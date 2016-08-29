"""
Mapping between vt100 key sequences, the prompt_toolkit key constants and the
Pymux namings. (Those namings are kept compatible with tmux.)
"""
from __future__ import unicode_literals
from prompt_toolkit.keys import Keys
from prompt_toolkit.terminal.vt100_input import ANSI_SEQUENCES

__all__ = (
    'pymux_key_to_prompt_toolkit_key_sequence',
    'prompt_toolkit_key_to_vt100_key',
    'PYMUX_TO_PROMPT_TOOLKIT_KEYS',
)


def pymux_key_to_prompt_toolkit_key_sequence(key):
    """
    Turn a pymux description of a key. E.g.  "C-a" or "M-x" into a
    prompt-toolkit key sequence.

    Raises `ValueError` if the key is not known.
    """
    # Make the c- and m- prefixes case insensitive.
    if key.lower().startswith('m-c-'):
        key = 'M-C-' + key[4:]
    elif key.lower().startswith('c-'):
        key = 'C-' + key[2:]
    elif key.lower().startswith('m-'):
        key = 'M-' + key[2:]

    # Lookup key.
    try:
        return PYMUX_TO_PROMPT_TOOLKIT_KEYS[key]
    except KeyError:
        if len(key) == 1:
            return (key, )
        else:
            raise ValueError('Unknown key: %r' % (key, ))


# Create a mapping from prompt_toolkit keys to their ANSI sequences.
# TODO: This is not completely correct yet. It doesn't take
#       cursor/application mode into account. Create new tables for this.
_PROMPT_TOOLKIT_KEY_TO_VT100 = dict(
    (key, vt100_data) for vt100_data, key in ANSI_SEQUENCES.items())


def prompt_toolkit_key_to_vt100_key(key, application_mode=False):
    """
    Turn a prompt toolkit key. (E.g Keys.ControlB) into a Vt100 key sequence.
    (E.g. \x1b[A.)
    """
    application_mode_keys = {
        Keys.Up: '\x1bOA',
        Keys.Left: '\x1bOD',
        Keys.Right: '\x1bOC',
        Keys.Down: '\x1bOB',
    }

    if key == Keys.ControlJ:
        # Required for redis-cli. This can be removed when prompt_toolkit stops
        # replacing \r by \n.
        return '\r'

    if key == '\n':
        return '\r'

    elif application_mode and key in application_mode_keys:
        return application_mode_keys.get(key)
    else:
        return _PROMPT_TOOLKIT_KEY_TO_VT100.get(key, key)


