from __future__ import unicode_literals
from abc import ABCMeta, abstractmethod
from six import with_metaclass

__all__ = [
    'PipeConnection',
    'BrokenPipeError',
]


class PipeConnection(with_metaclass(ABCMeta, object)):
    """
    A single active Win32 pipe connection on the server side.

    - Win32PipeConnection
    """
    @abstractmethod
    def read(self):
        """
        (coroutine)
        Read a single message from the pipe. (Return as text.)

        This can can BrokenPipeError.
        """

    @abstractmethod
    def write(self, message):
        """
        (coroutine)
        Write a single message into the pipe.

        This can can BrokenPipeError.
        """

    @abstractmethod
    def close(self):
        """
        Close connection.
        """


class BrokenPipeError(Exception):
    " Raised when trying to write to or read from a broken pipe. "
