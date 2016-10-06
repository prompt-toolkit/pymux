"""
Pymux string formatting.
"""
from __future__ import unicode_literals
import datetime
import socket
import six

__all__ = (
    'format_pymux_string',
)


def format_pymux_string(pymux, cli, string, window=None, pane=None):
    """
    Apply pymux sting formatting. (Similar to tmux.)
    E.g.  #P is replaced by the index of the active pane.

    We try to stay compatible with tmux, if possible.
    One thing that we won't support (for now) is colors, because our styling
    works different. (With a Style class.) On the other hand, in the future, we
    could allow things like `#[token=Token.Title.PID]`. This gives a clean
    separation of semantics and colors, making it easy to write different color
    schemes.
    """
    arrangement = pymux.arrangement

    if window is None:
        window = arrangement.get_active_window(cli)

    if pane is None:
        pane = window.active_pane

    def id_of_pane():
        return '%s' % (pane.pane_id, )

    def index_of_pane():
        try:
            return '%s' % (window.get_pane_index(pane), )
        except ValueError:
            return '/'

    def index_of_window():
        return '%s' % (window.index, )

    def name_of_window():
        return window.name or '(noname)'

    def window_flags():
        z = 'Z' if window.zoom else ''

        if window == arrangement.get_active_window(cli):
            return '*' + z
        elif window == arrangement.get_previous_active_window(cli):
            return '-' + z
        else:
            return z + ' '

    def name_of_session():
        return pymux.session_name

    def title_of_pane():
        return pane.process.screen.title

    def hostname():
        return socket.gethostname()

    def literal():
        return '#'

    format_table = {
        '#D': id_of_pane,
        '#F': window_flags,
        '#I': index_of_window,
        '#P': index_of_pane,
        '#S': name_of_session,
        '#T': title_of_pane,
        '#W': name_of_window,
        '#h': hostname,
        '##': literal,
    }

    # Date/time formatting.
    if '%' in string:
        try:
            if six.PY2:
                string = datetime.datetime.now().strftime(
                    string.encode('utf-8')).decode('utf-8')
            else:
                string = datetime.datetime.now().strftime(string)
        except ValueError:  # strftime format ends with raw %
            string = '<ValueError>'

    # Apply '#' formatting.
    for symbol, f in format_table.items():
        if symbol in string:
            string = string.replace(symbol, f())

    return string
