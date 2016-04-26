from __future__ import unicode_literals

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.contrib.completers import WordCompleter
from prompt_toolkit.document import Document

from .aliases import ALIASES
from .commands import COMMANDS_TO_HANDLERS, get_option_flags_for_command
from .utils import wrap_argument

from pymux.arrangement import LayoutTypes
from pymux.key_mappings import PYMUX_TO_PROMPT_TOOLKIT_KEYS

from functools import partial


__all__ = (
    'create_command_completer',
)


def create_command_completer(pymux):
    return ShlexCompleter(partial(get_completions_for_parts, pymux=pymux))


class CommandCompleter(Completer):
    """
    Completer for command names.
    """
    def __init__(self):
        # Completer for full command names.
        self._command_completer = WordCompleter(
            sorted(COMMANDS_TO_HANDLERS.keys()),
            ignore_case=True, WORD=True, match_middle=True)

        # Completer for aliases.
        self._aliases_completer = WordCompleter(
            sorted(ALIASES.keys()),
            ignore_case=True, WORD=True, match_middle=True)

    def get_completions(self, document, complete_event):
        # First, complete on full command names.
        found = False

        for c in self._command_completer.get_completions(document, complete_event):
            found = True
            yield c

        # When no matches are found, complete aliases instead.
        # The completion however, inserts the full name.
        if not found:
            for c in self._aliases_completer.get_completions(document, complete_event):
                full_name = ALIASES.get(c.display)

                yield Completion(full_name,
                                 start_position=c.start_position,
                                 display='%s (%s)' % (c.display, full_name))


_command_completer = CommandCompleter()
_layout_type_completer = WordCompleter(sorted(LayoutTypes._ALL), WORD=True)
_keys_completer = WordCompleter(sorted(PYMUX_TO_PROMPT_TOOLKIT_KEYS.keys()),
                                ignore_case=True, WORD=True)


def get_completions_for_parts(parts, last_part, complete_event, pymux):
    completer = None

    # Resolve aliases.
    if len(parts) > 0:
        parts = [ALIASES.get(parts[0], parts[0])] + parts[1:]

    if len(parts) == 0:
        # New command.
        completer = _command_completer

    elif len(parts) >= 1 and last_part.startswith('-'):
        flags = get_option_flags_for_command(parts[0])
        completer = WordCompleter(sorted(flags), WORD=True)

    elif len(parts) == 1 and parts[0] in ('set-option', 'set-window-option'):
        options = pymux.options if parts[0] == 'set-option' else pymux.window_options

        completer = WordCompleter(sorted(options.keys()), sentence=True)

    elif len(parts) == 2 and parts[0] in ('set-option', 'set-window-option'):
        options = pymux.options if parts[0] == 'set-option' else pymux.window_options

        option = options.get(parts[1])
        if option:
            completer = WordCompleter(sorted(option.get_all_values(pymux)), sentence=True)

    elif len(parts) == 1 and parts[0] == 'select-layout':
        completer = _layout_type_completer

    elif len(parts) == 1 and parts[0] == 'send-keys':
        completer = _keys_completer

    elif parts[0] == 'bind-key':
        if len(parts) == 1:
            completer = _keys_completer

        elif len(parts) == 2:
            completer = _command_completer

    # Recursive, for bind-key options.
    if parts and parts[0] == 'bind-key' and len(parts) > 2:
        for c in get_completions_for_parts(parts[2:], last_part, complete_event, pymux):
            yield c

    if completer:
        for c in completer.get_completions(Document(last_part), complete_event):
            yield c


class ShlexCompleter(Completer):
    """
    Completer that can be used when the input is parsed with shlex.
    """
    def __init__(self, get_completions_for_parts):
        assert callable(get_completions_for_parts)
        self.get_completions_for_parts = get_completions_for_parts

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        parts, part_start_pos = self.parse(text)

        for c in self.get_completions_for_parts(parts[:-1], parts[-1], complete_event):
            yield Completion(wrap_argument(parts[-1][:c.start_position] + c.text),
                             start_position=part_start_pos - len(document.text),
                             display=c.display,
                             display_meta=c.display_meta)

    @classmethod
    def parse(cls, text):
        """
        Parse the given text. Returns a tuple:
        (list_of_parts, start_pos_of_the_last_part).
        """
        OUTSIDE, IN_DOUBLE, IN_SINGLE = 0, 1, 2

        iterator = enumerate(text)
        state = OUTSIDE
        parts = []
        current_part = ''
        part_start_pos = 0

        for i, c in iterator:  # XXX: correctly handle empty strings.
            if state == OUTSIDE:
                if c.isspace():
                    # New part.
                    if current_part:
                        parts.append(current_part)
                    part_start_pos = i + 1
                    current_part = ''
                elif c == '"':
                    state = IN_DOUBLE
                elif c == "'":
                    state = IN_SINGLE
                else:
                    current_part += c

            elif state == IN_SINGLE:
                if c == "'":
                    state = OUTSIDE
                elif c == "\\":
                    next(iterator)
                    current_part += c
                else:
                    current_part += c

            elif state == IN_DOUBLE:
                if c == '"':
                    state = OUTSIDE
                elif c == "\\":
                    next(iterator)
                    current_part += c
                else:
                    current_part += c

        parts.append(current_part)
        return parts, part_start_pos


# assert ShlexCompleter.parse('"hello" world') == (['hello', 'world'], 8)
