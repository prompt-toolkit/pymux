"""
Key bindings.
"""
from __future__ import unicode_literals
from prompt_toolkit.enums import IncrementalSearchDirection
from prompt_toolkit.filters import HasFocus, Condition, HasSelection
from prompt_toolkit.key_binding.manager import KeyBindingManager as pt_KeyBindingManager
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.keys import Keys
from prompt_toolkit.selection import SelectionType

from .enums import COMMAND, PROMPT
from .filters import WaitsForConfirmation, HasPrefix, InScrollBuffer, InScrollBufferNotSearching, InScrollBufferSearching
from .key_mappings import pymux_key_to_prompt_toolkit_key_sequence
from .commands.commands import call_command_handler

import six

__all__ = (
    'KeyBindingsManager',
)


class KeyBindingsManager(object):
    """
    Pymux key binding manager.
    """
    def __init__(self, pymux):
        self.pymux = pymux

        def get_search_state(cli):
            " Return the currently active SearchState. (The one for the focussed pane.) "
            return pymux.arrangement.get_active_pane(cli).search_state

        # Start from this KeyBindingManager from prompt_toolkit, to have basic
        # editing functionality for the command line. These key binding are
        # however only active when the following `enable_all` condition is met.
        self.pt_key_bindings_manager = pt_KeyBindingManager(
            enable_all=(HasFocus(COMMAND) | HasFocus(PROMPT) | InScrollBuffer(pymux)) & ~HasPrefix(pymux),
            enable_auto_suggest_bindings=True,
            enable_search=False,  # We have our own search bindings, that support multiple panes.
            enable_extra_page_navigation=True,
            get_search_state=get_search_state)

        self.registry = self.pt_key_bindings_manager.registry

        self._prefix = (Keys.ControlB, )
        self._prefix_binding = None

        # Load initial bindings.
        self._load_builtins()
        self._load_prefix_binding()
        _load_search_bindings(pymux, self.registry)

        # Custom user configured key bindings.
        # { (needs_prefix, key) -> (command, handler) }
        self.custom_bindings = {}

    def _load_prefix_binding(self):
        """
        Load the prefix key binding.
        """
        pymux = self.pymux
        registry = self.registry

        # Remove previous binding.
        if self._prefix_binding:
            self.registry.remove_binding(self._prefix_binding)

        # Create new Python binding.
        @registry.add_binding(*self._prefix, filter=
            ~(HasPrefix(pymux) | HasFocus(COMMAND) | HasFocus(PROMPT) | WaitsForConfirmation(pymux)))
        def enter_prefix_handler(event):
            " Enter prefix mode. "
            pymux.get_client_state(event.cli).has_prefix = True

        self._prefix_binding = enter_prefix_handler

    @property
    def prefix(self):
        " Get the prefix key. "
        return self._prefix

    @prefix.setter
    def prefix(self, keys):
        """
        Set a new prefix key.
        """
        assert isinstance(keys, tuple)

        self._prefix = keys
        self._load_prefix_binding()

    def _load_builtins(self):
        """
        Fill the Registry with the hard coded key bindings.
        """
        pymux = self.pymux
        registry = self.registry

        # Create filters.
        has_prefix = HasPrefix(pymux)
        waits_for_confirmation = WaitsForConfirmation(pymux)
        prompt_or_command_focus = HasFocus(COMMAND) | HasFocus(PROMPT)
        display_pane_numbers = Condition(lambda cli: pymux.display_pane_numbers)
        in_scroll_buffer_not_searching = InScrollBufferNotSearching(pymux)
        pane_input_allowed = ~(prompt_or_command_focus | has_prefix |
                               waits_for_confirmation | display_pane_numbers |
                               InScrollBuffer(pymux))

        @registry.add_binding(Keys.Any, filter=pane_input_allowed, invalidate_ui=False)
        def _(event):
            """
            When a pane has the focus, key bindings are redirected to the
            process running inside the pane.
            """
            # NOTE: we don't invalidate the UI, because for pymux itself,
            #       nothing in the output changes yet. It's the application in
            #       the pane that will probably echo back the typed characters.
            #       When we receive them, they are draw to the UI and it's
            #       invalidated.
            w = pymux.arrangement.get_active_window(event.cli)
            pane = w.active_pane

            if pane.clock_mode:
                # Leave clock mode on key press.
                pane.clock_mode = False
                pymux.invalidate()
            else:
                # Write input to pane. If 'synchronize_panes' is on, write
                # input to all panes in the current window.
                panes = w.panes if w.synchronize_panes else [pane]
                for p in panes:
                    p.process.write_key(event.key_sequence[0].key)

        @registry.add_binding(Keys.BracketedPaste, filter=pane_input_allowed, invalidate_ui=False)
        def _(event):
            """
            Pasting to the active pane. (Using bracketed paste.)
            """
            w = pymux.arrangement.get_active_window(event.cli)
            pane = w.active_pane

            if not pane.clock_mode:
                # Paste input to pane. If 'synchronize_panes' is on, paste
                # input to all panes in the current window.
                panes = w.panes if w.synchronize_panes else [pane]
                for p in panes:
                    p.process.write_input(event.data, paste=True)

        @registry.add_binding(Keys.Any, filter=has_prefix)
        def _(event):
            " Ignore unknown Ctrl-B prefixed key sequences. "
            pymux.get_client_state(event.cli).has_prefix = False

        @registry.add_binding(Keys.ControlC, filter=prompt_or_command_focus & ~has_prefix)
        @registry.add_binding(Keys.ControlG, filter=prompt_or_command_focus & ~has_prefix)
        @registry.add_binding(Keys.Backspace, filter=HasFocus(COMMAND) & ~has_prefix &
                              Condition(lambda cli: cli.buffers[COMMAND].text == ''))
        def _(event):
            " Leave command mode. "
            pymux.leave_command_mode(event.cli, append_to_history=False)

        @registry.add_binding('y', filter=waits_for_confirmation)
        @registry.add_binding('Y', filter=waits_for_confirmation)
        def _(event):
            """
            Confirm command.
            """
            client_state = pymux.get_client_state(event.cli)

            command = client_state.confirm_command
            client_state.confirm_command = None
            client_state.confirm_text = None

            pymux.handle_command(event.cli, command)

        @registry.add_binding('n', filter=waits_for_confirmation)
        @registry.add_binding('N', filter=waits_for_confirmation)
        @registry.add_binding(Keys.ControlC, filter=waits_for_confirmation)
        def _(event):
            """
            Cancel command.
            """
            client_state = pymux.get_client_state(event.cli)
            client_state.confirm_command = None
            client_state.confirm_text = None

        @registry.add_binding(Keys.ControlC, filter=in_scroll_buffer_not_searching)
        @registry.add_binding(Keys.ControlJ, filter=in_scroll_buffer_not_searching)
        @registry.add_binding('q', filter=in_scroll_buffer_not_searching)
        def _(event):
            " Exit scroll buffer. "
            pane = pymux.arrangement.get_active_pane(event.cli)
            pane.exit_scroll_buffer()

        @registry.add_binding(' ', filter=in_scroll_buffer_not_searching)
        def _(event):
            " Enter selection mode when pressing space in copy mode. "
            event.current_buffer.start_selection(selection_type=SelectionType.CHARACTERS)

        @registry.add_binding(Keys.ControlJ, filter=in_scroll_buffer_not_searching & HasSelection())
        def _(event):
            " Copy selection when pressing Enter. "
            clipboard_data = event.current_buffer.copy_selection()
            event.cli.clipboard.set_data(clipboard_data)

        @registry.add_binding('v', filter=in_scroll_buffer_not_searching & HasSelection())
        def _(event):
            " Toggle between selection types. "
            types = [SelectionType.LINES, SelectionType.BLOCK, SelectionType.CHARACTERS]
            selection_state = event.current_buffer.selection_state

            try:
                index = types.index(selection_state.type)
            except ValueError:  # Not in list.
                index = 0

            selection_state.type = types[(index + 1) % len(types)]

        @registry.add_binding(Keys.Any, filter=display_pane_numbers)
        def _(event):
            " When the pane numbers are shown. Any key press should hide them. "
            pymux.display_pane_numbers = False

        return registry

    def add_custom_binding(self, key_name, command, arguments, needs_prefix=False):
        """
        Add custom binding (for the "bind-key" command.)
        Raises ValueError if the give `key_name` is an invalid name.

        :param key_name: Pymux key name, for instance "C-a" or "M-x".
        """
        assert isinstance(key_name, six.text_type)
        assert isinstance(command, six.text_type)
        assert isinstance(arguments, list)

        # Unbind previous key.
        self.remove_custom_binding(key_name, needs_prefix=needs_prefix)

        # Translate the pymux key name into a prompt_toolkit key sequence.
        # (Can raise ValueError.)
        keys_sequence = pymux_key_to_prompt_toolkit_key_sequence(key_name)

        # Create handler and add to Registry.
        if needs_prefix:
            filter = HasPrefix(self.pymux)
        else:
            filter = ~HasPrefix(self.pymux)

        filter = filter & ~(WaitsForConfirmation(self.pymux) |
                            HasFocus(COMMAND) | HasFocus(PROMPT))

        def key_handler(event):
            " The actual key handler. "
            call_command_handler(command, self.pymux, event.cli, arguments)
            self.pymux.get_client_state(event.cli).has_prefix = False

        self.registry.add_binding(*keys_sequence, filter=filter)(key_handler)

        # Store key in `custom_bindings` in order to be able to call
        # "unbind-key" later on.
        k = (needs_prefix, key_name)
        self.custom_bindings[k] = CustomBinding(key_handler, command, arguments)

    def remove_custom_binding(self, key_name, needs_prefix=False):
        """
        Remove custom key binding for a key.

        :param key_name: Pymux key name, for instance "C-A".
        """
        k = (needs_prefix, key_name)

        if k in self.custom_bindings:
            self.registry.remove_binding(self.custom_bindings[k].handler)
            del self.custom_bindings[k]


