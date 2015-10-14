#!/usr/bin/env python
"""
"""
from __future__ import unicode_literals
from prompt_toolkit.application import Application
from prompt_toolkit.interface import CommandLineInterface
from prompt_toolkit.key_binding.manager import KeyBindingManager
from prompt_toolkit.layout.containers import VSplit, HSplit, Window
from prompt_toolkit.layout.controls import TokenListControl, FillControl, UIControl
from prompt_toolkit.layout.dimension import LayoutDimension as D
from prompt_toolkit.layout.screen import Char, Screen, Point
from prompt_toolkit.filters import Condition
from pygments.style import Style
from pygments.styles.default import DefaultStyle
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding.registry import Registry
from prompt_toolkit.eventloop.posix_utils import PosixStdinReader


from libpymux.screen import BetterScreen
from libpymux.pexpect_utils import pty_make_controlling_tty
from libpymux.utils import set_size
import pyte

from pygments.token import Token
from functools import partial

import os
import resource

def title_bar(cli):
    return [
        (Token.Title, ' pymux '),
    ]


class Pane(UIControl):
    def __init__(self, app):
        self.app = app

    def create_screen(self, cli, width, height):
        process = self.app.p
        process.set_size(width, height)

        s = Screen(initial_width=width)
        line_offset = process.screen.line_offset

        for y in range(0, process.screen.lines):
            if (y + line_offset) in process.screen.buffer:
                line = process.screen.buffer[y + line_offset]

                for x in range(0, process.screen.columns):
                    cell = line.get(x)
                    if cell:
                        if cell.bold:
                            token = Token.Bold
                        elif cell.underscore:
                            token = Token.Underline
                        else:
                            token = Token

                        token = getattr(token, 'C_%s' % cell.fg)
                        s._buffer[y][x] = Char(cell.data, token)

        s.cursor_position = Point(
             x=max(0, process.screen.cursor.x),
             y=max(0, process.screen.cursor.y))
        s.width = width
        s.height = height
        return s

    def has_focus(self, cli):
        return True


def create_layout(hackernews_app):
    return HSplit([
        Window(
            height=D.exact(1),
            content=TokenListControl(title_bar, default_char=Char(' ', Token.Title))
        ),
        VSplit([
            Window(
                Pane(hackernews_app),
            ),
            Window(width=D.exact(1),
                   content=FillControl('|', token=Token.Line)),
            Window(
                Pane(hackernews_app),
            ),
        ]),
        VSplit([
            Window(
                height=D.exact(1),
                content=TokenListControl(lambda cli:[], default_char=Char(' ', Token.Ruler)),
            ),
        ]),
    ])

def load_key_bindings(hackernews_app):
    manager = KeyBindingManager()  # Start with the `KeyBindingManager`.

    return manager


class PyMuxStyle(Style):
    styles = DefaultStyle.styles.copy()

    styles.update({
        # User input.
        Token.Entry.Author:     '#444444 underline',
        Token.Ruler:            '#ff6666 underline',
        Token.Title:            'bg:#666666 #000000',

        Token.Bold:             ' bold #ff4444',
        Token.Underline:        ' underline #44ff44',

        Token.C_black:   '#000000',
        Token.C_red:     '#aa0000',
        Token.C_green:   '#00aa00',
        Token.C_brown:   '#aaaa00',
        Token.C_blue:    '#0000aa',
        Token.C_magenta: '#aa00aa',
        Token.C_cyan:    '#00aaaa',
        Token.C_white:   '#ffffff',
        Token.C_default:  '',

        #Token.C30: '#000000',
        #Token.C31: '#ff0000',
        #Token.C32: '#00ff00',
        #Token.C33: '#ffff00',
        #Token.C34: '#0000ff',
        #Token.C35: '#ff00ff',
        #Token.C36: '#00ffff',
        #Token.C37: '#ffffff',
        #Token.C39: '',
    })


class Process(object):
    def __init__(self, cli, invalidate):
        self.cli = cli
        self.invalidate = invalidate

        # Create pseudo terminal for this pane.
        self.master, self.slave = os.openpty()

        # Create output stream and attach to screen
        self.sx = 120
        self.sy = 24

        self.screen = BetterScreen(self.sx, self.sy)
        self.stream = pyte.Stream()
        self.stream.attach(self.screen)

        self.set_size(self.sx, self.sy)
        self.start()

    def start(self):
        os.environ['TERM'] = 'screen'
        pid = os.fork()
        if pid == 0:
            self._in_child()
        elif pid > 0:
            self._in_parent(pid)
            os.close(self.slave)
            self.slave = None

    def set_size(self, width, height):
        set_size(self.master, height, width)
        self.screen.resize(lines=height, columns=width)

        self.screen.lines = height
        self.screen.columns = width

    def _in_child(self):
        os.close(self.master)

        pty_make_controlling_tty(self.slave)

        # In the fork, set the stdin/out/err to our slave pty.
        os.dup2(self.slave, 0)
        os.dup2(self.slave, 1)
        os.dup2(self.slave, 2)

        # Execute in child.
        try:
            self._exec()
        except Exception as e:
            os._exit(1)
        os._exit(0)

    def _exec(self):
        self._close_file_descriptors()
        os.execv('/bin/bash', ['bash'])

    def _close_file_descriptors(self):
        # Do not allow child to inherit open file descriptors from parent.
        # (In case that we keep running Python code. We shouldn't close them.
        # because the garbage collector is still active, and he will close them
        # eventually.)
        max_fd = resource.getrlimit(resource.RLIMIT_NOFILE)[-1]
        for i in range(3, max_fd):
            if i != self.slave:
                try:
                    os.close(i)
                except OSError:
                    pass

    def _in_parent(self, pid):
        pass

    def write_input(self, data):
        " Write user key strokes to the input. "
        with open('/tmp/log', 'a') as f:
            f.write('write input: %r\n' % data)

        os.write(self.master, data)

    def process_pty_output(self):
        # Master side -> attached to terminal emulator.
        reader = PosixStdinReader(self.master)
        def read():
            self.stream.feed(reader.read())
            self.invalidate()

        self.cli.eventloop.connect_read_pipe(self.master, read)
        # Connect read pipe to process



class PyMux(object):
    def __init__(self):
        registry = Registry()
        @registry.add_binding(Keys.Any)
        def _(event):
            self.p.write_input(event.data.encode('utf-8'))

        @registry.add_binding(Keys.ControlT)
        def _(event):
            self.cli.set_return_value(None)

        application = Application(
            layout=create_layout(self),
            #key_bindings_registry=load_key_bindings(self).registry,
            key_bindings_registry=registry,
            mouse_support=True,
            use_alternate_screen=True,
            style=PyMuxStyle)

        self.cli = CommandLineInterface(application=application)

        self.p = Process(self.cli, self.cli.request_redraw)

    def run(self):
        self.p.process_pty_output()
        self.cli.run()


if __name__ == '__main__':
    PyMux().run()
