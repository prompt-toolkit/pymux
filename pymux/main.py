from __future__ import unicode_literals

from prompt_toolkit.application import Application
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer, AcceptAction
from prompt_toolkit.buffer_mapping import BufferMapping
from prompt_toolkit.enums import DUMMY_BUFFER, EditingMode
from prompt_toolkit.eventloop.callbacks import EventLoopCallbacks
from prompt_toolkit.eventloop.posix import PosixEventLoop
from prompt_toolkit.filters import Condition
from prompt_toolkit.input import PipeInput
from prompt_toolkit.interface import CommandLineInterface
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.layout.screen import Size
from prompt_toolkit.terminal.vt100_output import Vt100_Output, _get_size

from .arrangement import Arrangement, Pane, Window
from .commands.commands import handle_command, call_command_handler
from .commands.completer import create_command_completer
from .enums import COMMAND, PROMPT
from .key_bindings import KeyBindingsManager
from .layout import LayoutManager, Justify
from .log import logger
from .options import ALL_OPTIONS, ALL_WINDOW_OPTIONS
from .process import Process
from .rc import STARTUP_COMMANDS
from .server import ServerConnection, bind_socket
from .style import PymuxStyle
from .utils import get_default_shell

import os
import signal
import six
import sys
import tempfile
import threading
import time
import traceback
import weakref

__all__ = (
    'Pymux',
)


class ClientState(object):
    """
    State information that is independent for each client.
    """
    def __init__(self):
        #: True when the prefix key (Ctrl-B) has been pressed.
        self.has_prefix = False

        #: Error/info message.
        self.message = None

        # True when the command prompt is visible.
        self.command_mode = False

        # When a "confirm-before" command is running,
        # Show this text in the command bar. When confirmed, execute
        # confirm_command.
        self.confirm_text = None
        self.confirm_command = None

        # When a "command-prompt" command is running.
        self.prompt_text = None
        self.prompt_command = None


