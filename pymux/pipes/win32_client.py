from __future__ import unicode_literals
from .win32 import read_message_from_pipe, write_message_to_pipe, connect_to_pipe
from ctypes import windll
from prompt_toolkit.eventloop import From, Return
import six

__all__ = [
    'PipeClient',
]


class PipeClient(object):
    r"""
    Windows pipe client.

    :param pipe_name: Name of the pipe. E.g. \\.\pipe\pipe_name
    """
    def __init__(self, pipe_name):
        assert isinstance(pipe_name, six.text_type)
        self.pipe_handle = connect_to_pipe(pipe_name)

    def write_message(self, text):
        """
        (coroutine)
        Write message into the pipe.
        """
        yield From(write_message_to_pipe(self.pipe_handle, text))

    def read_message(self):
        """
        (coroutine)
        Read one single message from the pipe and return as text.
        """
        message = yield From(read_message_from_pipe(self.pipe_handle))
        raise Return(message)

    def close(self):
        """
        Close the connection.
        """
        windll.kernel32.CloseHandle(self.pipe_handle)
