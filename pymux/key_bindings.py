"""
Key bindings.
"""
from __future__ import unicode_literals
from prompt_toolkit.filters import has_focus, Condition, has_selection
from prompt_toolkit.keys import Keys
from prompt_toolkit.selection import SelectionType
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings

from .enums import COMMAND, PROMPT
from .filters import WaitsForConfirmation, HasPrefix, InScrollBuffer, InScrollBufferNotSearching
from .key_mappings import pymux_key_to_prompt_toolkit_key_sequence
from .commands.commands import call_command_handler

import six

__all__ = (
    'PymuxKeyBindings',
)


class PymuxKeyBindings(object):
    """
    Pymux key binding manager.
    """
    def __init__(self, pymux):
        self.pymux = pymux

        def get_search_state():
            " Return the currently active SearchState. (The one for the focused pane.) "
            return pymux.arrangement.get_active_pane().search_state

        self.custom_key_bindings = KeyBindings()

        self.key_bindings = merge_key_bindings([
            self._load_builtins(),
            self.custom_key_bindings,
        ])

        self._prefix = ('c-b', )
        self._prefix_binding = None

        # Load initial bindings.
        self._load_prefix_binding()

        # Custom user configured key bindings.
        # { (needs_prefix, key) -> (command, handler) }
        self.custom_bindings = {}

    def _load_prefix_binding(self):
        """
        Load the prefix key binding.
        """
        pymux = self.pymux

        # Remove previous binding.
        if self._prefix_binding:
            self.key_bindings.remove_binding(self._prefix_binding)

        # Create new Python binding.
        @self.custom_key_bindings.add(*self._prefix, filter=
            ~(HasPrefix(pymux) | has_focus(COMMAND) | has_focus(PROMPT) | WaitsForConfirmation(pymux)))
        def enter_prefix_handler(event):
            " Enter prefix mode. "
            pymux.get_client_state().has_prefix = True

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
        kb = KeyBindings()

        # Create filters.
        has_prefix = HasPrefix(pymux)
        waits_for_confirmation = WaitsForConfirmation(pymux)
        prompt_or_command_focus = has_focus(COMMAND) | has_focus(PROMPT)
        display_pane_numbers = Condition(lambda: pymux.display_pane_numbers)
        in_scroll_buffer_not_searching = InScrollBufferNotSearching(pymux)

        @kb.add(Keys.Any, filter=has_prefix)
        def _(event):
            " Ignore unknown Ctrl-B prefixed key sequences. "
            pymux.get_client_state().has_prefix = False

        @kb.add('c-c', filter=prompt_or_command_focus & ~has_prefix)
        @kb.add('c-g', filter=prompt_or_command_focus & ~has_prefix)
#        @kb.add('backspace', filter=has_focus(COMMAND) & ~has_prefix &
#                              Condition(lambda: cli.buffers[COMMAND].text == ''))
        def _(event):
            " Leave command mode. "
            pymux.leave_command_mode(append_to_history=False)

        @kb.add('y', filter=waits_for_confirmation)
        @kb.add('Y', filter=waits_for_confirmation)
        def _(event):
            """
            Confirm command.
            """
            client_state = pymux.get_client_state()

            command = client_state.confirm_command
            client_state.confirm_command = None
            client_state.confirm_text = None

            pymux.handle_command(command)

        @kb.add('n', filter=waits_for_confirmation)
        @kb.add('N', filter=waits_for_confirmation)
        @kb.add('c-c' , filter=waits_for_confirmation)
        def _(event):
            """
            Cancel command.
            """
            client_state = pymux.get_client_state()
            client_state.confirm_command = None
            client_state.confirm_text = None

        @kb.add('c-c', filter=in_scroll_buffer_not_searching)
        @kb.add('enter', filter=in_scroll_buffer_not_searching)
        @kb.add('q', filter=in_scroll_buffer_not_searching)
        def _(event):
            " Exit scroll buffer. "
            pane = pymux.arrangement.get_active_pane()
            pane.exit_scroll_buffer()

        @kb.add(' ', filter=in_scroll_buffer_not_searching)
        def _(event):
            " Enter selection mode when pressing space in copy mode. "
            event.current_buffer.start_selection(selection_type=SelectionType.CHARACTERS)

        @kb.add('enter', filter=in_scroll_buffer_not_searching & has_selection)
        def _(event):
            " Copy selection when pressing Enter. "
            clipboard_data = event.current_buffer.copy_selection()
            event.app.clipboard.set_data(clipboard_data)

        @kb.add('v', filter=in_scroll_buffer_not_searching & has_selection)
        def _(event):
            " Toggle between selection types. "
            types = [SelectionType.LINES, SelectionType.BLOCK, SelectionType.CHARACTERS]
            selection_state = event.current_buffer.selection_state

            try:
                index = types.index(selection_state.type)
            except ValueError:  # Not in list.
                index = 0

            selection_state.type = types[(index + 1) % len(types)]

        @Condition
        def popup_displayed():
            return self.pymux.get_client_state().display_popup

        @kb.add('q', filter=popup_displayed, eager=True)
        def _(event):
            " Quit pop-up dialog. "
            self.pymux.get_client_state().display_popup = False

        @kb.add(Keys.Any, eager=True, filter=display_pane_numbers)
        def _(event):
            " When the pane numbers are shown. Any key press should hide them. "
            pymux.display_pane_numbers = False

        @Condition
        def clock_displayed():
            " "
            pane = pymux.arrangement.get_active_pane()
            return pane.clock_mode

        @kb.add(Keys.Any, eager=True, filter=clock_displayed)
        def _(event):
            " When the clock is displayed. Any key press should hide it. "
            pane = pymux.arrangement.get_active_pane()
            pane.clock_mode = False

        return kb

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
                            has_focus(COMMAND) | has_focus(PROMPT))

        def key_handler(event):
            " The actual key handler. "
            call_command_handler(command, self.pymux, arguments)
            self.pymux.get_client_state().has_prefix = False

        self.custom_key_bindings.add(*keys_sequence, filter=filter)(key_handler)

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
            self.custom_key_bindings.remove(self.custom_bindings[k].handler)
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