class Pymux(object):
    """
    The main Pymux application class.

    Usage:

        p = Pymux()
        p.listen_on_socket()
        p.run_server()

    Or:

        p = Pymux()
        p.run_standalone()
    """
    def __init__(self, source_file=None, startup_command=None):
        self.arrangement = Arrangement()
        self.layout_manager = LayoutManager(self)

        self._client_states = weakref.WeakKeyDictionary()  # Mapping from CLI to ClientState.

        # Options
        self.enable_mouse_support = True
        self.enable_status = True
        self.enable_pane_status = False
        self.enable_bell = True
        self.remain_on_exit = False
        self.status_keys_vi_mode = False
        self.mode_keys_vi_mode = False
        self.history_limit = 2000
        self.status_interval = 4
        self.default_terminal = 'xterm-256color'
        self.status_left = '[#S] '
        self.status_left_length = 20
        self.status_right = ' %H:%M %d-%b-%y '
        self.status_right_length = 20
        self.window_status_current_format = '#I:#W#F'
        self.window_status_format = '#I:#W#F'
        self.session_name = '0'
        self.status_justify = Justify.LEFT
        self.default_shell = get_default_shell()

        self.options = ALL_OPTIONS
        self.window_options = ALL_WINDOW_OPTIONS

        # When no panes are available.
        self.original_cwd = os.getcwd()

        self.display_pane_numbers = False

        #: List of clients.
        self._runs_standalone = False
        self.connections = []
        self.clis = {}  # Mapping from Connection to CommandLineInterface.

        self._startup_done = False
        self.source_file = source_file
        self.startup_command = startup_command

        # Keep track of all the panes, by ID. (For quick lookup.)
        self.panes_by_id = weakref.WeakValueDictionary()

        # Socket information.
        self.socket = None
        self.socket_name = None

        # Create eventloop.
        self.eventloop = PosixEventLoop()

        # Key bindings manager.
        self.key_bindings_manager = KeyBindingsManager(self)

        self.style = PymuxStyle()

    def _start_auto_refresh_thread(self):
        """
        Start the background thread that auto refreshes all clients according to
        `self.status_interval`.
        """
        def run():
            while True:
                time.sleep(self.status_interval)
                self.invalidate()

        t = threading.Thread(target=run)
        t.daemon = True
        t.start()

    def get_client_state(self, cli):
        """
        Return the ClientState instance for this CommandLineInterface.
        """
        try:
            return self._client_states[cli]
        except KeyError:
            s = ClientState()
            self._client_states[cli] = s
            return s

    def get_title(self, cli):
        """
        The title to be displayed in the titlebar of the terminal.
        """
        w = self.arrangement.get_active_window(cli)

        if w and w.active_process:
            title = w.active_process.screen.title
        else:
            title = ''

        if title:
            return '%s - Pymux' % (title, )
        else:
            return 'Pymux'

    def get_window_size(self, cli):
        """
        Get the size to be used for the DynamicBody.
        This will be the smallest size of all clients.
        """
        get_active_window = self.arrangement.get_active_window
        active_window = get_active_window(cli)

        # Get connections watching the same window.
        connections = [c for c in self.connections if
                       c.cli and get_active_window(c.cli) == active_window]

        rows = [c.size.rows for c in connections]
        columns = [c.size.columns for c in connections]

        if self._runs_standalone:
            r, c = _get_size(sys.stdout.fileno())
            rows.append(r)
            columns.append(c)

        if rows and columns:
            return Size(rows=min(rows) - (1 if self.enable_status else 0),
                        columns=min(columns))
        else:
            return Size(rows=20, columns=80)

    def _create_pane(self, window=None, command=None, start_directory=None):
        """
        Create a new :class:`pymux.arrangement.Pane` instance. (Don't put it in
        a window yet.)

        :param window: If a window is given, take the CWD of the current
            process of that window as the start path for this pane.
        :param command: If given, run this command instead of `self.default_shell`.
        :param start_directory: If given, use this as the CWD.
        """
        assert window is None or isinstance(window, Window)
        assert command is None or isinstance(command, six.text_type)
        assert start_directory is None or isinstance(start_directory, six.text_type)

        def done_callback():
            " When the process finishes. "
            if not self.remain_on_exit:
                # Remove pane from layout.
                self.arrangement.remove_pane(pane)

                # No panes left? -> Quit.
                if not self.arrangement.has_panes:
                    self.eventloop.stop()

            self.invalidate()

        def bell():
            " Sound bell on all clients. "
            if self.enable_bell:
                for c in self.clis.values():
                    c.output.bell()

        # Start directory.
        if start_directory:
            path = start_directory
        elif window and window.active_process:
            # When the path of the active process is known,
            # start the new process at the same location.
            path = window.active_process.get_cwd()
        else:
            path = None

        def before_exec():
            " Called in the process fork (in the child process). "
            # Go to this directory.
            try:
                os.chdir(path or self.original_cwd)
            except OSError:
                pass  # No such file or directory.

            # Set terminal variable. (We emulate xterm.)
            os.environ['TERM'] = self.default_terminal

            # Make sure to set the PYMUX environment variable.
            if self.socket_name:
                os.environ['PYMUX'] = '%s,%i' % (
                    self.socket_name, pane.pane_id)

        if command:
            command = command.split()
        else:
            command = [self.default_shell]

        # Create process and pane.
        def has_priority():
            return self.arrangement.pane_has_priority(pane)

        process = Process.from_command(
            self.eventloop, self.invalidate, command, done_callback,
            bell_func=bell,
            before_exec_func=before_exec,
            has_priority=has_priority)

        pane = Pane(process)

        # Keep track of panes. This is a WeakKeyDictionary, we only add, but
        # don't remove.
        self.panes_by_id[pane.pane_id] = pane

        logger.info('Created process %r.', command)
        process.start()

        return pane

    def invalidate(self):
        " Invalidate the UI for all clients. "
        for c in self.clis.values():
            c.invalidate()

    def create_window(self, cli=None, command=None, start_directory=None, name=None):
        """
        Create a new :class:`pymux.arrangement.Window` in the arrangement.

        :param cli: If been given, this window will be focussed for that client.
        """
        assert cli is None or isinstance(cli, CommandLineInterface)
        assert command is None or isinstance(command, six.text_type)
        assert start_directory is None or isinstance(start_directory, six.text_type)

        pane = self._create_pane(None, command, start_directory=start_directory)

        self.arrangement.create_window(cli, pane, name=name)
        self.invalidate()

    def add_process(self, cli, command=None, vsplit=False, start_directory=None):
        """
        Add a new process to the current window. (vsplit/hsplit).
        """
        assert isinstance(cli, CommandLineInterface)
        assert command is None or isinstance(command, six.text_type)
        assert start_directory is None or isinstance(start_directory, six.text_type)

        window = self.arrangement.get_active_window(cli)

        pane = self._create_pane(window, command, start_directory=start_directory)
        window.add_pane(pane, vsplit=vsplit)
        self.invalidate()

    def kill_pane(self, pane):
        """
        Kill the given pane, and remove it from the arrangement.
        """
        assert isinstance(pane, Pane)

        # Send kill signal.
        if not pane.process.is_terminated:
            pane.process.send_signal(signal.SIGKILL)

        # Remove from layout.
        self.arrangement.remove_pane(pane)

        # No panes left? -> Quit.
        if not self.arrangement.has_panes:
            self.eventloop.stop()

    def leave_command_mode(self, cli, append_to_history=False):
        """
        Leave the command/prompt mode.
        """
        cli.buffers[COMMAND].reset(append_to_history=append_to_history)
        cli.buffers[PROMPT].reset(append_to_history=True)

        client_state = self.get_client_state(cli)
        client_state.command_mode = False
        client_state.prompt_command = ''
        client_state.confirm_command = ''

    def handle_command(self, cli, command):
        """
        Handle command from the command line.
        """
        handle_command(self, cli, command)

    def show_message(self, cli, message):
        """
        Set a warning message. This will be shown at the bottom until a key has
        been pressed.

        :param cli: CommandLineInterface instance. (The client.)
        :param message: String.
        """
        self.get_client_state(cli).message = message

    def create_cli(self, connection, output, input=None):
        """
        Create `CommandLineInterface` instance for this connection.
        """
        def get_title():
            return self.get_title(cli)

        def on_focus_changed():
            """ When the focus changes to a read/write buffer, make sure to go
            to insert mode. This happens when the ViState was set to NAVIGATION
            in the copy buffer. """
            vi_state = cli.vi_state

            if cli.current_buffer.read_only():
                vi_state.input_mode = InputMode.NAVIGATION
            else:
                vi_state.input_mode = InputMode.INSERT

        application = Application(
            layout=self.layout_manager.layout,
            key_bindings_registry=self.key_bindings_manager.registry,
            buffers=_BufferMapping(self),
            mouse_support=Condition(lambda cli: self.enable_mouse_support),
            use_alternate_screen=True,
            style=self.style,
            get_title=get_title,
            on_invalidate=(lambda cli: self.invalidate()))

        cli = CommandLineInterface(
            application=application,
            output=output,
            input=input,
            eventloop=self.eventloop)

        # Synchronize the Vi state with the CLI object.
        # (This is stored in the current class, but expected to be in the
        # CommandLineInterface.)
        def sync_vi_state(_):
            client_state = self.get_client_state(cli)
            VI = EditingMode.VI
            EMACS = EditingMode.EMACS

            if (client_state.confirm_text or client_state.prompt_command or
                    client_state.command_mode):
                cli.editing_mode = VI if self.status_keys_vi_mode else EMACS
            else:
                cli.editing_mode = VI if self.mode_keys_vi_mode else EMACS

        cli.input_processor.beforeKeyPress += sync_vi_state
        cli.input_processor.afterKeyPress += sync_vi_state

        # Set render postpone time. (.1 instead of 0).
        # This small change ensures that if for a split second a process
        # outputs a lot of information, we don't give the highest priority to
        # rendering output. (Nobody reads that fast in real-time.)
        cli.max_render_postpone_time = .1  # Second.

        # Hide message when a key has been pressed.
        def key_pressed(_):
            self.get_client_state(cli).message = None
        cli.input_processor.beforeKeyPress += key_pressed

        cli._is_running = True

        self.clis[connection] = cli

        # Redraw all CLIs. (Adding a new client could mean that the others
        # change size, so everything has to be redrawn.)
        self.invalidate()

        # Handle start-up comands.
        # (Does initial key bindings.)
        if not self._startup_done:
            self._startup_done = True

            # Execute default config.
            for cmd in STARTUP_COMMANDS.splitlines():
                self.handle_command(cli, cmd)

            # Source the given file.
            if self.source_file:
                call_command_handler('source-file', self, cli, [self.source_file])

            # Make sure that there is one window created.
            self.create_window(cli, command=self.startup_command)

        return cli

    def get_connection_for_cli(self, cli):
        """
        Return the `CommandLineInterface` instance for this connection, if any.
        `None` otherwise.
        """
        for connection, c in self.clis.items():
            if c == cli:
                return connection

    def detach_client(self, cli):
        """
        Detach the client that belongs to this CLI.
        """
        connection = self.get_connection_for_cli(cli)

        if connection is not None:
            connection.detach_and_close()

        # Redraw all clients -> Maybe their size has to change.
        self.invalidate()

    def listen_on_socket(self, socket_name=None):
        """
        Listen for clients on a Unix socket.
        Returns the socket name.
        """
        if self.socket is None:
            # Py2 uses 0027 and Py3 uses 0o027, but both know
            # how to create the right value from the string '0027'.
            old_umask = os.umask(int('0027', 8))
            self.socket_name, self.socket = bind_socket(socket_name)
            _ = os.umask(old_umask)
            self.socket.listen(0)
            self.eventloop.add_reader(self.socket.fileno(), self._socket_accept)

        # Set session_name according to socket name.
        if '.' in self.socket_name:
            self.session_name = self.socket_name.rpartition('.')[-1]

        logger.info('Listening on %r.' % self.socket_name)
        return self.socket_name

    def _socket_accept(self):
        """
        Accept connection from client.
        """
        logger.info('Client attached.')

        connection, client_address = self.socket.accept()
        # Note: We don't have to put this socket in non blocking mode.
        #       This can cause crashes when sending big packets on OS X.

        connection = ServerConnection(self, connection, client_address)
        self.connections.append(connection)

    def run_server(self):
        # Ignore keyboard. (When people run "pymux server" and press Ctrl-C.)
        # Pymux has to be terminated by termining all the processes running in
        # its panes.
        def handle_sigint(*a):
            print('Ignoring keyboard interrupt.')

        signal.signal(signal.SIGINT, handle_sigint)

        # Start background threads.
        self._start_auto_refresh_thread()

        # Run eventloop.

        # XXX: Both the PipeInput and DummyCallbacks are not used.
        #      This is a workaround to run the PosixEventLoop continuously
        #      without having a CommandLineInterface instance.
        #      A better API in prompt_toolkit is desired.
        try:
            self.eventloop.run(
                PipeInput(), DummyCallbacks())
        except:
            # When something bad happens, always dump the traceback.
            # (Otherwise, when running as a daemon, and stdout/stderr are not
            # available, it's hard to see what went wrong.)
            fd, path = tempfile.mkstemp(prefix='pymux.crash-')
            logger.fatal(
                'Pymux has crashed, dumping traceback to {0}'.format(path))
            os.write(fd, traceback.format_exc().encode('utf-8'))
            os.close(fd)
            raise

        finally:
            # Clean up socket.
            os.remove(self.socket_name)

    def run_standalone(self, true_color=False, ansi_colors_only=False):
        """
        Run pymux standalone, rather than using a client/server architecture.
        This is mainly useful for debugging.
        """
        self._runs_standalone = True
        self._start_auto_refresh_thread()
        cli = self.create_cli(
            connection=None,
            output=Vt100_Output.from_pty(
                sys.stdout, true_color=true_color, ansi_colors_only=ansi_colors_only))
        cli._is_running = False
        cli.run()


