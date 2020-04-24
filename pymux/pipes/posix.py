import getpass
import os
import socket
import tempfile
from asyncio import Future, get_event_loop
from typing import Callable, Optional

from ..log import logger
from .base import BrokenPipeError, PipeConnection

__all__ = [
    "bind_and_listen_on_posix_socket",
    "PosixSocketConnection",
]


def bind_and_listen_on_posix_socket(socket_name: str, accept_callback: Callable):
    """
    :param accept_callback: Called with `PosixSocketConnection` when a new
        connection is established.
    """
    # Py2 uses 0027 and Py3 uses 0o027, but both know
    # how to create the right value from the string '0027'.
    old_umask = os.umask(int("0027", 8))

    # Bind socket.
    socket_name, socket = _bind_posix_socket(socket_name)

    _ = os.umask(old_umask)

    # Listen on socket.
    socket.listen(0)

    def _accept_cb():
        connection, client_address = socket.accept()
        # Note: We don't have to put this socket in non blocking mode.
        #       This can cause crashes when sending big packets on OS X.

        posix_connection = PosixSocketConnection(connection)

        accept_callback(posix_connection)

    get_event_loop().add_reader(socket.fileno(), _accept_cb)

    logger.info("Listening on %r." % socket_name)
    return socket_name


def _bind_posix_socket(socket_name: Optional[str] = None):
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
                socket_name = "%s/pymux.sock.%s.%i" % (
                    tempfile.gettempdir(),
                    getpass.getuser(),
                    i,
                )
                s.bind(socket_name)
                return socket_name, s
            except (OSError, socket.error):
                i += 1

                # When 100 times failed, cancel server
                if i == 100:
                    logger.warning(
                        "100 times failed to listen on posix socket. "
                        "Please clean up old sockets."
                    )
                    raise


class PosixSocketConnection(PipeConnection):
    """
    A single active posix pipe connection on the server side.
    """

    def __init__(self, socket):
        self.socket = socket
        self._fd = socket.fileno()
        self._recv_buffer = b""

    async def read(self):
        r"""
        Coroutine that reads the next packet.
        (Packets are \0 separated.)
        """
        # Read until we have a \0 in our buffer.
        while b"\0" not in self._recv_buffer:
            self._recv_buffer += await _read_chunk_from_socket(self.socket)

        # Split on the first separator.
        pos = self._recv_buffer.index(b"\0")

        packet = self._recv_buffer[:pos]
        self._recv_buffer = self._recv_buffer[pos + 1 :]

        return packet

    def write(self, message):
        """
        Coroutine that writes the next packet.
        """
        try:
            self.socket.send(message.encode("utf-8") + b"\0")
        except socket.error:
            if not self._closed:
                raise BrokenPipeError

        f = Future()
        f.set_result(None)
        return f

    def close(self):
        """
        Close connection.
        """
        self.socket.close()

        # Make sure to remove the reader from the event loop.
        get_event_loop().remove_reader(self._fd)


def _read_chunk_from_socket(socket):
    """
    (coroutine)
    Turn socket reading into coroutine.
    """
    fd = socket.fileno()
    f = Future()

    def read_callback():
        get_event_loop().remove_reader(fd)

        # Read next chunk.
        try:
            data = socket.recv(1024)
        except OSError as e:
            # On OSX, when we try to create a new window by typing "pymux
            # new-window" in a centain pane, very often we get the following
            # error: "OSError: [Errno 9] Bad file descriptor."
            # This doesn't seem very harmful, and we can just try again.
            logger.warning(
                "Got OSError while reading data from client: %s. " "Trying again.", e
            )
            f.set_result("")
            return

        if data:
            f.set_result(data)
        else:
            f.set_exception(BrokenPipeError)

    get_event_loop().add_reader(fd, read_callback)

    return f
