"""
Arrangement of panes.

Don't confuse with the prompt_toolkit VSplit/HSplit classes. This is a higher
level abstraction of the Pymux window layout.

An arrangement consists of a list of windows. And a window has a list of panes,
arranged by ordering them in HSplit/VSplit instances.
"""
import math
import os
from enum import Enum
from typing import Dict, List, Optional, Union
from weakref import WeakKeyDictionary, ref

from prompt_toolkit.application import Application, get_app, get_app_or_none, set_app
from prompt_toolkit.buffer import Buffer
from ptterm import Terminal

__all__ = [
    "LayoutTypes",
    "Pane",
    "HSplit",
    "VSplit",
    "Window",
    "Arrangement",
]


class LayoutTypes(Enum):
    # The values are in lowercase with dashes, because that is what users can
    # use at the command line.
    EVEN_HORIZONTAL = "EVEN-HORIZONTAL"
    EVEN_VERTICAL = "EVEN-VERTICAL"
    MAIN_HORIZONTAL = "MAIN-HORIZONTAL"
    MAIN_VERTICAL = "MAIN-VERTICAL"
    TILED = "TILED"


class Pane:
    """
    One pane, containing one process and a search buffer for going into copy
    mode or displaying the help.
    """

    _pane_counter = (
        1000  # Start at 1000, to be sure to not confuse this with pane indexes.
    )

    def __init__(self, terminal: Terminal) -> None:
        self.terminal = terminal
        self.chosen_name: Optional[str] = None

        # Displayed the clock instead of this pane content.
        self.clock_mode = False

        # Give unique ID.
        Pane._pane_counter += 1
        self.pane_id = Pane._pane_counter

        # Prompt_toolkit buffer, for displaying scrollable text.
        # (In copy mode, or help mode.)
        # Note: Because the scroll_buffer can only contain text, we also use the
        #       get_tokens_for_line, that returns the token list with color
        #       information for each line.
        self.scroll_buffer = Buffer(read_only=True)
        self.display_scroll_buffer = False
        self.scroll_buffer_title = ""

    @property
    def process(self):
        return self.terminal.process

    @property
    def name(self) -> str:
        """
        The name for the window as displayed in the title bar and status bar.
        """
        # Name, explicitely set for the pane.
        if self.chosen_name:
            return self.chosen_name
        else:
            # Name from the process running inside the pane.
            name = self.process.get_name()
            if name:
                return os.path.basename(name)

        return ""

    def enter_copy_mode(self) -> None:
        """
        Suspend the process, and copy the screen content to the `scroll_buffer`.
        That way the user can search through the history and copy/paste.
        """
        self.terminal.enter_copy_mode()

    def focus(self) -> None:
        """
        Focus this pane.
        """
        get_app().layout.focus(self.terminal)


class _WeightsDictionary(WeakKeyDictionary):
    """
    Dictionary for the weights: weak keys, but defaults to 1.

    (Weights are used to represent the proportion of pane sizes in
    HSplit/VSplit lists.)

    This dictionary maps the child (another HSplit/VSplit or Pane), to the
    size. (Integer.)
    """

    def __getitem__(self, key):
        try:
            # (Don't use 'super' here. This is a classobj in Python2.)
            return WeakKeyDictionary.__getitem__(self, key)
        except KeyError:
            return 1


class _Split(list):
    """
    Base class for horizontal and vertical splits. (This is a higher level
    split than prompt_toolkit.layout.HSplit.)
    """

    def __init__(self, *a, **kw):
        list.__init__(self, *a, **kw)

        # Mapping children to its weight.
        self.weights = _WeightsDictionary()

    def __hash__(self):
        # Required in order to add HSplit/VSplit to the weights dict. "
        return id(self)

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, list.__repr__(self))


class HSplit(_Split):
    """Horizontal split."""


class VSplit(_Split):
    """Horizontal split."""