class _BufferMapping(BufferMapping):
    """
    Container for all the Buffer objects in a CommandLineInterface.
    """
    def __init__(self, pymux):
        self.pymux = pymux

        def _handle_command(cli, buffer):
            " When text is accepted in the command line. "
            text = buffer.text

            # First leave command mode. We want to make sure that the working
            # pane is focussed again before executing the command handers.
            pymux.leave_command_mode(cli, append_to_history=True)

            # Execute command.
            pymux.handle_command(cli, text)

        def _handle_prompt_command(cli, buffer):
            " When a command-prompt command is accepted. "
            text = buffer.text
            client_state = pymux.get_client_state(cli)
            prompt_command = client_state.prompt_command

            # Leave command mode and handle command.
            pymux.leave_command_mode(cli, append_to_history=True)
            pymux.handle_command(cli, prompt_command.replace('%%', text))

        super(_BufferMapping, self).__init__({
            COMMAND: Buffer(
                complete_while_typing=True,
                completer=create_command_completer(pymux),
                accept_action=AcceptAction(handler=_handle_command),
                auto_suggest=AutoSuggestFromHistory(),
            ),
            PROMPT: Buffer(
                accept_action=AcceptAction(handler=_handle_prompt_command),
                auto_suggest=AutoSuggestFromHistory(),
            ),
        })

    def __getitem__(self, name):
        " Override __getitem__ to make lookup of pane- buffers dynamic. "
        if name.startswith('pane-'):
            try:
                id = int(name[len('pane-'):])
                return self.pymux.panes_by_id[id].scroll_buffer
            except (ValueError, KeyError):
                raise KeyError

        elif name.startswith('search-'):
            try:
                id = int(name[len('search-'):])
                return self.pymux.panes_by_id[id].search_buffer
            except (ValueError, KeyError):
                raise KeyError
        else:
            return super(_BufferMapping, self).__getitem__(name)

    def current(self, cli):
        """
        Return the currently focussed Buffer.
        """
        return self[self.current_name(cli)]

    def current_name(self, cli):
        """
        Name of the current buffer.
        """
        client_state = self.pymux.get_client_state(cli)

        # Confirm.
        if client_state.confirm_text:
            return DUMMY_BUFFER

        # Custom prompt.
        if client_state.prompt_command:
            return PROMPT

        # Command mode.
        if client_state.command_mode:
            return COMMAND

        # Copy/search mode.
        pane = self.pymux.arrangement.get_active_pane(cli)

        if pane and pane.display_scroll_buffer:
            if pane.is_searching:
                return 'search-%i' % pane.pane_id
            else:
                return 'pane-%i' % pane.pane_id

        return DUMMY_BUFFER

    def focus(self, cli, buffer_name):
        """
        Focus buffer with the given name.

        Called when a :class:`BufferControl` in the layout has been clicked.
        Make sure that we focus the pane in the :class:`.Arrangement`.
        """
        self._focus(cli, buffer_name)
        super(_BufferMapping, self).focus(cli, buffer_name)

    def push(self, cli, buffer_name):
        """
        Push to focus stack.
        """
        self._focus(cli, buffer_name)
        super(_BufferMapping, self).push(cli, buffer_name)

    def _focus(self, cli, buffer_name):
        if buffer_name.startswith('pane-'):
            id = int(buffer_name[len('pane-'):])
            pane = self.pymux.panes_by_id[id]

            w = self.pymux.arrangement.get_active_window(cli)
            w.active_pane = pane


class DummyCallbacks(EventLoopCallbacks):
    " Required in order to call eventloop.run() without having a CLI instance. "
    def terminal_size_changed(self): pass
    def input_timeout(self): pass
    def feed_key(self, key): pass
