"""
Platform specific (Windows+posix) implementations for inter process
communication through pipes between the Pymux server and clients.
"""
from prompt_toolkit.utils import is_windows

from .base import BrokenPipeError, PipeConnection

__all__ = [
    "bind_and_listen_on_socket",
    # Base.
    "PipeConnection",
    "BrokenPipeError",
]


def bind_and_listen_on_socket(socket_name, accept_callback):
    """
    Return socket name.

    :param accept_callback: Callback is called with a `PipeConnection` as
        argument.
    """
    if is_windows():
        from .win32_server import bind_and_listen_on_win32_socket

        return bind_and_listen_on_win32_socket(socket_name, accept_callback)
    else:
        from .posix import bind_and_listen_on_posix_socket

        return bind_and_listen_on_posix_socket(socket_name, accept_callback)
