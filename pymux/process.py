"""
The child process.
"""
from __future__ import unicode_literals

from prompt_toolkit.document import Document
from prompt_toolkit.eventloop.base import EventLoop
from prompt_toolkit.eventloop.posix_utils import PosixStdinReader
from six.moves import range

from .key_mappings import prompt_toolkit_key_to_vt100_key
from .screen import BetterScreen
from .stream import BetterStream
from .utils import set_terminal_size, pty_make_controlling_tty

import os
import resource
import signal
import sys
import time
import traceback

__all__ = (
    'Process',
)


class Process(object):
    """
    Child process.
    Functionality for parsing the vt100 output (the Pyte screen and stream), as
    well as sending input to the process.

    Usage:

        p = Process(eventloop, ...):
        p.start()

    :param eventloop: Prompt_toolkit eventloop. Used for executing blocking
        stuff in an executor, as well as adding additional readers to the
        eventloop.
    :param invalidate: When the screen content changes, and the renderer needs
        to redraw the output, this callback is called.
    :param exec_func: Callable that is called in the child process. (Usualy,
        this calls execv.)
    :param bell_func: Called when the process does a `bell`.
    :param done_callback: Called when the process terminates.
    :param has_priority: Callable that returns True when this Process should
        get priority in the event loop. (When this pane has the focus.)
        Otherwise output can be delayed.
    """
    def __init__(self, eventloop, invalidate, exec_func, bell_func=None,
                 done_callback=None, has_priority=None):
        assert isinstance(eventloop, EventLoop)
        assert callable(invalidate)
        assert callable(exec_func)
        assert bell_func is None or callable(bell_func)
        assert done_callback is None or callable(done_callback)
        assert has_priority is None or callable(has_priority)

        self.eventloop = eventloop
        self.invalidate = invalidate
        self.exec_func = exec_func
        self.done_callback = done_callback
        self.has_priority = has_priority or (lambda: True)

        self.pid = None
        self.is_terminated = False
        self.suspended = False

        # Create pseudo terminal for this pane.
        self.master, self.slave = os.openpty()

        # Master side -> attached to terminal emulator.
        self._reader = PosixStdinReader(self.master, errors='replace')

        # Create output stream and attach to screen
        self.sx = 0
        self.sy = 0

        self.screen = BetterScreen(self.sx, self.sy,
                                   write_process_input=self.write_input,
                                   bell_func=bell_func)

        self.stream = BetterStream(self.screen)
        self.stream.attach(self.screen)

    def start(self):
        """
        Start the process: fork child.
        """
        self.set_size(120, 24)
        self._start()
        self._connect_reader()
        self._waitpid()

    @classmethod
    def from_command(cls, eventloop, invalidate, command, done_callback,
                     bell_func=None, before_exec_func=None, has_priority=None):
        """
        Create Process from command,
        e.g. command=['python', '-c', 'print("test")']

        :param before_exec_func: Function that is called before `exec` in the process fork.
        """
        assert isinstance(command, list)

        def execv():
            if before_exec_func:
                before_exec_func()

            for p in os.environ['PATH'].split(':'):
                path = os.path.join(p, command[0])
                if os.path.exists(path) and os.access(path, os.X_OK):
                    os.execv(path, command)

        return cls(eventloop, invalidate, execv,
                   bell_func=bell_func, done_callback=done_callback,
                   has_priority=has_priority)

    def _start(self):
        """
        Create fork and start the child process.
        """
        pid = os.fork()

        if pid == 0:
            self._in_child()
        elif pid > 0:
            # In parent.
            os.close(self.slave)
            self.slave = None

            # We wait a very short while, to be sure the child had the time to
            # call _exec. (Otherwise, we are still sharing signal handlers and
            # FDs.) Resizing the pty, when the child is still in our Python
            # code and has the signal handler from prompt_toolkit, but closed
            # the 'fd' for 'call_from_executor', will cause OSError.
            time.sleep(0.1)

            self.pid = pid

    def _waitpid(self):
        """
        Create an executor that waits and handles process termination.
        """
        def wait_for_finished():
            " Wait for PID in executor. "
            os.waitpid(self.pid, 0)
            self.eventloop.call_from_executor(done)

        def done():
            " PID received. Back in the main thread. "
            # Close pty and remove reader.
            os.close(self.master)
            self.eventloop.remove_reader(self.master)
            self.master = None

            # Callback.
            self.is_terminated = True
            self.done_callback()

        self.eventloop.run_in_executor(wait_for_finished)

    def set_size(self, width, height):
        """
        Set terminal size.
        """
        assert isinstance(width, int)
        assert isinstance(height, int)

        if self.master is not None:
            if (self.sx, self.sy) != (width, height):
                set_terminal_size(self.master, height, width)
        self.screen.resize(lines=height, columns=width)

        self.screen.lines = height
        self.screen.columns = width

        self.sx = width
        self.sy = height

    def _in_child(self):
        " Will be executed in the forked child. "
        os.close(self.master)

        # Remove signal handler for SIGWINCH as early as possible.
        # (We don't want this to be triggered when execv has not been called
        # yet.)
        signal.signal(signal.SIGWINCH, 0)

        pty_make_controlling_tty(self.slave)

        # In the fork, set the stdin/out/err to our slave pty.
        os.dup2(self.slave, 0)
        os.dup2(self.slave, 1)
        os.dup2(self.slave, 2)

        # Execute in child.
        try:
            self._close_file_descriptors()
            self.exec_func()
        except Exception:
            traceback.print_exc()
            time.sleep(5)

            os._exit(1)
        os._exit(0)

    def _close_file_descriptors(self):
        # Do not allow child to inherit open file descriptors from parent.
        # (In case that we keep running Python code. We shouldn't close them.
        # because the garbage collector is still active, and he will close them
        # eventually.)
        max_fd = resource.getrlimit(resource.RLIMIT_NOFILE)[-1]

        try:
            os.closerange(3, max_fd)
        except OverflowError:
            # On OS X, max_fd can return very big values, than closerange
            # doesn't understand, e.g. 9223372036854775807. In this case, just
            # use 4096. This is what Linux systems report, and should be
            # sufficient. (I hope...)
            os.closerange(3, 4096)

    def write_input(self, data, paste=False):
        """
        Write user key strokes to the input.

        :param data: (text, not bytes.) The input.
        :param paste: When True, and the process running here understands
            bracketed paste. Send as pasted text.
        """
        # send as bracketed paste?
        if paste and self.screen.bracketed_paste_enabled:
            data = '\x1b[200~' + data + '\x1b[201~'

        self.write_bytes(data.encode('utf-8'))

    def write_bytes(self, data):
        while self.master is not None:
            try:
                os.write(self.master, data)
            except OSError as e:
                # This happens when the window resizes and a SIGWINCH was received.
                # We get 'Error: [Errno 4] Interrupted system call'
                if e.errno == 4:
                    continue
            return

    def write_key(self, key):
        """
        Write prompt_toolkit Key.
        """
        data = prompt_toolkit_key_to_vt100_key(
            key, application_mode=self.screen.in_application_mode)
        self.write_input(data)

    def _connect_reader(self):
        """
        Process stdout output from the process.
        """
        if self.master is not None:
            self.eventloop.add_reader(self.master, self._read)

    def _read(self):
        """
        Read callback, called by the eventloop.
        """
        d = self._reader.read(4096)  # Make sure not to read too much at once. (Otherwise,
                                     # this could block the event loop.)

        if not self._reader.closed:
            def process():
                self.stream.feed(d)
                self.invalidate()

            # Feed directly, if this process has priority. (That is when this
            # pane has the focus in any of the clients.)
            if self.has_priority():
                process()

            # Otherwise, postpone processing until we have CPU time available.
            else:
                if self.master is not None:
                    self.eventloop.remove_reader(self.master)

                def do_asap():
                    " Process output and reconnect to event loop. "
                    process()
                    self._connect_reader()

                # When the event loop is saturated because of CPU, we will
                # postpone this processing max 'x' seconds.

                # '1' seems like a reasonable value, because that way we say
                # that we will process max 1k/1s in case of saturation.
                # That should be enough to prevent the UI from feeling
                # unresponsive.
                timestamp = time.time() + 1

                self.eventloop.call_from_executor(
                    do_asap, _max_postpone_until=timestamp)
        else:
            # End of stream. Remove child.
            self.eventloop.remove_reader(self.master)

    def suspend(self):
        """
        Suspend process. Stop reading stdout. (Called when going into copy mode.)
        """
        self.suspended = True
        self.eventloop.remove_reader(self.master)

    def resume(self):
        """
        Resume from 'suspend'.
        """
        if self.suspended and self.master is not None:
            self._connect_reader()
            self.suspended = False

    def get_cwd(self):
        """
        The current working directory for this process. (Or `None` when
        unknown.)
        """
        return get_cwd_for_pid(self.pid)

    def get_name(self):
        """
        The name for this process. (Or `None` when unknown.)
        """
        # TODO: Maybe cache for short time.
        if self.master is not None:
            return get_name_for_fd(self.master)

    def send_signal(self, signal):
        " Send signal to running process. "
        assert isinstance(signal, int), type(signal)

        if self.pid and not self.is_terminated:
            try:
                os.kill(self.pid, signal)
            except OSError:
                pass  # [Errno 3] No such process.

    def create_copy_document(self):
        """
        Create a Document instance and token list that can be used in copy
        mode.
        """
        data_buffer = self.screen.data_buffer
        text = []
        token_lists = []

        first_row = min(data_buffer.keys())
        last_row = max(data_buffer.keys())

        def token_has_no_background(token):
            try:
                # Token looks like ('C', color, bgcolor, bold, underline, ...)
                return token[2] is None
            except IndexError:
                return True

        for lineno in range(first_row, last_row + 1):
            token_list = []

            row = data_buffer[lineno]
            max_column = max(row.keys()) if row else 0

            # Remove trailing whitespace. (If the background is transparent.)
            row_data = [row[x] for x in range(0, max_column + 1)]

            while (row_data and row_data[-1].char.isspace() and
                   token_has_no_background(row_data[-1].token)):
                row_data.pop()

            # Walk through row.
            char_iter = iter(range(len(row_data)))

            for x in char_iter:
                c = row[x]
                text.append(c.char)
                token_list.append((c.token, c.char))

                # Skip next cell when this is a double width character.
                if c.width == 2:
                    try:
                        next(char_iter)
                    except StopIteration:
                        pass

            token_lists.append(token_list)
            text.append('\n')

        def get_tokens_for_line(lineno):
            try:
                return token_lists[lineno]
            except IndexError:
                return []

        # Calculate cursor position.
        d = Document(text=''.join(text))

        return Document(text=d.text,
                        cursor_position=d.translate_row_col_to_index(
                            row=self.screen.pt_screen.cursor_position.y,
                            col=self.screen.pt_screen.cursor_position.x)), get_tokens_for_line


def get_cwd_for_pid(pid):
    """
    Return the current working directory for a given process ID.
    """
    if sys.platform in ('linux', 'linux2', 'cygwin'):
        try:
            return os.readlink('/proc/%s/cwd' % pid)
        except OSError:
            pass


if sys.platform in ('linux', 'linux2', 'cygwin'):
    def get_name_for_fd(fd):
        """
        Return the process name for a given process ID.
        """
        try:
            pgrp = os.tcgetpgrp(fd)
        except OSError:
            # See: https://github.com/jonathanslenders/pymux/issues/46
            return

        try:
            with open('/proc/%s/cmdline' % pgrp, 'rb') as f:
                return f.read().decode('utf-8', 'ignore').partition('\0')[0]
        except IOError:
            pass
elif sys.platform == 'darwin':
    from .darwin import get_proc_name

    def get_name_for_fd(fd):
        """
        Return the process name for a given process ID.
        """
        try:
            pgrp = os.tcgetpgrp(fd)
        except OSError:
            return

        try:
            return get_proc_name(pgrp)
        except IOError:
            pass
else:
    def get_name_for_fd(fd):
        """
        Return the process name for a given process ID.
        """
        return
