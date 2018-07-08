from __future__ import unicode_literals
import getpass
import json
import socket
import tempfile

from prompt_toolkit.eventloop import get_event_loop
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input.vt100 import PipeInput
from prompt_toolkit.input.vt100_parser import Vt100Parser
from prompt_toolkit.layout.screen import Size
from prompt_toolkit.output.vt100 import Vt100_Output
from functools import partial

from .log import logger
import win32file

__all__ = (
    'ServerConnection',
    'bind_socket',
)


class ServerConnection(object):
    """
    For each client that connects, we have one instance of this class.
    """
    def __init__(self, pymux, socket):
        self.pymux = pymux

        self.socket = socket
        self.handle = socket.handle

        self.connection = socket.handle
        self.size = Size(rows=20, columns=80)
        self._closed = False

        self._recv_buffer = b''
        self.client_state = None

        def feed_key(key):
            self.client_state.app.key_processor.feed(key)
            self.client_state.app.key_processor.process_keys()

        self._inputstream = Vt100Parser(feed_key)
        self._pipeinput = _ClientInput(self._send_packet)

        print('add win32 handle', socket, socket.handle)
#        if connection:  # XXX: not sure why we get '0' the first time.
#            get_event_loop().add_win32_handle(connection, self._win_recv)

        if socket.handle:  # XXX: not sure why we get '0' the first time.
            get_event_loop().run_in_executor(self._start_reader_thread)

    def _start_reader_thread(self):
        while True:
            print('Reading')
            num, data = win32file.ReadFile(self.socket, 4096)
            print('Received', repr(num), repr(data))

            get_event_loop().call_from_executor(
                partial(self._process_chunk, data))

#    def _win_recv(self):
#        print('win recv')
#        data = win32file.ReadFile(self.connection, 4096)
#        print('received', repr(data))

    def _process_chunk(self, data):
        """
        Data received from the client.
        (Parse it.)
        """
        if data == b'':
            # End of file. Close connection.
            self.detach_and_close()
        else:
            # Receive and process packets.
            self._recv_buffer += data

            while b'\0' in self._recv_buffer:
                # Zero indicates end of packet.
                pos = self._recv_buffer.index(b'\0')
                self._process(self._recv_buffer[:pos])
                self._recv_buffer = self._recv_buffer[pos + 1:]

    def _process(self, data):
        """
        Process packet received from client.
        """
        try:
            packet = json.loads(data.decode('utf-8'))
        except ValueError:
            # So far, this never happened. But it would be good to have some
            # protection.
            logger.warning('Received invalid JSON from client. Ignoring.')
            return

        print('Received packet: ', repr(packet))

        # Handle commands.
        if packet['cmd'] == 'run-command':
            self._run_command(packet)

        # Handle stdin.
        elif packet['cmd'] == 'in':
            self._pipeinput.send_text(packet['data'])

#        elif packet['cmd'] == 'flush-input':
#            self._inputstream.flush()  # Flush escape key.  # XXX: I think we no longer need this.

        # Set size. (The client reports the size.)
        elif packet['cmd'] == 'size':
            data = packet['data']
            self.size = Size(rows=data[0], columns=data[1])
            self.pymux.invalidate()

        # Start GUI. (Create CommandLineInterface front-end for pymux.)
        elif packet['cmd'] == 'start-gui':
            detach_other_clients = bool(packet['detach-others'])
            color_depth = packet['color-depth']
            term = packet['term']

            if detach_other_clients:
                for c in self.pymux.connections:
                    c.detach_and_close()

            print('Create app...')
            self._create_app(color_depth=color_depth, term=term)

    def _send_packet(self, data):
        """
        Send packet to client.
        """
