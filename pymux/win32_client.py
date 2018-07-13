from ctypes import windll, byref, create_string_buffer
from ctypes.wintypes import DWORD, BOOL
from prompt_toolkit.eventloop import get_event_loop, ensure_future, From, Return, Future
from ptterm.backends.win32_pipes import OVERLAPPED
import ctypes

BUFSIZE = 4096

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 0x3

ERROR_IO_PENDING = 997
ERROR_BROKEN_PIPE = 109
ERROR_MORE_DATA = 234 
FILE_FLAG_OVERLAPPED = 0x40000000

PIPE_READMODE_MESSAGE = 0x2
FILE_WRITE_ATTRIBUTES = 0x100  # 256 
INVALID_HANDLE_VALUE = -1


def _create_event():
    """
    Create Win32 event.
    """
    event = windll.kernel32.CreateEventA(
        None,  # Default security attributes.
        BOOL(True),  # Manual reset event.
        BOOL(True),  # Initial state = signaled.
        None  # Unnamed event object.
    )
    if not event:
        raise Exception('event creation failed.')
    return event


class PipeClient(object):
    def __init__(self, pipe_name):
        self.pipe_handle = windll.kernel32.CreateFileW(
            pipe_name,
            DWORD(GENERIC_READ | GENERIC_WRITE | FILE_WRITE_ATTRIBUTES),
            DWORD(0),  # No sharing.
            None,  # Default security attributes.
            DWORD(OPEN_EXISTING),  # dwCreationDisposition.
            FILE_FLAG_OVERLAPPED,  # dwFlagsAndAttributes.
            None  # hTemplateFile,
        )
        if self.pipe_handle == INVALID_HANDLE_VALUE:
            raise Exception('Invalid handle. Connecting to pipe %r failed.' % pipe_name)

        dwMode = DWORD(PIPE_READMODE_MESSAGE)
        windll.kernel32.SetNamedPipeHandleState(
            self.pipe_handle,
            byref(dwMode),
            None,
            None)

    def write_message(self, text):
        """
        (coroutine)
        Write data into the pipe.
        """
        overlapped = OVERLAPPED()
        overlapped.hEvent = _create_event()
        c_written = DWORD()

        data = text.encode('utf-8')

        success = windll.kernel32.WriteFile(
            self.pipe_handle,
            create_string_buffer(data),
            len(data),
            byref(c_written),
            byref(overlapped))

        if success:
            return

        error_code = windll.kernel32.GetLastError()
        if error_code == ERROR_IO_PENDING:
            yield From(wait_for_event(overlapped.hEvent))

            success = windll.kernel32.GetOverlappedResult(
                self.pipe_handle,
                byref(overlapped),
                byref(c_written),
                BOOL(False))

            if not success:
                error_code = windll.kernel32.GetLastError()
                if error_code == ERROR_BROKEN_PIPE:
                    raise _BrokenPipeError
                else:
                    raise 'Writing overlapped IO failed.'

        elif error_code == ERROR_BROKEN_PIPE:
            raise _BrokenPipeError

    def read_message(self):
        """
        (coroutine)
        Read one single message from the pipe and return as text.
        """
        data = yield From(self._read_message_bytes())
        raise Return(data.decode('utf-8', 'ignore'))

    def _read_message_bytes(self):
        """
        (coroutine)
        Read message from this pipe. Return bytes.
        """
        overlapped = OVERLAPPED()
        overlapped.hEvent = _create_event()

        buff = create_string_buffer(BUFSIZE + 1)
        c_read = DWORD()
        rc = DWORD()

        success = windll.kernel32.ReadFile( 
            self.pipe_handle,
            buff,
            DWORD(BUFSIZE),
            byref(c_read),
            byref(overlapped))

        if success:
            buff[c_read.value] = b'\0'
            raise Return(buff.value)

        error_code = windll.kernel32.GetLastError()

        if error_code == ERROR_IO_PENDING:
            yield From(wait_for_event(overlapped.hEvent))

            success = windll.kernel32.GetOverlappedResult(
                self.pipe_handle,
                byref(overlapped),
                byref(c_read),
                BOOL(False))

            if success:
                buff[c_read.value] = b'\0'
                raise Return(buff.value)

            else:
                error_code = windll.kernel32.GetLastError()
                if error_code == ERROR_BROKEN_PIPE:
                    raise _BrokenPipeError
                elif error_code == ERROR_MORE_DATA:

                    more_data = yield From(self._read_message_bytes())
                    raise Return(buff.value + more_data)
                else:
                    raise Exception(
                        'reading overlapped IO failed. error_code=%r' % error_code)

        elif error_code == ERROR_BROKEN_PIPE:
            raise _BrokenPipeError

        elif error_code == ERROR_MORE_DATA:
            more_data = yield From(self._read_message_bytes())
            raise Return(buff.value + more_data)

        else:
            raise Exception('Reading pipe failed, error_code=%s' % error_code)

    def close():
        win32.CloseHandle(self.pipe_handle)


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


