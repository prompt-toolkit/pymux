from __future__ import unicode_literals
from .base import Client
import win32file
import win32con
import win32security
import os
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.win32 import Win32Output
from prompt_toolkit.eventloop import get_event_loop
from prompt_toolkit.eventloop import Future
from prompt_toolkit.input.win32 import Win32Input
from prompt_toolkit.win32_types import STD_OUTPUT_HANDLE
import json
import sys
from functools import partial
from ctypes import windll

__all__ = [
    'WindowsClient',
    'list_clients',
]

class WindowsClient(Client):
    def __init__(self, pipe_name):
        self._input = Win32Input()
        self._hconsole = windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        self._data_buffer = b''

        print('Pipe name: ', repr(pipe_name))
        try:
            import win32pipe
            #self.pipe = win32pipe.ConnectNamedPipe(pipe_name)
            self.pipe = win32file.CreateFile(
                pipe_name,  # Pipe name.
                win32con.GENERIC_READ | win32con.GENERIC_WRITE,  # Read and write access.
                1,  # 10 sharing.
                win32security.SECURITY_ATTRIBUTES(),  # Default security attributes.
                win32con.OPEN_EXISTING,  # Open existing pipe.
                0, # win32con.FILE_FLAG_OVERLAPPED,
                0)
        except win32file.error as e:
            print('Error:', e)
            raise


#        self._stdin_reader = 

    def attach(self, detach_other_clients=False, color_depth=ColorDepth.DEPTH_8_BIT):
        assert isinstance(detach_other_clients, bool)
        future = Future()

        self._send_size()
        self._send_packet({
            'cmd': 'start-gui',
            'detach-others': detach_other_clients,
            'color-depth': color_depth,
            'term': os.environ.get('TERM', ''),
            'data': ''
        })

        loop = get_event_loop()
        loop.run_in_executor(self._start_reader_thread)
#        loop.add_win32_handle(self.pipe.handle, self._received)

        with self._input.attach(self._input_ready):
            loop.run_until_complete(future)

    def _start_reader_thread(self):
        while True:
            print('Reading pipe')
#            num, data = win32file.ReadFile(self.pipe.handle, 2048)
            num, data = win32file.ReadFile(self.pipe, 2048)
            print('Received from pipe: ', repr(num), repr(data))

            get_event_loop().call_from_executor(
                partial(self._process_chunk, data))

#    def _received(self):
#        print('received something')
#        num, data = win32file.ReadFile(self.pipe.handle, 1)
#        print('Received', repr(num), repr(data))

    def _process_chunk(self, data):
        print('_process_chunk', repr(data))
        data_buffer = self._data_buffer + data

        while b'\0' in data_buffer:
            pos = data_buffer.index(b'\0')
            self._process(data_buffer[:pos])
            data_buffer = data_buffer[pos + 1:]

        self._data_buffer = data_buffer

    def _process(self, data_buffer):
        """
        Handle incoming packet from server.
        """
        packet = json.loads(data_buffer.decode('utf-8'))
        print('Processing packet: ', repr(packet))

        if packet['cmd'] == 'out':
            # Call os.write manually. In Python2.6, sys.stdout.write doesn't use UTF-8.
            original_mode = DWORD(0)
#            windll.kernel32.GetConsoleMode(self._hconsole, byref(original_mode))
#
#            windll.kernel32.SetConsoleMode(self._hconsole, DWORD(
#                ENABLE_PROCESSED_INPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING))

            try:
                os.write(sys.stdout.fileno(), packet['data'].encode('utf-8'))
            finally:
                pass #windll.kernel32.SetConsoleMode(self._hconsole, original_mode)

        elif packet['cmd'] == 'suspend':
            # Suspend client process to background.
            pass

        elif packet['cmd'] == 'mode':
            pass

            # # Set terminal to raw/cooked.
            # action = packet['data']

            # if action == 'raw':
            #     cm = raw_mode(sys.stdin.fileno())
            #     cm.__enter__()
            #     self._mode_context_managers.append(cm)

            # elif action == 'cooked':
            #     cm = cooked_mode(sys.stdin.fileno())
            #     cm.__enter__()
            #     self._mode_context_managers.append(cm)

            # elif action == 'restore' and self._mode_context_managers:
            #     cm = self._mode_context_managers.pop()
            #     cm.__exit__()



    def _input_ready(self):
        print('Input ready')
        keys = self._input.read_keys()
        print('Received input', repr(keys))
        if keys:
            self._send_packet({
                'cmd': 'in',
                'data': ''.join(key_press.data for key_press in keys),
            })
        else:
            print('sending nothing, no keys received')

    def _send_packet(self, data):
        " Send to server. "
        data = json.dumps(data).encode('utf-8')

        def in_thread():
            print('Send packet: ', repr(data))
            win32file.WriteFile(self.pipe, data + b'\0')
            print('Send packet done')
        get_event_loop().run_in_executor(in_thread)

    def _send_size(self):
        " Report terminal size to server. "
        output = Win32Output(sys.stdout)
        rows, cols = output.get_size()

        self._send_packet({
            'cmd': 'size',
            'data': [rows, cols]
        })


def list_clients():
    return []