PYMUX_TO_PROMPT_TOOLKIT_KEYS = {
    'Space': (' '),

    'C-a': (Keys.ControlA, ),
    'C-b': (Keys.ControlB, ),
    'C-c': (Keys.ControlC, ),
    'C-d': (Keys.ControlD, ),
    'C-e': (Keys.ControlE, ),
    'C-f': (Keys.ControlF, ),
    'C-g': (Keys.ControlG, ),
    'C-h': (Keys.ControlH, ),
    'C-i': (Keys.ControlI, ),
    'C-j': (Keys.ControlJ, ),
    'C-k': (Keys.ControlK, ),
    'C-l': (Keys.ControlL, ),
    'C-m': (Keys.ControlM, ),
    'C-n': (Keys.ControlN, ),
    'C-o': (Keys.ControlO, ),
    'C-p': (Keys.ControlP, ),
    'C-q': (Keys.ControlQ, ),
    'C-r': (Keys.ControlR, ),
    'C-s': (Keys.ControlS, ),
    'C-t': (Keys.ControlT, ),
    'C-u': (Keys.ControlU, ),
    'C-v': (Keys.ControlV, ),
    'C-w': (Keys.ControlW, ),
    'C-x': (Keys.ControlX, ),
    'C-y': (Keys.ControlY, ),
    'C-z': (Keys.ControlZ, ),

    'C-Left': (Keys.ControlLeft, ),
    'C-Right': (Keys.ControlRight, ),
    'C-Up': (Keys.ControlUp, ),
    'C-Down': (Keys.ControlDown, ),
    'C-\\': (Keys.ControlBackslash, ),

    'S-Left':  (Keys.ShiftLeft, ),
    'S-Right': (Keys.ShiftRight, ),
    'S-Up':    (Keys.ShiftUp, ),
    'S-Down':  (Keys.ShiftDown, ),

    'M-C-a': (Keys.Escape, Keys.ControlA, ),
    'M-C-b': (Keys.Escape, Keys.ControlB, ),
    'M-C-c': (Keys.Escape, Keys.ControlC, ),
    'M-C-d': (Keys.Escape, Keys.ControlD, ),
    'M-C-e': (Keys.Escape, Keys.ControlE, ),
    'M-C-f': (Keys.Escape, Keys.ControlF, ),
    'M-C-g': (Keys.Escape, Keys.ControlG, ),
    'M-C-h': (Keys.Escape, Keys.ControlH, ),
    'M-C-i': (Keys.Escape, Keys.ControlI, ),
    'M-C-j': (Keys.Escape, Keys.ControlJ, ),
    'M-C-k': (Keys.Escape, Keys.ControlK, ),
    'M-C-l': (Keys.Escape, Keys.ControlL, ),
    'M-C-m': (Keys.Escape, Keys.ControlM, ),
    'M-C-n': (Keys.Escape, Keys.ControlN, ),
    'M-C-o': (Keys.Escape, Keys.ControlO, ),
    'M-C-p': (Keys.Escape, Keys.ControlP, ),
    'M-C-q': (Keys.Escape, Keys.ControlQ, ),
    'M-C-r': (Keys.Escape, Keys.ControlR, ),
    'M-C-s': (Keys.Escape, Keys.ControlS, ),
    'M-C-t': (Keys.Escape, Keys.ControlT, ),
    'M-C-u': (Keys.Escape, Keys.ControlU, ),
    'M-C-v': (Keys.Escape, Keys.ControlV, ),
    'M-C-w': (Keys.Escape, Keys.ControlW, ),
    'M-C-x': (Keys.Escape, Keys.ControlX, ),
    'M-C-y': (Keys.Escape, Keys.ControlY, ),
    'M-C-z': (Keys.Escape, Keys.ControlZ, ),

    'M-C-Left': (Keys.Escape, Keys.ControlLeft, ),
    'M-C-Right': (Keys.Escape, Keys.ControlRight, ),
    'M-C-Up': (Keys.Escape, Keys.ControlUp, ),
    'M-C-Down': (Keys.Escape, Keys.ControlDown, ),
    'M-C-\\': (Keys.Escape, Keys.ControlBackslash, ),

    'M-a': (Keys.Escape, 'a'),
    'M-b': (Keys.Escape, 'b'),
    'M-c': (Keys.Escape, 'c'),
    'M-d': (Keys.Escape, 'd'),
    'M-e': (Keys.Escape, 'e'),
    'M-f': (Keys.Escape, 'f'),
    'M-g': (Keys.Escape, 'g'),
    'M-h': (Keys.Escape, 'h'),
    'M-i': (Keys.Escape, 'i'),
    'M-j': (Keys.Escape, 'j'),
    'M-k': (Keys.Escape, 'k'),
    'M-l': (Keys.Escape, 'l'),
    'M-m': (Keys.Escape, 'm'),
    'M-n': (Keys.Escape, 'n'),
    'M-o': (Keys.Escape, 'o'),
    'M-p': (Keys.Escape, 'p'),
    'M-q': (Keys.Escape, 'q'),
    'M-r': (Keys.Escape, 'r'),
    'M-s': (Keys.Escape, 's'),
    'M-t': (Keys.Escape, 't'),
    'M-u': (Keys.Escape, 'u'),
    'M-v': (Keys.Escape, 'v'),
    'M-w': (Keys.Escape, 'w'),
    'M-x': (Keys.Escape, 'x'),
    'M-y': (Keys.Escape, 'y'),
    'M-z': (Keys.Escape, 'z'),

    'M-0': (Keys.Escape, '0'),
    'M-1': (Keys.Escape, '1'),
    'M-2': (Keys.Escape, '2'),
    'M-3': (Keys.Escape, '3'),
    'M-4': (Keys.Escape, '4'),
    'M-5': (Keys.Escape, '5'),
    'M-6': (Keys.Escape, '6'),
    'M-7': (Keys.Escape, '7'),
    'M-8': (Keys.Escape, '8'),
    'M-9': (Keys.Escape, '9'),

    'M-Up': (Keys.Escape, Keys.Up),
    'M-Down': (Keys.Escape, Keys.Down, ),
    'M-Left': (Keys.Escape, Keys.Left, ),
    'M-Right': (Keys.Escape, Keys.Right, ),
    'Left': (Keys.Left, ),
    'Right': (Keys.Right, ),
    'Up': (Keys.Up, ),
    'Down': (Keys.Down, ),
    'BSpace': (Keys.Backspace, ),
    'BTab': (Keys.BackTab, ),
    'DC': (Keys.Delete, ),
    'IC': (Keys.Insert, ),
    'End': (Keys.End, ),
    'Enter': (Keys.ControlJ, ),
    'Home': (Keys.Home, ),
    'Escape': (Keys.Escape, ),
    'Tab': (Keys.Tab, ),

    'F1': (Keys.F1, ),
    'F2': (Keys.F2, ),
    'F3': (Keys.F3, ),
    'F4': (Keys.F4, ),
    'F5': (Keys.F5, ),
    'F6': (Keys.F6, ),
    'F7': (Keys.F7, ),
    'F8': (Keys.F8, ),
    'F9': (Keys.F9, ),
    'F10': (Keys.F10, ),
    'F11': (Keys.F11, ),
    'F12': (Keys.F12, ),
    'F13': (Keys.F13, ),
    'F14': (Keys.F14, ),
    'F15': (Keys.F15, ),
    'F16': (Keys.F16, ),
    'F17': (Keys.F17, ),
    'F18': (Keys.F18, ),
    'F19': (Keys.F19, ),
    'F20': (Keys.F20, ),

    'NPage': (Keys.PageDown, ),
    'PageDown': (Keys.PageDown, ),
    'PgDn': (Keys.PageDown, ),
    'PPage': (Keys.PageUp, ),
    'PageUp': (Keys.PageUp, ),
    'PgUp': (Keys.PageUp, ),
}
