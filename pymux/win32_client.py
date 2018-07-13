from ctypes.wintypes import DWORD, BOOL
import ctypes
#import win32
from ctypes import windll, byref
from ptterm.backends.win32_pipes import OVERLAPPED
from prompt_toolkit.eventloop import get_event_loop, ensure_future, From, Return, Future

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

        # TODO: handle errors.
#        print('pipe handle', self.pipe_handle)
        #if self.pipe_handle != INVALID_HANDLE_VALUE: ...             # TODO!!!

        dwMode = DWORD(PIPE_READMODE_MESSAGE)
        windll.kernel32.SetNamedPipeHandleState(
            self.pipe_handle,
            byref(dwMode),
            None,
            None)


#    def write_message(self, text):
#        # Send a message to the pipe server.
#        message = text.encode('utf-8')
#        rc = DWORD()
#
#        fSuccess = windll.kernel32.WriteFile(
#            self.pipe_handle,
#            ctypes.create_string_buffer(message),
#            len(message),
#            ctypes.byref(rc),
#            None)  # Not overlapped.
#
#        if not fSuccess:
#            print('WriteFile failed.', win32api.GetLastError())
#            return

    def write_message(self, text):
        """
        (coroutine)
        Write data into the pipe.
        """
#        print('PipeClient.write_message #0')
        overlapped = OVERLAPPED()
        overlapped.hEvent = _create_event()
        c_written = DWORD()

        data = text.encode('utf-8')
#        print('PipeClient.write_message #1')

        success = windll.kernel32.WriteFile(
            self.pipe_handle,
            ctypes.create_string_buffer(data),
            len(data),
            ctypes.byref(c_written),
            ctypes.byref(overlapped))

#        print('PipeClient.write_message #2', success)
        if success:
            return

        error_code = windll.kernel32.GetLastError()
#        print('PipeClient.write_message #3', error_code)
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
#                    print('Overlapped Write failed, broken pipe.')
                    raise _BrokenPipeError
                else:
                    raise 'Writing overlapped IO failed.'

        elif error_code == ERROR_BROKEN_PIPE:
#            print('Write failed, broken pipe.')
            raise _BrokenPipeError


#    def read_message(self):
#        # Get response.
#        buff = ctypes.create_string_buffer(BUFSIZE)
#        c_read = DWORD()
#
#        print('call readfile')
#        success = windll.kernel32.ReadFile( 
#            self.pipe_handle,
#            buff,
#            DWORD(BUFSIZE),
#            ctypes.byref(c_read),
#            None)  # Not overlapped.
#
#        if success:
#            buff[c_read.value] = b'\0'
#            return buff.value.decode('utf-8', 'ignore')
#        # TODO: handle ERROR_MORE_DATA

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
        Read data from this pipe.
        """
#        print('PipeClient.read_message')
        overlapped = OVERLAPPED()
        overlapped.hEvent = _create_event()

#        print('PipeClient.read_message #2')
        buff = ctypes.create_string_buffer(BUFSIZE + 1)
        c_read = DWORD()
        rc = DWORD()

#        print('PipeClient.read_message #3')
        success = windll.kernel32.ReadFile( 
            self.pipe_handle,
            buff,
            DWORD(BUFSIZE),
            ctypes.byref(c_read),
            ctypes.byref(overlapped))

#        print('reading', success)
        if success:
            buff[c_read.value] = b'\0'
            raise Return(buff.value)

        error_code = windll.kernel32.GetLastError()
#        print('err', error_code)
        if error_code == ERROR_IO_PENDING:
            yield From(wait_for_event(overlapped.hEvent))

            success = windll.kernel32.GetOverlappedResult(
                self.pipe_handle,
                ctypes.byref(overlapped),
                ctypes.byref(c_read),
                BOOL(False))

            if success:
                buff[c_read.value] = b'\0'
#                print('received', buff.value)
                raise Return(buff.value)

            else:
                error_code = windll.kernel32.GetLastError()
                if error_code == ERROR_BROKEN_PIPE:
#                    print('Overlapped Read failed, broken pipe.')
                    raise _BrokenPipeError
                elif error_code == ERROR_MORE_DATA:
#                    print('ERRRO_MORE_DATA')

                    more_data = yield From(self._read_message_bytes())
#                    if more_data is None:
#                        more_data = ''  # XXX: why does this happen????
                    raise Return(buff.value + more_data)
                    pass  # XXX
                # XXX: use utf8decoder...

                else:
                    raise Exception(
                        'reading overlapped IO failed. error_code=%r' % error_code)

        elif error_code == ERROR_BROKEN_PIPE:
#            print('Read failed, broken pipe.')
            raise _BrokenPipeError

        elif error_code == ERROR_MORE_DATA:
            more_data = yield From(self._read_message_bytes())
            raise Return(buff.value + more_data)

        else:
            raise Exception('Reading pipe failed, error_code=%s' % error_code)


    def close():
        win32.CloseHandle(self.pipe_handle)

#def main_coro():
#    pipe_name = r'\\.\pipe\pymux.sock.jonathan.9942'
#    pipe_client = PipeClient(pipe_name)
#    yield From(pipe_client.write_message('Hi there'))
#    result = yield From(pipe_client.read_message())
#    print('result', repr(result))


#get_event_loop().run_until_complete(ensure_future(main_coro()))


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


