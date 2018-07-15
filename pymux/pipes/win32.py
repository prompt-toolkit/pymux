"""
Common Win32 pipe operations.
"""
from __future__ import unicode_literals
from ctypes import windll, byref, create_string_buffer
from ctypes.wintypes import DWORD, BOOL
from prompt_toolkit.eventloop import get_event_loop, From, Return, Future
from ptterm.backends.win32_pipes import OVERLAPPED

__all__ = [
    'read_message_from_pipe',
    'read_message_bytes_from_pipe',
    'write_message_to_pipe',
    'write_message_bytes_to_pipe',
    'wait_for_event',
]

BUFSIZE = 4096

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 0x3

ERROR_BROKEN_PIPE = 109
ERROR_IO_PENDING = 997
ERROR_MORE_DATA = 234 
ERROR_NO_DATA = 232
FILE_FLAG_OVERLAPPED = 0x40000000

PIPE_READMODE_MESSAGE = 0x2
FILE_WRITE_ATTRIBUTES = 0x100  # 256 
INVALID_HANDLE_VALUE = -1


def connect_to_pipe(pipe_name):
    """
    Connect to a new pipe in message mode.
    """
    pipe_handle = windll.kernel32.CreateFileW(
        pipe_name,
        DWORD(GENERIC_READ | GENERIC_WRITE | FILE_WRITE_ATTRIBUTES),
        DWORD(0),  # No sharing.
        None,  # Default security attributes.
        DWORD(OPEN_EXISTING),  # dwCreationDisposition.
        FILE_FLAG_OVERLAPPED,  # dwFlagsAndAttributes.
        None  # hTemplateFile,
    )
    if pipe_handle == INVALID_HANDLE_VALUE:
        raise Exception('Invalid handle. Connecting to pipe %r failed.' % pipe_name)

    # Turn pipe into message mode.
    dwMode = DWORD(PIPE_READMODE_MESSAGE)
    windll.kernel32.SetNamedPipeHandleState(
        pipe_handle,
        byref(dwMode),
        None,
        None)

    return pipe_handle


def create_event():
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


def read_message_from_pipe(pipe_handle):
    """
    (coroutine)
    Read message from this pipe. Return text.
    """
    data = yield From(read_message_bytes_from_pipe(pipe_handle))
    assert isinstance(data, bytes)
    raise Return(data.decode('utf-8', 'ignore'))


def read_message_bytes_from_pipe(pipe_handle):
    """
    (coroutine)
    Read message from this pipe. Return bytes.
    """
    overlapped = OVERLAPPED()
    overlapped.hEvent = create_event()
    
    try:
        buff = create_string_buffer(BUFSIZE + 1)
        c_read = DWORD()

        success = windll.kernel32.ReadFile( 
            pipe_handle,
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
                pipe_handle,
                byref(overlapped),
                byref(c_read),
                BOOL(False))

            if success:
                buff[c_read.value] = b'\0'
                raise Return(buff.value)

            else:
                error_code = windll.kernel32.GetLastError()
                if error_code == ERROR_BROKEN_PIPE:
                    print('Broken pipe')
                    raise _BrokenPipeError

                elif error_code == ERROR_MORE_DATA:
                    more_data = yield From(read_message_bytes_from_pipe(pipe_handle))
                    raise Return(buff.value + more_data)
                else:
                    raise Exception(
                        'reading overlapped IO failed. error_code=%r' % error_code)

        elif error_code == ERROR_BROKEN_PIPE:
            print('Broken pipe')
            raise _BrokenPipeError

        elif error_code == ERROR_MORE_DATA:
            more_data = yield From(read_message_bytes_from_pipe(pipe_handle))
            raise Return(buff.value + more_data)

        else:
            raise Exception('Reading pipe failed, error_code=%s' % error_code)
    finally:
        windll.kernel32.CloseHandle(overlapped.hEvent)


def write_message_to_pipe(pipe_handle, text):
    data = text.encode('utf-8')
    yield From(write_message_bytes_to_pipe(pipe_handle, data))


def write_message_bytes_to_pipe(pipe_handle, data):
    overlapped = OVERLAPPED()
    overlapped.hEvent = create_event()
    
    try:
        c_written = DWORD()

        success = windll.kernel32.WriteFile(
            pipe_handle,
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
                pipe_handle,
                byref(overlapped),
                byref(c_written),
                BOOL(False))

            if not success:
                error_code = windll.kernel32.GetLastError()
                if error_code == ERROR_BROKEN_PIPE:
                    raise _BrokenPipeError
                else:
                    raise Exception('Writing overlapped IO failed. error_code=%r' % error_code)

        elif error_code == ERROR_BROKEN_PIPE:
            raise _BrokenPipeError
    finally:
        windll.kernel32.CloseHandle(overlapped.hEvent)


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