class Window:
    """
    Pymux window.
    """

    _window_counter = 1000  # Start here, to avoid confusion with window index.

    def __init__(self, index: int = 0) -> None:
        self.index = index
        self.root: Union[VSplit, HSplit] = HSplit()
        self._active_pane: Optional[Pane] = None
        self._prev_active_pane: Optional["ref[Pane]"] = None
        self.chosen_name: Optional[str] = None
        self.previous_selected_layout: Optional[LayoutTypes] = None

        #: When true, the current pane is zoomed in.
        self.zoom = False

        #: When True, send input to all panes simultaniously.
        self.synchronize_panes = False

        # Give unique ID.
        Window._window_counter += 1
        self.window_id = Window._window_counter

    def invalidation_hash(self) -> str:
        """
        Return a hash (string) that can be used to determine when the layout
        has to be rebuild.
        """
        #        if not self.root:
        #            return '<empty-window>'

        def _hash_for_split(split: Union[HSplit, VSplit]) -> str:
            result = []
            for item in split:
                if isinstance(item, (VSplit, HSplit)):
                    result.append(_hash_for_split(item))
                elif isinstance(item, Pane):
                    result.append("p%s" % item.pane_id)

            if isinstance(split, HSplit):
                return "HSplit(%s)" % (",".join(result))
            else:
                return "VSplit(%s)" % (",".join(result))

        return "<window_id=%s,zoom=%s,children=%s>" % (
            self.window_id,
            self.zoom,
            _hash_for_split(self.root),
        )

    @property
    def active_pane(self) -> Optional[Pane]:
        """
        The current active :class:`.Pane`.
        """
        return self._active_pane

    @active_pane.setter
    def active_pane(self, value: Pane) -> None:
        # Remember previous active pane.
        if self._active_pane:
            self._prev_active_pane = ref(self._active_pane)

        self.zoom = False
        self._active_pane = value

    @property
    def previous_active_pane(self) -> Optional[Pane]:
        """
        The previous active :class:`.Pane` or `None` if unknown.
        """
        p = self._prev_active_pane and self._prev_active_pane()

        # Only return when this pane actually still exists in the current
        # window.
        if p and p in self.panes:
            return p
        return None

    @property
    def name(self) -> str:
        """
        The name for this window as it should be displayed in the status bar.
        """
        # Name, explicitely set for the window.
        if self.chosen_name:
            return self.chosen_name
        else:
            pane = self.active_pane
            if pane:
                return pane.name

        return ""

    def add_pane(self, pane: Pane, vsplit: bool = False) -> None:
        """
        Add another pane to this Window.
        """
        split_cls = VSplit if vsplit else HSplit

        if self.active_pane is None:
            self.root.append(pane)
        else:
            parent = self._get_parent(self.active_pane)
            same_direction = isinstance(parent, split_cls)

            index = parent.index(self.active_pane)

            if same_direction:
                parent.insert(index + 1, pane)
            else:
                new_split = split_cls([self.active_pane, pane])
                parent[index] = new_split

                # Give the newly created split the same weight as the original
                # pane that was at this position.
                parent.weights[new_split] = parent.weights[self.active_pane]

        self.active_pane = pane
        self.zoom = False

    def remove_pane(self, pane: Pane) -> None:
        """
        Remove pane from this Window.
        """
        if pane in self.panes:
            # When this pane was focused, switch to previous active or next in order.
            if pane == self.active_pane:
                if self.previous_active_pane:
                    self.active_pane = self.previous_active_pane
                else:
                    self.focus_next()

            # Remove from the parent. When the parent becomes empty, remove the
            # parent itself recursively.
            p = self._get_parent(pane)
            p.remove(pane)

            while len(p) == 0 and p != self.root:
                p2 = self._get_parent(p)
                p2.remove(p)
                p = p2

            # When the parent has only one item left, collapse into its parent.
            while len(p) == 1 and p != self.root:
                p2 = self._get_parent(p)
                p2.weights[p[0]] = p2.weights[p]  # Keep dimensions.
                i = p2.index(p)
                p2[i] = p[0]
                p = p2

    @property
    def panes(self) -> List[Pane]:
        "List with all panes from this Window."
        result = []

        for s in self.splits:
            for item in s:
                if isinstance(item, Pane):
                    result.append(item)

        return result

    @property
    def splits(self) -> List[Union[HSplit, VSplit]]:
        "Return a list with all HSplit/VSplit instances."
        result = []

        def collect(split):
            result.append(split)

            for item in split:
                if isinstance(item, (HSplit, VSplit)):
                    collect(item)

        collect(self.root)
        return result

    def _get_parent(self, item):
        "The HSplit/VSplit that contains the active pane."
        for s in self.splits:
            if item in s:
                return s

    @property
    def has_panes(self) -> bool:
        "True when this window contains at least one pane."
        return len(self.panes) > 0

    @property
    def active_process(self):
        "Return `Process` that should receive user input."
        p = self.active_pane

        if p is not None:
            return p.process

    def focus_next(self, count=1) -> None:
        "Focus the next pane."
        panes = self.panes
        if panes:
            self.active_pane = panes[
                (panes.index(self.active_pane or panes[0]) + count) % len(panes)
            ]
        else:
            self.active_pane = None  # No panes left.

    def focus_previous(self) -> None:
        "Focus the previous pane."
        self.focus_next(count=-1)

    def rotate(
        self,
        count: int = 1,
        with_pane_before_only: bool = False,
        with_pane_after_only: bool = False,
    ) -> None:
        """
        Rotate panes.
        When `with_pane_before_only` or `with_pane_after_only` is True, only rotate
        with the pane before/after the active pane.
        """
        # Create (split, index, pane, weight) tuples.
        items = []
        current_pane_index: Optional[int] = None

        for s in self.splits:
            for index, item in enumerate(s):
                if isinstance(item, Pane):
                    items.append((s, index, item, s.weights[item]))
                    if item == self.active_pane:
                        current_pane_index = len(items) - 1

        # Only before after? Reduce list of panes.
        if current_pane_index is not None:
            if with_pane_before_only:
                items = items[current_pane_index - 1 : current_pane_index + 1]

            elif with_pane_after_only:
                items = items[current_pane_index : current_pane_index + 2]

        # Rotate positions.
        for i, triple in enumerate(items):
            split, index, pane, weight = triple

            new_item = items[(i + count) % len(items)][2]

            split[index] = new_item
            split.weights[new_item] = weight

    def select_layout(self, layout_type: LayoutTypes) -> None:
        """
        Select one of the predefined layouts.
        """
        # When there is only one pane, always choose EVEN_HORIZONTAL,
        # Otherwise, we create VSplit/HSplit instances with an empty list of
        # children.
        if len(self.panes) == 1:
            layout_type = LayoutTypes.EVEN_HORIZONTAL

        # even-horizontal.
        if layout_type == LayoutTypes.EVEN_HORIZONTAL:
            self.root = HSplit(self.panes)

        # even-vertical.
        elif layout_type == LayoutTypes.EVEN_VERTICAL:
            self.root = VSplit(self.panes)

        # main-horizontal.
        elif layout_type == LayoutTypes.MAIN_HORIZONTAL:
            self.root = HSplit(
                [
                    self.active_pane,
                    VSplit([p for p in self.panes if p != self.active_pane]),
                ]
            )

        # main-vertical.
        elif layout_type == LayoutTypes.MAIN_VERTICAL:
            self.root = VSplit(
                [
                    self.active_pane,
                    HSplit([p for p in self.panes if p != self.active_pane]),
                ]
            )

        # tiled.
        elif layout_type == LayoutTypes.TILED:
            panes = self.panes
            column_count = math.ceil(len(panes) ** 0.5)

            rows = HSplit()
            current_row = VSplit()

            for p in panes:
                current_row.append(p)

                if len(current_row) >= column_count:
                    rows.append(current_row)
                    current_row = VSplit()
            if current_row:
                rows.append(current_row)

            self.root = rows

        self.previous_selected_layout = layout_type

    def select_next_layout(self, count: int = 1) -> None:
        """
        Select next layout. (Cycle through predefined layouts.)
        """
        # List of all layouts. (When we have just two panes, only toggle
        # between horizontal/vertical.)
        if len(self.panes) == 2:
            all_layouts = [LayoutTypes.EVEN_HORIZONTAL, LayoutTypes.EVEN_VERTICAL]
        else:
            all_layouts = list(LayoutTypes)

        # Get index of current layout.
        layout = self.previous_selected_layout or list(LayoutTypes)[-1]
        try:
            index = all_layouts.index(layout)
        except ValueError:
            index = 0

        # Switch to new layout.
        new_layout = all_layouts[(index + count) % len(all_layouts)]
        self.select_layout(new_layout)

    def select_previous_layout(self) -> None:
        self.select_next_layout(count=-1)

    def change_size_for_active_pane(
        self, up: int = 0, right: int = 0, down: int = 0, left: int = 0
    ) -> None:
        """
        Increase the size of the current pane in any of the four directions.
        """
        child = self.active_pane
        if child is not None:
            self.change_size_for_pane(child, up=up, right=right, down=down, left=left)

    def change_size_for_pane(self, pane: Pane, up=0, right=0, down=0, left=0):
        """
        Increase the size of the current pane in any of the four directions.
        Positive values indicate an increase, negative values a decrease.
        """

        def find_split_and_child(split_cls, is_before):
            "Find the split for which we will have to update the weights."
            child = pane
            split = self._get_parent(child)

            def found():
                return (
                    isinstance(split, split_cls)
                    and (not is_before or split.index(child) > 0)
                    and (is_before or split.index(child) < len(split) - 1)
                )

            while split and not found():
                child = split
                split = self._get_parent(child)

            return split, child  # split can be None!

        def handle_side(split_cls, is_before, amount, trying_other_side=False):
            "Increase weights on one side. (top/left/right/bottom)."
            if amount:
                split, child = find_split_and_child(split_cls, is_before)

                if split:
                    # Find neighbour.
                    neighbour_index = split.index(child) + (-1 if is_before else 1)
                    neighbour_child = split[neighbour_index]

                    # Increase/decrease weights.
                    split.weights[child] += amount
                    split.weights[neighbour_child] -= amount

                    # Ensure that all weights are at least one.
                    for k, value in split.weights.items():
                        if value < 1:
                            split.weights[k] = 1

                else:
                    # When no split has been found where we can move in this
                    # direction, try to move the other side instead using a
                    # negative amount. This happens when we run "resize-pane -R 4"
                    # inside the pane that is completely on the right. In that
                    # case it's logical to move the left border to the right
                    # instead.
                    if not trying_other_side:
                        handle_side(
                            split_cls, not is_before, -amount, trying_other_side=True
                        )

        handle_side(VSplit, True, left)
        handle_side(VSplit, False, right)
        handle_side(HSplit, True, up)
        handle_side(HSplit, False, down)

    def get_pane_index(self, pane: Pane):
        "Return the index of the given pane. ValueError if not found."
        return self.panes.index(pane)


