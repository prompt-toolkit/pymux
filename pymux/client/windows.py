from __future__ import unicode_literals
from .base import Client
import win32file
import win32con
import win32security
import os
from ctypes import byref
from ctypes.wintypes import DWORD
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.win32 import Win32Output
from prompt_toolkit.eventloop import get_event_loop
from prompt_toolkit.eventloop import Future, ensure_future, From
from prompt_toolkit.input.win32 import Win32Input
from prompt_toolkit.win32_types import STD_OUTPUT_HANDLE
import json
import sys
from functools import partial
from ctypes import windll
from ..win32_client import PipeClient

__all__ = [
    'WindowsClient',
    'list_clients',
]

# See: https://msdn.microsoft.com/pl-pl/library/windows/desktop/ms686033(v=vs.85).aspx
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

class WindowsClient(Client):
    def __init__(self, pipe_name):
        self._input = Win32Input()
        self._hconsole = windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        self._data_buffer = b''

        self.pipe = PipeClient(pipe_name)

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

        f = ensure_future(self._start_reader())
        with self._input.attach(self._input_ready):
            get_event_loop().run_until_complete(f)  # Run forever.
        print('DONE' * 1000)

#        loop = get_event_loop()
#        loop.run_in_executor(self._start_reader_thread)
#        loop.add_win32_handle(self.pipe.handle, self._received)

#        with self._input.attach(self._input_ready):
#            get_event_loop().run_until_complete(future)

    def _start_reader(self):
        """
        Read from Win32 pipe.
        """
        while True:
            message = yield From(self.pipe.read_message())
#            print('Received from pipe: ', repr(message))
            self._process(message)

    def _process(self, data_buffer):
        """
        Handle incoming packet from server.
        """
        packet = json.loads(data_buffer)
#        print('Processing packet: ', repr(packet))

        if packet['cmd'] == 'out':
            # Call os.write manually. In Python2.6, sys.stdout.write doesn't use UTF-8.
            original_mode = DWORD(0)
            windll.kernel32.GetConsoleMode(self._hconsole, byref(original_mode))

            windll.kernel32.SetConsoleMode(self._hconsole, DWORD(
                ENABLE_PROCESSED_INPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING))

            try:
                os.write(sys.stdout.fileno(), packet['data'].encode('utf-8'))
            finally:
                windll.kernel32.SetConsoleMode(self._hconsole, original_mode)

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
        print('sending packet', repr(data))
        data = json.dumps(data)
        ensure_future(self.pipe.write_message(data))

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
