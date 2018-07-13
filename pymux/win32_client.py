from ctypes import windll
from .win32 import read_message_from_pipe, wait_for_event, write_message_to_pipe, connect_to_pipe
from prompt_toolkit.eventloop import From, Return

__all__ = [
    'PipeClient',
]


class PipeClient(object):
    def __init__(self, pipe_name):
        self.pipe_handle = connect_to_pipe(pipe_name)

    def write_message(self, text):
        """
        (coroutine)
        Write data into the pipe.
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
        windll.kernel32.CloseHandle(self.pipe_handle)
