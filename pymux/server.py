import json
from asyncio import create_task
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ContextManager,
    Dict,
    List,
    Optional,
    TextIO,
    cast,
)

from prompt_toolkit.application.current import set_app
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input.vt100_parser import Vt100Parser
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.utils import is_windows
from prompt_toolkit.input.defaults import create_pipe_input

from .log import logger
from .pipes import BrokenPipeError

if TYPE_CHECKING:
    from pymux.main import Pymux, ClientState

__all__ = ["ServerConnection"]


class ServerConnection:
    """
    For each client that connects, we have one instance of this class.
    """

    def __init__(self, pymux: "Pymux", pipe_connection) -> None:
        self.pymux = pymux

        self.pipe_connection = pipe_connection

        self.size = Size(rows=20, columns=80)
        self._closed = False

        self._recv_buffer = b""
        self.client_state: Optional["ClientState"] = None

        def feed_key(key) -> None:
            if self.client_state is not None:
                self.client_state.app.key_processor.feed(key)
                self.client_state.app.key_processor.process_keys()

        self._inputstream = Vt100Parser(feed_key)
        self._pipeinput = _ClientInput(self._send_packet)

        create_task(self._start_reading())

    async def _start_reading(self) -> None:
        while True:
            try:
                data = await self.pipe_connection.read()
                self._process(data)
            except BrokenPipeError:
                self.detach_and_close()
                break

            except Exception as e:
                import traceback

                traceback.print_stack()
                print("got exception ", repr(e))
                break

    def _process(self, data: str) -> None:
        """
        Process packet received from client.
        """
        try:
            packet = json.loads(data)
        except ValueError:
            # So far, this never happened. But it would be good to have some
            # protection.
            logger.warning("Received invalid JSON from client. Ignoring.")
            return

        # Handle commands.
        if packet["cmd"] == "run-command":
            self._run_command(packet)

        # Handle stdin.
        elif packet["cmd"] == "in":
            self._pipeinput.send_text(packet["data"])

        # Set size. (The client reports the size.)
        elif packet["cmd"] == "size":
            rows, columns = packet["data"]
            self.size = Size(rows=rows, columns=columns)
            self.pymux.invalidate()

        # Start GUI. (Create CommandLineInterface front-end for pymux.)
        elif packet["cmd"] == "start-gui":
            detach_other_clients = bool(packet["detach-others"])
            color_depth = ColorDepth(packet["color-depth"])
            term = packet["term"]

            if detach_other_clients:
                for c in self.pymux.connections:
                    c.detach_and_close()

            print("Create app...")
            self._create_app(color_depth=color_depth, term=term)

    def _send_packet(self, data: object) -> None:
        """
        Send packet to client.
        """
        if self._closed:
            return

        data = json.dumps(data)

        async def send() -> None:
            try:
                await self.pipe_connection.write(data)
            except BrokenPipeError:
                self.detach_and_close()

        create_task(send())

    def _run_command(self, packet: Dict[str, Any]) -> None:
        """
        Execute a run command from the client.
        """
        create_temp_cli = self.client_state is None

        if create_temp_cli:
            # If this client doesn't have a CLI. Create a Fake CLI where the
            # window containing this pane, is the active one. (The CLI instance
            # will be removed before the render function is called, so it doesn't
            # hurt too much and makes the code easier.)
            pane_id = int(packet["pane_id"])
            self._create_app()
            with set_app(self.client_state.app):
                self.pymux.arrangement.set_active_window_from_pane_id(pane_id)

        with set_app(self.client_state.app):
            try:
                self.pymux.handle_command(packet["data"])
            finally:
                self._close_connection()

    def _create_app(
        self, color_depth: ColorDepth = ColorDepth.DEPTH_8_BIT, term: str = "xterm"
    ) -> None:
        """
        Create CommandLineInterface for this client.
        Called when the client wants to attach the UI to the server.
        """
        output = Vt100_Output(
            cast(TextIO, _SocketStdout(self._send_packet)),
            lambda: self.size,
            term=term,
            # write_binary=False,
        )

        client_state = self.pymux.add_client(
            input=self._pipeinput,
            output=output,
            connection=self,
            color_depth=color_depth,
        )
        self.client_state = client_state

        async def run() -> None:
            await client_state.app.run_async()
            self._close_connection()

        create_task(run())

    def _close_connection(self) -> None:
        # This is important. If we would forget this, the server will
        # render CLI output for clients that aren't connected anymore.
        self.pymux.remove_client(self)
        self.client_state = None
        self._closed = True

        # Remove from eventloop.
        self.pipe_connection.close()

    def suspend_client_to_background(self) -> None:
        """
        Ask the client to suspend itself. (Like, when Ctrl-Z is pressed.)
        """
        self._send_packet({"cmd": "suspend"})

    def detach_and_close(self) -> None:
        # Remove from Pymux.
        self._close_connection()


class _SocketStdout:
    """
    Stdout-like object that writes everything through the unix socket to the
    client.
    """

    def __init__(self, send_packet: Callable) -> None:
        self.send_packet = send_packet
        self._buffer: List[str] = []

    def write(self, data: str) -> int:
        self._buffer.append(data)
        return len(data)

    def flush(self) -> None:
        data = {"cmd": "out", "data": "".join(self._buffer)}
        self.send_packet(data)
        self._buffer = []

    def isatty(self) -> bool:
        return True


class _ClientInput:
    """
    Input class that can be given to the CommandLineInterface.
    We only need this for turning the client into raw_mode/cooked_mode.
    """

    def __init__(self, send_packet: Callable) -> None:
        self.send_packet = send_packet
        self._input = create_pipe_input().__enter__()  # TODO: use as context manager.

    # Implement raw/cooked mode by sending this to the attached client.

    def raw_mode(self) -> ContextManager[None]:
        return self._create_context_manager("raw")

    def cooked_mode(self) -> ContextManager[None]:
        return self._create_context_manager("cooked")

    def _create_context_manager(self, mode: str) -> ContextManager[None]:
        "Create a context manager that sends 'mode' commands to the client."

        class mode_context_manager:
            def __enter__(*a: object) -> None:
                self.send_packet({"cmd": "mode", "data": mode})

            def __exit__(*a: object) -> None:
                self.send_packet({"cmd": "mode", "data": "restore"})

        return mode_context_manager()

    def __getattr__(self, name: str) -> object:
        return getattr(self._input, name)