#        import time; time.sleep(2)
        data = json.dumps(data).encode('utf-8') + b'\0'

        def send():
            try:
                print('sending', repr(data))
                win32file.WriteFile(self.socket, data)
                print('Sent')
                #self.connection.send(json.dumps(data).encode('utf-8') + b'\0')
            except socket.error as e:
                print('Error sending', e)
                if not self._closed:
                    self.detach_and_close()
            except Exception as e:
                print('Error sending', e)

        get_event_loop().run_in_executor(send)

    def _run_command(self, packet):
        """
        Execute a run command from the client.
        """
        create_temp_cli = self.client_states is None

        if create_temp_cli:
            # If this client doesn't have a CLI. Create a Fake CLI where the
            # window containing this pane, is the active one. (The CLI instance
            # will be removed before the render function is called, so it doesn't
            # hurt too much and makes the code easier.)
            pane_id = int(packet['pane_id'])
            self._create_app()
            with set_app(self.client_state.app):
                self.pymux.arrangement.set_active_window_from_pane_id(pane_id)

        with set_app(self.client_state.app):
            try:
                self.pymux.handle_command(packet['data'])
            finally:
                self._close_connection()

    def _create_app(self, color_depth, term='xterm'):
        """
        Create CommandLineInterface for this client.
        Called when the client wants to attach the UI to the server.
        """
        output = Vt100_Output(_SocketStdout(self._send_packet),
                              lambda: self.size,
                              term=term,
                              write_binary=False)

        self.client_state = self.pymux.add_client(
            input=self._pipeinput, output=output, connection=self, color_depth=color_depth)

        print('Start running app...')
        future = self.client_state.app.run_async()
        print('Start running app got future...', future)

        @future.add_done_callback
        def done(_):
            self._close_connection()

    def _close_connection(self):
        # This is important. If we would forget this, the server will
        # render CLI output for clients that aren't connected anymore.
        self.pymux.remove_client(self)
        self.client_state = None
        self._closed = True

    def suspend_client_to_background(self):
        """
        Ask the client to suspend itself. (Like, when Ctrl-Z is pressed.)
        """
        self._send_packet({'cmd': 'suspend'})

    def detach_and_close(self):
        # Remove from Pymux.
        self._close_connection()

        # Remove from eventloop.
        get_event_loop().remove_reader(self.connection.fileno())
        self.connection.close()


def bind_socket(socket_name=None):
    """
    Find a socket to listen on and return it.

    Returns (socket_name, sock_obj)
    """
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    if socket_name:
        s.bind(socket_name)
        return socket_name, s
    else:
        i = 0
        while True:
            try:
                socket_name = '%s/pymux.sock.%s.%i' % (
                    tempfile.gettempdir(), getpass.getuser(), i)
                s.bind(socket_name)
                return socket_name, s
            except (OSError, socket.error):
                i += 1

                # When 100 times failed, cancel server
                if i == 100:
                    logger.warning('100 times failed to listen on posix socket. '
                                   'Please clean up old sockets.')
                    raise


def bind_socket(socket_name=None):  # XXX: windows
    socket_name = r'\\.\pipe\pymux.sock.jonathan.42'

    buffsize = 65536  # TODO: XXX make smaller.

    import win32con
    import win32pipe
    import win32security
    sa = win32security.SECURITY_ATTRIBUTES()
    return socket_name, win32pipe.CreateNamedPipe(
        socket_name,  # Pipe name.
        win32con.PIPE_ACCESS_DUPLEX | win32con.FILE_FLAG_OVERLAPPED, #win32con.PIPE_ACCESS_OUTBOUND,  # Read/write access
        win32con.PIPE_TYPE_BYTE | win32con.PIPE_READMODE_BYTE,
        1, # Max instances. (TODO: increase).
        buffsize,  # Output buffer size.
        buffsize,  # Input buffer size.
        0,  # Client time-out.
        sa  # Security attributes.
    )
#########        1, 0, 0, 0, sa)


class _SocketStdout(object):
    """
    Stdout-like object that writes everything through the unix socket to the
    client.
    """
    def __init__(self, send_packet):
        assert callable(send_packet)
        self.send_packet = send_packet
        self._buffer = []

    def write(self, data):
        self._buffer.append(data)

    def flush(self):
        data = {'cmd': 'out', 'data': ''.join(self._buffer)}
        self.send_packet(data)
        self._buffer = []


class _ClientInput(PipeInput):
    """
    Input class that can be given to the CommandLineInterface.
    We only need this for turning the client into raw_mode/cooked_mode.
    """
    def __init__(self, send_packet):
        super(_ClientInput, self).__init__()
        assert callable(send_packet)
        self.send_packet = send_packet

    # Implement raw/cooked mode by sending this to the attached client.

    def raw_mode(self):
        return self._create_context_manager('raw')

    def cooked_mode(self):
        return self._create_context_manager('cooked')

    def _create_context_manager(self, mode):
        " Create a context manager that sends 'mode' commands to the client. "
        class mode_context_manager(object):
            def __enter__(*a):
                self.send_packet({'cmd': 'mode', 'data': mode})

            def __exit__(*a):
                self.send_packet({'cmd': 'mode', 'data': 'restore'})

        return mode_context_manager()
