"""
Pymux string formatting.
"""
import datetime
import socket
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pymux.main import Pymux
    from pymux.arrangement import Window, Pane

__all__ = ["format_pymux_string"]


def format_pymux_string(
    pymux: "Pymux",
    string: str,
    window: Optional["Window"] = None,
    pane: Optional["Pane"] = None,
) -> str:
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
        window = arrangement.get_active_window()

    if pane is None:
        pane = window.active_pane

    def id_of_pane():
        return "%s" % (pane.pane_id,)

    def index_of_pane():
        try:
            return "%s" % (window.get_pane_index(pane),)
        except ValueError:
            return "/"

    def index_of_window():
        return "%s" % (window.index,)

    def name_of_window():
        return window.name or "(noname)"

    def window_flags():
        z = "Z" if window.zoom else ""

        if window == arrangement.get_active_window():
            return "*" + z
        elif window == arrangement.get_previous_active_window():
            return "-" + z
        else:
            return z + " "

    def name_of_session():
        return pymux.session_name

    def title_of_pane():
        return pane.process.screen.title

    def hostname():
        return socket.gethostname()

    def literal():
        return "#"

    format_table = {
        "#D": id_of_pane,
        "#F": window_flags,
        "#I": index_of_window,
        "#P": index_of_pane,
        "#S": name_of_session,
        "#T": title_of_pane,
        "#W": name_of_window,
        "#h": hostname,
        "##": literal,
    }

    # Date/time formatting.
    if "%" in string:
        try:
            string = datetime.datetime.now().strftime(string)
        except ValueError:  # strftime format ends with raw %
            string = "<ValueError>"

    # Apply '#' formatting.
    for symbol, f in format_table.items():
        if symbol in string:
            string = string.replace(symbol, f())

    return string
