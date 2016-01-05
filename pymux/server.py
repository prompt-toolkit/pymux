from __future__ import unicode_literals
import getpass
import json
import socket
import logging

from prompt_toolkit.layout.screen import Size
from prompt_toolkit.terminal.vt100_input import InputStream
from prompt_toolkit.terminal.vt100_output import Vt100_Output
from prompt_toolkit.input import Input

__all__ = (
    'ServerConnection',
    'bind_socket',
)


class ServerConnection(object):
    """
    For each client that connects, we have one instance of this class.
    """
    def __init__(self, pymux, connection, client_address):
        """(ServerConnection, type(pymux), type(connection),
        str) -> NoneType
        *Description*
        """
        self.pymux = pymux
        self.connection = connection
        self.client_address = client_address
        self.size = Size(rows=20, columns=80)
        self._closed = False

        self._recv_buffer = b''
        self.cli = None
        self._inputstream = InputStream(
            lambda key: self.cli.input_processor.feed_key(key))

        pymux.eventloop.add_reader(
            connection.fileno(), self._recv)

    def _recv(self):
        """
        Data received from the client.
        (Parse it.)
        """
        # Read next chunk.
        data = self.connection.recv(1024)

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
        packet = json.loads(data.decode('utf-8'))

        # Handle commands.
        if packet['cmd'] == 'run-command':
            self._run_command(packet)

        # Handle stdin.
        elif packet['cmd'] == 'in':
            self._inputstream.feed(packet['data'])

        elif packet['cmd'] == 'flush-input':
            self._inputstream.flush()  # Flush escape key.

        # Set size. (The client reports the size.)
        elif packet['cmd'] == 'size':
            data = packet['data']
            self.size = Size(rows=data[0], columns=data[1])
            self.pymux.invalidate()

        # Start GUI. (Create CommandLineInterface front-end for pymux.)
        elif packet['cmd'] == 'start-gui':
            detach_other_clients = bool(packet['detach-others'])
            true_color = bool(packet['true-color'])

            if detach_other_clients:
                for c in self.pymux.connections:
                    c.detach_and_close()

            self._create_cli(true_color=true_color)

    def _send_packet(self, data):
        """
        Send packet to client.
        """
        try:
            self.connection.send(json.dumps(data).encode('utf-8') + b'\0')
        except socket.error:
            if not self._closed:
                self.detach_and_close()

    def _run_command(self, packet):
        """
        Execute a run command from the client.
        """
        create_temp_cli = self.cli is None

        if create_temp_cli:
            # If this client doesn't have a CLI. Create a Fake CLI where the
            # window containing this pane, is the active one. (The CLI instance
            # will be removed before the render function is called, so it doesn't
            # hurt too much and makes the code easier.)
            pane_id = int(packet['pane_id'])
            self._create_cli()
            self.pymux.arrangement.set_active_window_from_pane_id(self.cli, pane_id)

        try:
            self.pymux.handle_command(self.cli, packet['data'])
        finally:
            self._close_cli()

    def _create_cli(self, true_color=False):
        """
        Create CommandLineInterface for this client.
        Called when the client wants to attach the UI to the server.
        """
        output = Vt100_Output(_SocketStdout(self._send_packet),
                              lambda: self.size,
                              true_color=true_color)
        input = _ClientInput(self._send_packet)
        self.cli = self.pymux.create_cli(self, output, input)

    def _close_cli(self):
        if self in self.pymux.clis:
            del self.pymux.clis[self]

        self.cli = None

    def suspend_client_to_background(self):
        """
        Ask the client to suspend itself. (Like, when Ctrl-Z is pressed.)
        """
        if self.cli:
            def suspend():
                self._send_packet({'cmd': 'suspend'})

            self.cli.run_in_terminal(suspend)

    def detach_and_close(self):
        # Remove from Pymux.
        self.pymux.connections.remove(self)

        # Remove from eventloop.
        self.pymux.eventloop.remove_reader(self.connection.fileno())
        self.connection.close()

        self._closed = True


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
                socket_name = '/tmp/pymux.sock.%s.%i' % (getpass.getuser(), i)
                s.bind(socket_name)
                return socket_name, s
            except (OSError, socket.error):
                i += 1

                # When 100 times failed, cancel server
                if i == 100:
                    logging.warning('100 times failed to listen on posix socket. '
                                    'Please clean up old sockets.')
                    raise


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


class _ClientInput(Input):
    """
    Input class that can be given to the CommandLineInterface.
    We only need this for turning the client into raw_mode/cooked_mode.
    """
    def __init__(self, send_packet):
        assert callable(send_packet)
        self.send_packet = send_packet

    def fileno(self):
        raise NotImplementedError

    def read(self):
        raise NotImplementedError

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
