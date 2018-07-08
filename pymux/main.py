from __future__ import unicode_literals

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app, set_app
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.eventloop import Future
from prompt_toolkit.eventloop import get_event_loop
from prompt_toolkit.eventloop.context import context
from prompt_toolkit.filters import Condition
from prompt_toolkit.input.defaults import create_input
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.screen import Size
from prompt_toolkit.output.defaults import create_output

from .style import ui_style
from .arrangement import Arrangement, Pane, Window
from .commands.commands import handle_command, call_command_handler
from .commands.completer import create_command_completer
from .enums import COMMAND, PROMPT
from .key_bindings import PymuxKeyBindings
from .layout import LayoutManager, Justify
from .log import logger
from .options import ALL_OPTIONS, ALL_WINDOW_OPTIONS
from .rc import STARTUP_COMMANDS
from .utils import get_default_shell
from ptterm import Terminal

import os
import signal
import six
import sys
import tempfile
import threading
import time
import traceback
import weakref

__all__ = [
    'Pymux',
]


class ClientState(object):
    """
    State information that is independent for each client.
    """
    def __init__(self, pymux, input, output, color_depth, connection):
        self.pymux = pymux
        self.input = input
        self.output = output
        self.color_depth = color_depth
        self.connection = connection

        #: True when the prefix key (Ctrl-B) has been pressed.
        self.has_prefix = False

        #: Error/info message.
        self.message = None

        # When a "confirm-before" command is running,
        # Show this text in the command bar. When confirmed, execute
        # confirm_command.
        self.confirm_text = None
        self.confirm_command = None

        # When a "command-prompt" command is running.
        self.prompt_text = None
        self.prompt_command = None

        # Popup.
        self.display_popup = False

        # Input buffers.
        self.command_buffer = Buffer(
            name=COMMAND,
            accept_handler=self._handle_command,
            auto_suggest=AutoSuggestFromHistory(),
            multiline=False,
            complete_while_typing=False,
            completer=create_command_completer(pymux))

        self.prompt_buffer = Buffer(
            name=PROMPT,
            accept_handler=self._handle_prompt_command,
            multiline=False,
            auto_suggest=AutoSuggestFromHistory())

        # Layout.
        self.layout_manager = LayoutManager(self.pymux, self)

        self.app = self._create_app()

        # Clear write positions right before rendering. (They are populated
        # during rendering).
        def before_render(_):
            self.layout_manager.reset_write_positions()
        self.app.before_render += before_render

    @property
    def command_mode(self):
        return get_app().layout.has_focus(COMMAND)

    def _handle_command(self, buffer):
        " When text is accepted in the command line. "
        text = buffer.text

        # First leave command mode. We want to make sure that the working
        # pane is focused again before executing the command handers.
        self.pymux.leave_command_mode(append_to_history=True)

        # Execute command.
        self.pymux.handle_command(text)

    def _handle_prompt_command(self, buffer):
        " When a command-prompt command is accepted. "
        text = buffer.text
        prompt_command = self.prompt_command

        # Leave command mode and handle command.
        self.pymux.leave_command_mode(append_to_history=True)
        self.pymux.handle_command(prompt_command.replace('%%', text))

    def _create_app(self):
        """
        Create `Application` instance for this .
        """
        pymux = self.pymux

        def on_focus_changed():
            """ When the focus changes to a read/write buffer, make sure to go
            to insert mode. This happens when the ViState was set to NAVIGATION
            in the copy buffer. """
            vi_state = app.vi_state

            if app.current_buffer.read_only():
                vi_state.input_mode = InputMode.NAVIGATION
            else:
                vi_state.input_mode = InputMode.INSERT

        app = Application(
            output=self.output,
            input=self.input,
            color_depth=self.color_depth,

            layout=Layout(container=self.layout_manager.layout),
            key_bindings=pymux.key_bindings_manager.key_bindings,
            mouse_support=Condition(lambda: pymux.enable_mouse_support),
            full_screen=True,
            style=self.pymux.style,
            on_invalidate=(lambda _: pymux.invalidate()))

        # Synchronize the Vi state with the CLI object.
        # (This is stored in the current class, but expected to be in the
        # CommandLineInterface.)
        def sync_vi_state(_):
            VI = EditingMode.VI
            EMACS = EditingMode.EMACS

            if self.confirm_text or self.prompt_command or self.command_mode:
                app.editing_mode = VI if pymux.status_keys_vi_mode else EMACS
            else:
                app.editing_mode = VI if pymux.mode_keys_vi_mode else EMACS

        app.key_processor.before_key_press += sync_vi_state
        app.key_processor.after_key_press += sync_vi_state
        app.key_processor.after_key_press += self.sync_focus

        # Set render postpone time. (.1 instead of 0).
        # This small change ensures that if for a split second a process
        # outputs a lot of information, we don't give the highest priority to
        # rendering output. (Nobody reads that fast in real-time.)
        app.max_render_postpone_time = .1  # Second.

        # Hide message when a key has been pressed.
        def key_pressed(_):
            self.message = None
        app.key_processor.before_key_press += key_pressed

        # The following code needs to run with the application active.
        # Especially, `create_window` needs to know what the current
        # application is, in order to focus the new pane.
        with set_app(app):
            # Redraw all CLIs. (Adding a new client could mean that the others
            # change size, so everything has to be redrawn.)
            pymux.invalidate()

            pymux.startup()

        return app

    def sync_focus(self, *_):
        """
        Focus the focused window from the pymux arrangement.
        """
        # Pop-up displayed?
        if self.display_popup:
            self.app.layout.focus(self.layout_manager.popup_dialog)
            return

        # Confirm.
        if self.confirm_text:
            return

        # Custom prompt.
        if self.prompt_command:
            return # Focus prompt

        # Command mode.
        if self.command_mode:
            return # Focus command

        # No windows left, return. We will quit soon.
        if not self.pymux.arrangement.windows:
            return

        pane = self.pymux.arrangement.get_active_pane()
        self.app.layout.focus(pane.terminal)


