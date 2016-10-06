"""
All configurable options which can be changed through "set-option" commands.
"""
from __future__ import unicode_literals
from abc import ABCMeta, abstractmethod
import six

from .key_mappings import PYMUX_TO_PROMPT_TOOLKIT_KEYS, pymux_key_to_prompt_toolkit_key_sequence
from .utils import get_default_shell
from .layout import Justify

__all__ = (
    'Option',
    'SetOptionError',
    'OnOffOption',
    'ALL_OPTIONS',
    'ALL_WINDOW_OPTIONS',
)


class Option(six.with_metaclass(ABCMeta, object)):
    """
    Base class for all options.
    """
    @abstractmethod
    def get_all_values(self):
        """
        Return a list of strings, with all possible values. (For
        autocompletion.)
        """

    @abstractmethod
    def set_value(self, pymux, cli, value):
        " Set option. This can raise SetOptionError. "


class SetOptionError(Exception):
    """
    Raised when setting an option fails.
    """
    def __init__(self, message):
        self.message = message


class OnOffOption(Option):
    """
    Boolean on/off option.
    """
    def __init__(self, attribute_name, window_option=False):
        self.attribute_name = attribute_name
        self.window_option = window_option

    def get_all_values(self, pymux):
        return ['on', 'off']

    def set_value(self, pymux, cli, value):
        value = value.lower()

        if value in ('on', 'off'):
            if self.window_option:
                w = pymux.arrangement.get_active_window(cli)
                setattr(w, self.attribute_name, (value == 'on'))
            else:
                setattr(pymux, self.attribute_name, (value == 'on'))
        else:
            raise SetOptionError('Expecting "yes" or "no".')


class StringOption(Option):
    """
    String option, the attribute is set as a Pymux attribute.
    """
    def __init__(self, attribute_name, possible_values=None):
        self.attribute_name = attribute_name
        self.possible_values = possible_values or []

    def get_all_values(self, pymux):
        return sorted(set(
            self.possible_values + [getattr(pymux, self.attribute_name)]
        ))

    def set_value(self, pymux, cli, value):
        setattr(pymux, self.attribute_name, value)


class PositiveIntOption(Option):
    """
    Positive integer option, the attribute is set as a Pymux attribute.
    """
    def __init__(self, attribute_name, possible_values=None):
        self.attribute_name = attribute_name
        self.possible_values = ['%s' % i for i in (possible_values or [])]

    def get_all_values(self, pymux):
        return sorted(set(
            self.possible_values +
            ['%s' % getattr(pymux, self.attribute_name)]
        ))

    def set_value(self, pymux, cli, value):
        """
        Take a string, and return an integer. Raise SetOptionError when the
        given text does not parse to a positive integer.
        """
        try:
            value = int(value)
            if value < 0:
                raise ValueError
        except ValueError:
            raise SetOptionError('Expecting an integer.')
        else:
            setattr(pymux, self.attribute_name, value)


class KeyPrefixOption(Option):
    def get_all_values(self, pymux):
        return PYMUX_TO_PROMPT_TOOLKIT_KEYS.keys()

    def set_value(self, pymux, cli, value):
        # Translate prefix to prompt_toolkit
        try:
            keys = pymux_key_to_prompt_toolkit_key_sequence(value)
        except ValueError:
            raise SetOptionError('Invalid key: %r' % (value, ))
        else:
            pymux.key_bindings_manager.prefix = keys


class BaseIndexOption(Option):
    " Base index for window numbering. "
    def get_all_values(self, pymux):
        return ['0', '1']

    def set_value(self, pymux, cli, value):
        try:
            value = int(value)
        except ValueError:
            raise SetOptionError('Expecting an integer.')
        else:
            pymux.arrangement.base_index = value


class KeysOption(Option):
    " Emacs or Vi mode. "
    def __init__(self, attribute_name):
        self.attribute_name = attribute_name

    def get_all_values(self, pymux):
        return ['emacs', 'vi']

    def set_value(self, pymux, cli, value):
        if value in ('emacs', 'vi'):
            setattr(pymux, self.attribute_name, value == 'vi')
        else:
            raise SetOptionError('Expecting "vi" or "emacs".')

class JustifyOption(Option):
    def __init__(self, attribute_name):
        self.attribute_name = attribute_name

    def get_all_values(self, pymux):
        return Justify._ALL

    def set_value(self, pymux, cli, value):
        if value in Justify._ALL:
            setattr(pymux, self.attribute_name, value)
        else:
            raise SetOptionError('Invalid justify option.')


ALL_OPTIONS = {
    'base-index': BaseIndexOption(),
    'bell': OnOffOption('enable_bell'),
    'history-limit': PositiveIntOption(
        'history_limit', [200, 500, 1000, 2000, 5000, 10000]),
    'mouse': OnOffOption('enable_mouse_support'),
    'prefix': KeyPrefixOption(),
    'remain-on-exit': OnOffOption('remain_on_exit'),
    'status': OnOffOption('enable_status'),
    'pane-border-status': OnOffOption('enable_pane_status'),
    'status-keys': KeysOption('status_keys_vi_mode'),
    'mode-keys': KeysOption('mode_keys_vi_mode'),
    'default-terminal': StringOption(
        'default_terminal', ['xterm', 'xterm-256color', 'screen']),
    'status-right': StringOption('status_right'),
    'status-left': StringOption('status_left'),
    'status-right-length': PositiveIntOption('status_right_length', [20]),
    'status-left-length': PositiveIntOption('status_left_length', [20]),
    'window-status-format': StringOption('window_status_format'),
    'window-status-current-format': StringOption('window_status_current_format'),
    'default-shell': StringOption(
        'default_shell', [get_default_shell()]),
    'status-justify': JustifyOption('status_justify'),
    'status-interval': PositiveIntOption(
        'status_interval', [1, 2, 4, 8, 16, 30, 60]),
}


ALL_WINDOW_OPTIONS = {
    'synchronize-panes': OnOffOption('synchronize_panes', window_option=True),
}
