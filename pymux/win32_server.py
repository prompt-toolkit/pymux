#import win32security
from ctypes import windll
from ctypes.wintypes import BOOL, DWORD, HANDLE
from prompt_toolkit.eventloop import get_event_loop, ensure_future, From, Future, Return
import ctypes
import pywintypes
import win32
import win32api
import win32con
import win32file
import win32pipe
from ptterm.backends.win32_pipes import OVERLAPPED

socket_name = r'\\.\pipe\pymux.sock.jonathan.9942'

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
        print('Win32PipeConnection.read #0')
        if self.done_f.done():
            raise _BrokenPipeError

        try:
            print('Win32PipeConnection.read #1')
            result = yield From(self.pipe_instance.read())
            print('Win32PipeConnection.read #2')
            print('result=', type(result), repr(result))
            raise Return(result)
        except _BrokenPipeError:
            self.done_f.set_result(None)
            raise

    def write(self, message):
        if self.done_f.done():
            raise _BrokenPipeError

        try:
            yield From(self.pipe_instance.write(message))
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
#            try:
                # Wait for connection.
                print('wait for connection')
                yield From(self._connect_client())
                print('connected')

                conn = Win32PipeConnection(self)
                print('connected cb')
                self.pipe_connection_cb(conn)
                print('connected cb done, wait for done_f')

                yield From(conn.done_f)
                print('connected cb done, done_f done')

#                while True:
#                    # Wait for input.
#                    data = yield From(self._read())
#
#                    # Wait for output.
#                    yield From(self._write('Received: ' + data))
#            except _BrokenPipeError:
                # Disconnect and reconnect.
                print('disconnect')
                windll.kernel32.DisconnectNamedPipe(self.pipe_handle)

    def _connect_client(self):
        """
        Wait for a client to connect to this pipe.
        """
        overlapped = OVERLAPPED()
        overlapped.hEvent = _create_event()

        while True:
            success = windll.kernel32.ConnectNamedPipe(
                self.pipe_handle,
                ctypes.byref(overlapped))

            if success:
                return

            last_error = win32api.GetLastError()
            if last_error == ERROR_IO_PENDING:
                yield From(wait_for_event(overlapped.hEvent))

                # XXX: Call GetOverlappedResult.
                return  # Connection succeeded.

            else:
                raise Exception('connect failed with error code' + str(last_error))

    def read(self):
        """
        Read data from this pipe.
        """
        print('Pipe instance read #0')
        overlapped = OVERLAPPED()
        ev = _create_event(True)  # XXX: not sure about the default event value here.
        overlapped.hEvent = ev

        try:
            buff = ctypes.create_string_buffer(BUFSIZE + 1)
            c_read = DWORD()
            rc = DWORD()

            print('Pipe instance read #1', self)
            success = windll.kernel32.ReadFile( 
                self.pipe_handle,
                buff,
                DWORD(BUFSIZE),
                ctypes.byref(c_read),
                ctypes.byref(overlapped))

            print('Pipe instance read #2', success)
            if success:
                buff[c_read.value] = b'\0'
                raise Return(buff.value.decode('utf-8', 'ignore'))

            error_code = windll.kernel32.GetLastError()
            print('Pipe instance read #3', error_code)
            if error_code == ERROR_IO_PENDING:
                print('Pipe instance read #4')
                yield From(wait_for_event(ev))
                print('Pipe instance read #5')

                success = windll.kernel32.GetOverlappedResult(
                    self.pipe_handle,
                    ctypes.byref(overlapped),
                    ctypes.byref(c_read),
                    BOOL(False))

                print('Pipe instance read #6', success)
                if success:
                    buff[c_read.value] = b'\0'
                    raise Return(buff.value.decode('utf-8', 'ignore'))

                else:
                    error_code = windll.kernel32.GetLastError()
                    if error_code == ERROR_BROKEN_PIPE:
                        print('Overlapped Read failed, broken pipe.')
                        raise _BrokenPipeError
                    else:
                        raise Exception('reading overlapped IO failed.')

            elif error_code == ERROR_BROKEN_PIPE:
                print('Read failed, broken pipe.')
                raise _BrokenPipeError

        finally:
            # Release event.
            windll.kernel32.CloseHandle(overlapped.hEvent)

    def write(self, text):
        """
        Write data into the pipe.
        """
        overlapped = OVERLAPPED()
        overlapped.hEvent = _create_event()
        c_written = DWORD()

        try:
            data = text.encode('utf-8')

            success = windll.kernel32.WriteFile(
                self.pipe_handle,
                ctypes.create_string_buffer(data),
                len(data),
                ctypes.byref(c_written),
                ctypes.byref(overlapped))

            if success:
                return

            error_code = windll.kernel32.GetLastError()
            if error_code == ERROR_IO_PENDING:
                yield From(wait_for_event(overlapped.hEvent))

                success = windll.kernel32.GetOverlappedResult(
                    self.pipe_handle,
                    ctypes.byref(overlapped),
                    ctypes.byref(c_written),
                    BOOL(False))

                if not success:
                    error_code = windll.kernel32.GetLastError()
                    if error_code == ERROR_BROKEN_PIPE:
                        print('Overlapped Write failed, broken pipe.')
                        raise _BrokenPipeError
                    else:
                        raise 'Writing overlapped IO failed.'

            elif error_code == ERROR_BROKEN_PIPE:
                print('Write failed, broken pipe.')
                raise _BrokenPipeError

        finally:
            # Release event.
            windll.kernel32.CloseHandle(overlapped.hEvent)


class _BrokenPipeError(Exception):
    pass


def wait_for_event(event):
    """
    Wraps a win32 event into a `Future` and wait for it.
    """
    f = Future()
    def ready():
        get_event_loop().remove_win32_handle(event)
        f.set_result(None)
    get_event_loop().add_win32_handle(event, ready)
    return f


def _create_event(initial_state=True):
    """
    Create Win32 event.
    """
    event = windll.kernel32.CreateEventA(
        None,  # Default security attributes.
        BOOL(True),  # Manual reset event.
        BOOL(initial_state),  # Initial state = signaled.
        None  # Unnamed event object.
    )
    if not event:
        raise Exception('event creation failed.')

    return event


# TODO: delete event?