class Arrangement:
    """
    Arrangement class for one Pymux session.
    This contains the list of windows and the layout of the panes for each
    window. All the clients share the same Arrangement instance, but they can
    have different windows active.
    """

    def __init__(self) -> None:
        self.windows: List[Window] = []
        self.base_index = 0

        self._active_window_for_cli: "WeakKeyDictionary[Application, Window]" = (
            WeakKeyDictionary()
        )
        self._prev_active_window_for_cli: "WeakKeyDictionary[Application, Window]" = (
            WeakKeyDictionary()
        )

        # The active window of the last CLI. Used as default when a new session
        # is attached.
        self._last_active_window: Optional[Window] = None

    def invalidation_hash(self) -> str:
        """
        When this changes, the layout needs to be rebuild.
        """
        if not self.windows:
            return "<no-windows>"

        w = self.get_active_window()
        return w.invalidation_hash()

    def get_active_window(self) -> Window:
        """
        The current active :class:`.Window`.
        """
        app = get_app()

        try:
            return self._active_window_for_cli[app]
        except KeyError:
            self._active_window_for_cli[app] = (
                self._last_active_window or self.windows[0]
            )
            return self.windows[0]

    def set_active_window(self, window: Window) -> None:
        app = get_app()

        previous = self.get_active_window()
        self._prev_active_window_for_cli[app] = previous
        self._active_window_for_cli[app] = window
        self._last_active_window = window

    def set_active_window_from_pane_id(self, pane_id: int) -> None:
        """
        Make the window with this pane ID the active Window.
        """
        for w in self.windows:
            for p in w.panes:
                if p.pane_id == pane_id:
                    self.set_active_window(w)

    def get_previous_active_window(self) -> Optional[Window]:
        "The previous active Window or None if unknown."
        app = get_app()

        try:
            return self._prev_active_window_for_cli[app]
        except KeyError:
            return None

    def get_window_by_index(self, index):
        "Return the Window with this index or None if not found."
        for w in self.windows:
            if w.index == index:
                return w

    def create_window(
        self, pane: Pane, name: Optional[str] = None, set_active: bool = True
    ) -> None:
        """
        Create a new window that contains just this pane.

        :param pane: The :class:`.Pane` instance to put in the new window.
        :param name: If given, name for the new window.
        :param set_active: When True, focus the new window.
        """
        # Take the first available index.
        taken_indexes = [w.index for w in self.windows]

        index = self.base_index
        while index in taken_indexes:
            index += 1

        # Create new window and add it.
        w = Window(index)
        w.add_pane(pane)
        self.windows.append(w)

        # Sort windows by index.
        self.windows = sorted(self.windows, key=lambda w: w.index)

        app = get_app_or_none()

        if app is not None and set_active:
            self.set_active_window(w)

        if name is not None:
            w.chosen_name = name

        assert w.active_pane == pane
        assert w._get_parent(pane)

    def move_window(self, window: Window, new_index: int) -> None:
        """
        Move window to a new index.
        """
        window.index = new_index

        # Sort windows by index.
        self.windows = sorted(self.windows, key=lambda w: w.index)

    def get_active_pane(self) -> Optional[Pane]:
        """
        The current :class:`.Pane` from the current window.
        """
        w = self.get_active_window()
        if w is not None:
            return w.active_pane
        return None

    def remove_pane(self, pane: Pane) -> None:
        """
        Remove a :class:`.Pane`. (Look in all windows.)
        """
        for w in self.windows:
            w.remove_pane(pane)

            # No panes left in this window?
            if not w.has_panes:
                # Focus next.
                for app, active_w in self._active_window_for_cli.items():
                    if w == active_w:
                        with set_app(app):
                            self.focus_next_window()

                self.windows.remove(w)

    def focus_previous_window(self) -> None:
        w = self.get_active_window()

        self.set_active_window(
            self.windows[(self.windows.index(w) - 1) % len(self.windows)]
        )

    def focus_next_window(self) -> None:
        w = self.get_active_window()

        self.set_active_window(
            self.windows[(self.windows.index(w) + 1) % len(self.windows)]
        )

    def break_pane(self, set_active: bool = True) -> None:
        """
        When the current window has multiple panes, remove the pane from this
        window and put it in a new window.

        :param set_active: When True, focus the new window.
        """
        w = self.get_active_window()

        if len(w.panes) > 1:
            pane = w.active_pane
            if pane is not None:
                self.get_active_window().remove_pane(pane)
                self.create_window(pane, set_active=set_active)

    def rotate_window(self, count: int = 1) -> None:
        "Rotate the panes in the active window."
        w = self.get_active_window()
        w.rotate(count=count)

    @property
    def has_panes(self) -> bool:
        "True when any of the windows has a :class:`.Pane`."
        for w in self.windows:
            if w.has_panes:
                return True
        return False