class Pymux(object):
    """
    The main Pymux application class.

    Usage:

        p = Pymux()
        p.listen_on_socket()
        p.run_server()

    Or:

        p = Pymux()
        p.run_standalone()
    """
    def __init__(self, source_file=None, startup_command=None):
        self._client_states = {}  # connection -> client_state

        # Options
        self.enable_mouse_support = True
        self.enable_status = True
        self.enable_pane_status = True#False
        self.enable_bell = True
        self.remain_on_exit = False
        self.status_keys_vi_mode = False
        self.mode_keys_vi_mode = False
        self.history_limit = 2000
        self.status_interval = 4
        self.default_terminal = 'xterm-256color'
        self.status_left = '[#S] '
        self.status_left_length = 20
        self.status_right = ' %H:%M %d-%b-%y '
        self.status_right_length = 20
        self.window_status_current_format = '#I:#W#F'
        self.window_status_format = '#I:#W#F'
        self.session_name = '0'
        self.status_justify = Justify.LEFT
        self.default_shell = get_default_shell()

        self.options = ALL_OPTIONS
        self.window_options = ALL_WINDOW_OPTIONS

        # When no panes are available.
        self.original_cwd = os.getcwd()

        self.display_pane_numbers = False

        #: List of clients.
        self._runs_standalone = False
        self.connections = []
        self.done_f = Future()

        self._startup_done = False
        self.source_file = source_file
        self.startup_command = startup_command

        # Keep track of all the panes, by ID. (For quick lookup.)
        self.panes_by_id = weakref.WeakValueDictionary()

        # Socket information.
        self.socket = None
        self.socket_name = None

        # Key bindings manager.
        self.key_bindings_manager = PymuxKeyBindings(self)

        self.arrangement = Arrangement()

        self.style = ui_style

    def _start_auto_refresh_thread(self):
        """
        Start the background thread that auto refreshes all clients according to
        `self.status_interval`.
        """
        def run():
            while True:
                time.sleep(self.status_interval)
                self.invalidate()

        t = threading.Thread(target=run)
        t.daemon = True
        t.start()

    @property
    def apps(self):
        return [c.app for c in self._client_states.values()]

    def get_client_state(self):
        " Return the active ClientState instance. "
        app = get_app()
        for client_state in self._client_states.values():
            if client_state.app == app:
                return client_state

        raise ValueError

    def get_connection(self):
        " Return the active Connection instance. "
        app = get_app()
        for connection, client_state in self._client_states.items():
            if client_state.app == app:
                return connection

        raise ValueError

    def startup(self):
        # Handle start-up comands.
        # (Does initial key bindings.)
        if not self._startup_done:
            self._startup_done = True

            # Execute default config.
            for cmd in STARTUP_COMMANDS.splitlines():
                self.handle_command(cmd)

            # Source the given file.
            if self.source_file:
                call_command_handler('source-file', self, [self.source_file])

            # Make sure that there is one window created.
            self.create_window(command=self.startup_command)

    def get_title(self):
        """
        The title to be displayed in the titlebar of the terminal.
        """
        w = self.arrangement.get_active_window()

        if w and w.active_process:
            title = w.active_process.screen.title
        else:
            title = ''

        if title:
            return '%s - Pymux' % (title, )
        else:
            return 'Pymux'

    def get_window_size(self):
        """
        Get the size to be used for the DynamicBody.
        This will be the smallest size of all clients.
        """
        def active_window_for_app(app):
            with set_app(app):
                return self.arrangement.get_active_window()

        active_window = self.arrangement.get_active_window()

        # Get sizes for connections watching the same window.
        apps = [client_state.app for client_state in self._client_states.values()
                if active_window_for_app(client_state.app) == active_window]
        sizes = [app.output.get_size() for app in apps]

        rows = [s.rows for s in sizes]
        columns = [s.columns for s in sizes]

        if rows and columns:
            return Size(rows=min(rows) - (1 if self.enable_status else 0),
                        columns=min(columns))
        else:
            return Size(rows=20, columns=80)

    def _create_pane(self, window=None, command=None, start_directory=None):
        """
        Create a new :class:`pymux.arrangement.Pane` instance. (Don't put it in
        a window yet.)

        :param window: If a window is given, take the CWD of the current
            process of that window as the start path for this pane.
        :param command: If given, run this command instead of `self.default_shell`.
        :param start_directory: If given, use this as the CWD.
        """
        assert window is None or isinstance(window, Window)
        assert command is None or isinstance(command, six.text_type)
        assert start_directory is None or isinstance(start_directory, six.text_type)

        def done_callback():
            " When the process finishes. "
            if not self.remain_on_exit:
                # Remove pane from layout.
                self.arrangement.remove_pane(pane)

                # No panes left? -> Quit.
                if not self.arrangement.has_panes:
                    self.stop()

                # Make sure the right pane is focused for each client.
                for client_state in self._client_states.values():
                    client_state.sync_focus()

            self.invalidate()

        def bell():
            " Sound bell on all clients. "
            if self.enable_bell:
                for c in self.apps:
                    c.output.bell()

        # Start directory.
        if start_directory:
            path = start_directory
        elif window and window.active_process:
            # When the path of the active process is known,
            # start the new process at the same location.
            path = window.active_process.get_cwd()
        else:
            path = None

        def before_exec():
            " Called in the process fork (in the child process). "
            # Go to this directory.
            try:
                os.chdir(path or self.original_cwd)
            except OSError:
                pass  # No such file or directory.

            # Set terminal variable. (We emulate xterm.)
            os.environ['TERM'] = self.default_terminal

            # Make sure to set the PYMUX environment variable.
            if self.socket_name:
                os.environ['PYMUX'] = '%s,%i' % (
                    self.socket_name, pane.pane_id)

        if command:
            command = command.split()
        else:
            command = [self.default_shell]

        # Create new pane and terminal.
        terminal = Terminal(done_callback=done_callback, bell_func=bell,
                            before_exec_func=before_exec)
        pane = Pane(terminal)

        # Keep track of panes. This is a WeakKeyDictionary, we only add, but
        # don't remove.
        self.panes_by_id[pane.pane_id] = pane

        logger.info('Created process %r.', command)

        return pane

    def invalidate(self):
        " Invalidate the UI for all clients. "
        for app in self.apps:
            app.invalidate()

    def stop(self):
        for app in self.apps:
            app.exit()
        self.done_f.set_result(None)

    def create_window(self, command=None, start_directory=None, name=None):
        """
        Create a new :class:`pymux.arrangement.Window` in the arrangement.
        """
        assert command is None or isinstance(command, six.text_type)
        assert start_directory is None or isinstance(start_directory, six.text_type)

        pane = self._create_pane(None, command, start_directory=start_directory)

        self.arrangement.create_window(pane, name=name)
        pane.focus()
        self.invalidate()

    def add_process(self, command=None, vsplit=False, start_directory=None):
        """
        Add a new process to the current window. (vsplit/hsplit).
        """
        assert command is None or isinstance(command, six.text_type)
        assert start_directory is None or isinstance(start_directory, six.text_type)

        window = self.arrangement.get_active_window()

        pane = self._create_pane(window, command, start_directory=start_directory)
        window.add_pane(pane, vsplit=vsplit)
        pane.focus()
        self.invalidate()

    def kill_pane(self, pane):
        """
        Kill the given pane, and remove it from the arrangement.
        """
        assert isinstance(pane, Pane)

        # Send kill signal.
        if not pane.process.is_terminated:
            pane.process.kill()

        # Remove from layout.
        self.arrangement.remove_pane(pane)

    def leave_command_mode(self, append_to_history=False):
        """
        Leave the command/prompt mode.
        """
        client_state = self.get_client_state()

        client_state.command_buffer.reset(append_to_history=append_to_history)
        client_state.prompt_buffer.reset(append_to_history=True)

        client_state.prompt_command = ''
        client_state.confirm_command = ''

        client_state.app.layout.focus_previous()

    def handle_command(self, command):
        """
        Handle command from the command line.
        """
        handle_command(self, command)

    def show_message(self, message):
        """
        Set a warning message. This will be shown at the bottom until a key has
        been pressed.

        :param message: String.
        """
        self.get_client_state().message = message

    def detach_client(self, app):
        """
        Detach the client that belongs to this CLI.
        """
        connection = self.get_connection()
        if connection:
            connection.detach_and_close()

        # Redraw all clients -> Maybe their size has to change.
        self.invalidate()

    def listen_on_socket(self, socket_name=None):
        """
        Listen for clients on a Unix socket.
        Returns the socket name.
        """
        from .server import bind_socket
        if self.socket is None:
            # Py2 uses 0027 and Py3 uses 0o027, but both know
            # how to create the right value from the string '0027'.
            old_umask = os.umask(int('0027', 8))
            self.socket_name, self.socket = bind_socket(socket_name)
            _ = os.umask(old_umask)
            self.socket.listen(0)
            get_event_loop().add_reader(self.socket.fileno(), self._socket_accept)

        # Set session_name according to socket name.
        if '.' in self.socket_name:
            self.session_name = self.socket_name.rpartition('.')[-1]

        logger.info('Listening on %r.' % self.socket_name)
        return self.socket_name

    def _socket_accept(self):
        """
        Accept connection from client.
        """
        logger.info('Client attached.')
        from .server import ServerConnection

        connection, client_address = self.socket.accept()
        # Note: We don't have to put this socket in non blocking mode.
        #       This can cause crashes when sending big packets on OS X.

        # We have to create a new `context`, because this will be the scope for
        # a new prompt_toolkit.Application to become active.
        with context():
            connection = ServerConnection(self, connection, client_address)
            self.connections.append(connection)

    def run_server(self):
        # Ignore keyboard. (When people run "pymux server" and press Ctrl-C.)
        # Pymux has to be terminated by termining all the processes running in
        # its panes.
        def handle_sigint(*a):
            print('Ignoring keyboard interrupt.')

        signal.signal(signal.SIGINT, handle_sigint)

        # Start background threads.
        self._start_auto_refresh_thread()

        # Run eventloop.
        try:
            get_event_loop().run_until_complete(self.done_f)
        except:
            # When something bad happens, always dump the traceback.
            # (Otherwise, when running as a daemon, and stdout/stderr are not
            # available, it's hard to see what went wrong.)
            fd, path = tempfile.mkstemp(prefix='pymux.crash-')
            logger.fatal(
                'Pymux has crashed, dumping traceback to {0}'.format(path))
            os.write(fd, traceback.format_exc().encode('utf-8'))
            os.close(fd)
            raise

        finally:
            # Clean up socket.
            os.remove(self.socket_name)

    def run_standalone(self, color_depth):
        """
        Run pymux standalone, rather than using a client/server architecture.
        This is mainly useful for debugging.
        """
        self._runs_standalone = True
        self._start_auto_refresh_thread()

        client_state = self.add_client(
            input=create_input(),
            output=create_output(stdout=sys.stdout),
            color_depth=color_depth,
            connection=None)

        client_state.app.run()

    def add_client(self, output, input, color_depth, connection):
        client_state = ClientState(self,
            connection=None,
            input=input,
            output=output,
            color_depth=color_depth)

        self._client_states[connection] = client_state

        return client_state

    def remove_client(self, connection):
        if connection in self._client_states:
            del self._client_states[connection]
