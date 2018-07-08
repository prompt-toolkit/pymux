from __future__ import unicode_literals
from prompt_toolkit.utils import is_windows
__all__ = [
    'create_client',
    'list_clients',
]


def create_client(socket_name):
    if is_windows():
        from .windows import WindowsClient
        return WindowsClient()
    else:
        from .posix import PosixClient
        return PosixClient(socket_name)


def list_clients():
    if is_windows():
        from .windows import list_clients
        return list_clients()
    else:
        from .posix import list_clients
        return list_clients()
