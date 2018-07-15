"""
Platform specific (Windows+posix) implementations for inter process
communication through pipes between the Pymux server and clients.
"""
from prompt_toolkit.utils import is_windows

__all__ = [
    'bind_and_listen_on_socket',
]


def bind_and_listen_on_socket(socket_name, accept_callback):
    """
    Return socket name.

    :param accept_callback: Callback with a `ServerConnection`.
    """
    if is_windows():
        from .win32server import bind_and_listen_on_win32_socket
        return bind_and_listen_on_win32_socket(socket_name, accept_callback)
    else:
        from .posix import bind_and_listen_on_posix_socket
        return bind_and_listen_on_posix_socket(socket_name, accept_callback)
