from ctypes import windll, byref
from ctypes.wintypes import DWORD
from prompt_toolkit.eventloop import From, Future, Return
from ptterm.backends.win32_pipes import OVERLAPPED

from .win32 import wait_for_event, create_event, read_message_from_pipe, write_message_to_pipe
from .log import logger

INSTANCES = 10
BUFSIZE = 4096

# CreateNamedPipeW flags.
# See: https://docs.microsoft.com/en-us/windows/desktop/api/winbase/nf-winbase-createnamedpipea
PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_NOWAIT = 0x00000001

ERROR_IO_PENDING = 997
ERROR_BROKEN_PIPE= 109
ERROR_NO_DATA = 232

CONNECTING_STATE = 0
READING_STATE = 1
WRITING_STATE = 2


class Win32PipeConnection(object):
    def __init__(self, pipe_instance):
        self.pipe_instance = pipe_instance
        self.done_f = Future()

    def read(self):
        if self.done_f.done():
            raise _BrokenPipeError

        try:
            result = yield From(read_message_from_pipe(self.pipe_instance.pipe_handle))
            raise Return(result)
        except _BrokenPipeError:
            self.done_f.set_result(None)
            raise

    def write(self, message):
        if self.done_f.done():
            raise _BrokenPipeError

        try:
            yield From(write_message_to_pipe(self.pipe_instance.pipe_handle, message))
        except _BrokenPipeError:
            self.done_f.set_result(None)
            raise

    def close(self):
        pass


class PipeInstance(object):
    def __init__(self, pipe_name, instances=INSTANCES, buffsize=BUFSIZE,
                 timeout=5000, pipe_connection_cb=None):

        self.pipe_handle = windll.kernel32.CreateNamedPipeW(
            pipe_name,  # Pipe name.
            PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
            DWORD(instances), # Max instances. (TODO: increase).
            DWORD(buffsize),  # Output buffer size.
            DWORD(buffsize),  # Input buffer size.
            DWORD(timeout),  # Client time-out.
            None, # Default security attributes.
        )
        self.pipe_connection_cb = pipe_connection_cb

        if not self.pipe_handle:
            raise Exception('invalid pipe')

    def handle_pipe(self):
        """
        Coroutine that handles this pipe.
        """
        while True:
            yield From(self._handle_client())

    def _handle_client(self):
        """
        Coroutine that connects to a single client and handles that.
        """
        while True:
            try:
                # Wait for connection.
                logger.info('Waiting for connection in pipe instance.')
                yield From(self._connect_client())
                logger.info('Connected in pipe instance')

                conn = Win32PipeConnection(self)
                self.pipe_connection_cb(conn)

                yield From(conn.done_f)
                logger.info('Pipe instance done.')

            finally:
                # Disconnect and reconnect.
                logger.info('Disconnecting pipe instance.')
                windll.kernel32.DisconnectNamedPipe(self.pipe_handle)

    def _connect_client(self):
        """
        Wait for a client to connect to this pipe.
        """
        overlapped = OVERLAPPED()
        overlapped.hEvent = create_event()

        while True:
            success = windll.kernel32.ConnectNamedPipe(
                self.pipe_handle,
                byref(overlapped))

            if success:
                return

            last_error = windll.kernel32.GetLastError()
            if last_error == ERROR_IO_PENDING:
                yield From(wait_for_event(overlapped.hEvent))

                # XXX: Call GetOverlappedResult.
                return  # Connection succeeded.

            else:
                raise Exception('connect failed with error code' + str(last_error))


class _BrokenPipeError(Exception):
    pass