class CustomBinding(object):
    """
    Record for storing a single custom key binding.
    """
    def __init__(self, handler, command, arguments):
        assert callable(handler)
        assert isinstance(command, six.text_type)
        assert isinstance(arguments, list)

        self.handler = handler
        self.command = command
        self.arguments = arguments


def _load_search_bindings(pymux, registry):
    """
    Load the key bindings for searching. (Vi and Emacs)

    This is different from the ones of prompt_toolkit, because we have a
    individual search buffers for each pane.
    """
    is_searching = InScrollBufferSearching(pymux)
    in_scroll_buffer_not_searching = InScrollBufferNotSearching(pymux)

    def search_buffer_is_empty(cli):
        """ Returns True when the search buffer is empty. """
        return pymux.arrangement.get_active_pane(cli).search_buffer.text == ''

    @registry.add_binding(Keys.ControlG, filter=is_searching)
    @registry.add_binding(Keys.ControlC, filter=is_searching)
    @registry.add_binding(Keys.Backspace, filter=is_searching & Condition(search_buffer_is_empty))
    def _(event):
        """
        Abort an incremental search and restore the original line.
        """
        pane = pymux.arrangement.get_active_pane(event.cli)
        pane.search_buffer.reset()
        pane.is_searching = False

    @registry.add_binding(Keys.ControlJ, filter=is_searching)
    def _(event):
        """
        When enter pressed in isearch, accept search.
        """
        pane = pymux.arrangement.get_active_pane(event.cli)

        input_buffer = pane.scroll_buffer
        search_buffer = pane.search_buffer

        # Update search state.
        if search_buffer.text:
            pane.search_state.text = search_buffer.text

        # Apply search.
        input_buffer.apply_search(pane.search_state, include_current_position=True)

        # Add query to history of search line.
        search_buffer.append_to_history()

        # Focus previous document again.
        pane.search_buffer.reset()
        pane.is_searching = False

    def enter_search(cli):
        cli.vi_state.input_mode = InputMode.INSERT

        pane = pymux.arrangement.get_active_pane(cli)
        pane.is_searching = True
        return pane.search_state

    @registry.add_binding(Keys.ControlR, filter=in_scroll_buffer_not_searching)
    @registry.add_binding('?', filter=in_scroll_buffer_not_searching)
    def _(event):
        " Enter reverse search. "
        search_state = enter_search(event.cli)
        search_state.direction = IncrementalSearchDirection.BACKWARD

    @registry.add_binding(Keys.ControlS, filter=in_scroll_buffer_not_searching)
    @registry.add_binding('/', filter=in_scroll_buffer_not_searching)
    def _(event):
        " Enter forward search. "
        search_state = enter_search(event.cli)
        search_state.direction = IncrementalSearchDirection.FORWARD

    @registry.add_binding(Keys.ControlR, filter=is_searching)
    @registry.add_binding(Keys.Up, filter=is_searching)
    def _(event):
        " Repeat reverse search. (While searching.) "
        pane = pymux.arrangement.get_active_pane(event.cli)

        # Update search_state.
        search_state = pane.search_state
        direction_changed = search_state.direction != IncrementalSearchDirection.BACKWARD

        search_state.text = pane.search_buffer.text
        search_state.direction = IncrementalSearchDirection.BACKWARD

        # Apply search to current buffer.
        if not direction_changed:
            pane.scroll_buffer.apply_search(
                pane.search_state, include_current_position=False, count=event.arg)

    @registry.add_binding(Keys.ControlS, filter=is_searching)
    @registry.add_binding(Keys.Down, filter=is_searching)
    def _(event):
        " Repeat forward search. (While searching.) "
        pane = pymux.arrangement.get_active_pane(event.cli)

        # Update search_state.
        search_state = pane.search_state
        direction_changed = search_state.direction != IncrementalSearchDirection.FORWARD

        search_state.text = pane.search_buffer.text
        search_state.direction = IncrementalSearchDirection.FORWARD

        # Apply search to current buffer.
        if not direction_changed:
            pane.scroll_buffer.apply_search(
                pane.search_state, include_current_position=False, count=event.arg)
