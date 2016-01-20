# encoding: utf-8
"""
The layout engine. This builds the prompt_toolkit layout.
"""
from __future__ import unicode_literals

from prompt_toolkit.enums import IncrementalSearchDirection
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout.containers import VSplit, HSplit, Window, FloatContainer, Float, ConditionalContainer, Container
from prompt_toolkit.layout.controls import TokenListControl, FillControl, UIControl, BufferControl
from prompt_toolkit.layout.dimension import LayoutDimension as D
from prompt_toolkit.layout.highlighters import SelectionHighlighter, SearchHighlighter
from prompt_toolkit.layout.lexers import Lexer
from prompt_toolkit.layout.lexers import SimpleLexer
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import BeforeInput, AfterInput, AppendAutoSuggestion, Processor, Transformation
from prompt_toolkit.layout.prompt import DefaultPrompt
from prompt_toolkit.layout.screen import Char, Screen
from prompt_toolkit.layout.toolbars import TokenListToolbar
from prompt_toolkit.mouse_events import MouseEventTypes
from prompt_toolkit.token import Token

from six.moves import range

import pymux.arrangement as arrangement
import datetime
import six
import weakref

from .enums import COMMAND, PROMPT
from .filters import WaitsForConfirmation, WaitsForPrompt, InCommandMode
from .format import format_pymux_string
from .log import logger
from .screen import DEFAULT_TOKEN

__all__ = (
    'LayoutManager',
)


class Justify:
    " Justify enum for the status bar. "
    LEFT = 'left'
    CENTER = 'center'
    RIGHT = 'right'

    _ALL = [LEFT, CENTER, RIGHT]


class Background(Container):
    """
    Generate the background of dots, which becomes visible when several clients
    are attached and not all of them have the same size.

    (This is implemented as a Container, rather than a UIControl wrapped in a
    Window, because it can be done very effecient this way.)
    """
    def reset(self):
        pass

    def preferred_width(self, cli, max_available_width):
        return D()

    def preferred_height(self, cli, width):
        return D()

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        " Fill the whole area of write_position with dots. "
        default_char = Char(' ', Token.Background)
        dot = Char('.', Token.Background)

        ypos = write_position.ypos
        xpos = write_position.xpos

        for y in range(ypos, ypos + write_position.height):
            row = screen.data_buffer[y]

            for x in range(xpos, xpos + write_position.width):
                row[x] = dot if (x + y) % 3 == 0 else default_char

    def walk(self, cli):
        return []


# Numbers for the clock and pane numbering.
_numbers = list(zip(*[  # (Transpose x/y.)
    ['#####', '    #', '#####', '#####', '#   #', '#####', '#####', '#####', '#####', '#####'],
    ['#   #', '    #', '    #', '    #', '#   #', '#    ', '#    ', '    #', '#   #', '#   #'],
    ['#   #', '    #', '#####', '#####', '#####', '#####', '#####', '    #', '#####', '#####'],
    ['#   #', '    #', '#    ', '    #', '    #', '    #', '#   #', '    #', '#   #', '    #'],
    ['#####', '    #', '#####', '#####', '    #', '#####', '#####', '    #', '#####', '#####'],
]))


def _draw_number(screen, x_offset, number, token=Token.Clock, default_token=Token):
    " Write number at position. "
    for y, row in enumerate(_numbers[number]):
        screen_row = screen.data_buffer[y]
        for x, n in enumerate(row):
            t = token if n == '#' else default_token
            screen_row[x + x_offset] = Char(' ', t)


class BigClock(UIControl):
    """
    Display a big clock.
    """
    WIDTH = 28
    HEIGHT = 5

    def __init__(self, on_click):
        assert callable(on_click)
        self.on_click = on_click

    def create_screen(self, cli, width, height):
        screen = Screen(initial_width=width)

        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                screen.data_buffer[y][x] = Char(' ', Token)

        # Display time.
        now = datetime.datetime.now()
        _draw_number(screen, 0, now.hour // 10)
        _draw_number(screen, 6, now.hour % 10)
        _draw_number(screen, 16, now.minute // 10)
        _draw_number(screen, 23, now.minute % 10)

        # Add a colon
        screen.data_buffer[1][13] = Char(' ', Token.Clock)
        screen.data_buffer[3][13] = Char(' ', Token.Clock)

        screen.width = self.WIDTH
        screen.height = self.HEIGHT
        return screen

    def mouse_handler(self, cli, mouse_event):
        " Click callback. "
        if mouse_event.event_type == MouseEventTypes.MOUSE_UP:
            self.on_click(cli)
        else:
            return NotImplemented


class PaneNumber(UIControl):
    """
    Number of panes, to be drawn in the middle of the pane.
    """
    WIDTH = 5
    HEIGHT = 5

    def __init__(self, pymux, arrangement_pane, on_click):
        self.pymux = pymux
        self.arrangement_pane = arrangement_pane
        self.on_click = on_click

    def _get_index(self, cli):
        window = self.pymux.arrangement.get_active_window(cli)
        try:
            return window.get_pane_index(self.arrangement_pane)
        except ValueError:
            return 0

    def preferred_width(self, cli, max_available_width):
        # Enough to display all the digits.
        return 6 * len('%s' % self._get_index(cli)) - 1

    def preferred_height(self, cli, width):
        return self.HEIGHT

    def create_screen(self, cli, width, height):
        screen = Screen(initial_width=width)

        if self.pymux.arrangement.get_active_pane(cli) == self.arrangement_pane:
            token = Token.PaneNumber.Focussed
        else:
            token = Token.PaneNumber

        for i, d in enumerate('%s' % (self._get_index(cli))):
            _draw_number(screen, i * 6, int(d),
                         token=token, default_token=Token.Transparent)

        return screen

    def mouse_handler(self, cli, mouse_event):
        " Click callback. "
        if mouse_event.event_type == MouseEventTypes.MOUSE_UP:
            self.on_click(cli)
        else:
            return NotImplemented


class PaneControl(UIControl):
    """
    User control that takes the Screen from a pymux pane/process.
    This also handles mouse support.
    """
    def __init__(self, pymux, pane):
        self.pane = pane
        self.process = pane.process
        self.pymux = pymux

    def create_screen(self, cli, width, height):
        process = self.process
        process.set_size(width, height)
        return process.screen.pt_screen

    def has_focus(self, cli):
        return (cli.current_buffer_name != COMMAND and
                self.pymux.arrangement.get_active_pane(cli) == self.pane)

    def mouse_handler(self, cli, mouse_event):
        """
        Handle mouse events in a pane. A click in a non-active pane will select
        it, one in an active pane, will send the mouse event to the application
        running inside it.
        """
        process = self.process
        x = mouse_event.position.x
        y = mouse_event.position.y

        # The containing Window translates coordinates to the absolute position
        # of the whole screen, but in this case, we need the relative
        # coordinates of the visible area.
        y -= self.process.screen.line_offset

        if not self.has_focus(cli):
            # Focus this process when the mouse has been clicked.
            if mouse_event.event_type == MouseEventTypes.MOUSE_UP:
                self.pymux.arrangement.get_active_window(cli).active_pane = self.pane
                self.pymux.invalidate()
        else:
            # Already focussed, send event to application when it requested
            # mouse support.
            if process.screen.sgr_mouse_support_enabled:
                # Xterm SGR mode.
                ev, m = {
                    MouseEventTypes.MOUSE_DOWN: ('0', 'M'),
                    MouseEventTypes.MOUSE_UP: ('0', 'm'),
                    MouseEventTypes.SCROLL_UP: ('64', 'M'),
                    MouseEventTypes.SCROLL_DOWN: ('65', 'M'),
                }.get(mouse_event.event_type)

                self.process.write_input(
                    '\x1b[<%s;%s;%s%s' % (ev, x + 1, y + 1, m))

            elif process.screen.urxvt_mouse_support_enabled:
                # Urxvt mode.
                ev = {
                    MouseEventTypes.MOUSE_DOWN: 32,
                    MouseEventTypes.MOUSE_UP: 35,
                    MouseEventTypes.SCROLL_UP: 96,
                    MouseEventTypes.SCROLL_DOWN: 97,
                }.get(mouse_event.event_type)

                self.process.write_input(
                    '\x1b[%s;%s;%sM' % (ev, x + 1, y + 1))

            elif process.screen.mouse_support_enabled:
                # Fall back to old mode.
                if x < 96 and y < 96:
                    ev = {
                            MouseEventTypes.MOUSE_DOWN: 32,
                            MouseEventTypes.MOUSE_UP: 35,
                            MouseEventTypes.SCROLL_UP: 96,
                            MouseEventTypes.SCROLL_DOWN: 97,
                    }.get(mouse_event.event_type)

                    self.process.write_input('\x1b[M%s%s%s' % (
                        six.unichr(ev),
                        six.unichr(x + 33),
                        six.unichr(y + 33)))


class PaneWindow(Window):
    """
    The window around a :class:`.PaneControl`.
    """
    def __init__(self, pymux, arrangement_pane, process):
        self._process = process
        super(PaneWindow, self).__init__(
            content=PaneControl(pymux, arrangement_pane),
            get_vertical_scroll=lambda window: process.screen.line_offset,
            allow_scroll_beyond_bottom=True,
        )

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        """
        Override, in order to implement reverse video efficiently.
        """
        super(PaneWindow, self).write_to_screen(cli, screen, mouse_handlers, write_position)

        # If reverse video is enabled for the whole screen.
        if self._process.screen.has_reverse_video:
            data_buffer = screen.data_buffer

            for y in range(write_position.ypos, write_position.ypos + write_position.height):
                row = data_buffer[y]

                for x in range(write_position.xpos, write_position.xpos + write_position.width):
                    char = row[x]
                    token = list(char.token or DEFAULT_TOKEN)

                    # The token looks like ('C', *attrs). Replace the value of the reverse flag.
                    if token and token[0] == 'C':
                        token[-1] = not token[-1]  # Invert reverse value.
                        row[x] = Char(char.char, tuple(token))


class SearchWindow(Window):
    """
    Display the search input in copy mode.
    """
    def __init__(self, pymux, arrangement_pane):
        assert isinstance(arrangement_pane, arrangement.Pane)

        def focussed(cli):
            return pymux.arrangement.get_active_pane(cli) == arrangement_pane

        def get_before_input(cli):
            if not arrangement_pane.is_searching:
                text = ''
            elif arrangement_pane.search_state.direction == IncrementalSearchDirection.BACKWARD:
                text = 'Search up: '
            else:
                text = 'Search down: '

            if focussed(cli):
                return [(Token.Search.Focussed, text)]
            else:
                return [(Token.Search, text)]

        def get_after_input(cli):
            if focussed(cli):
                return [(Token.Search.Focussed, ' ')]
            else:
                return []

        class SearchLexer(Lexer):
            " Color for the search string. "
            def get_tokens(self, cli, text):
                if focussed(cli):
                    return [(Token.Search.Focussed.Text, text)]
                else:
                    return [(Token.Search.Text, text)]

        super(SearchWindow, self).__init__(
            content=BufferControl(
                buffer_name='search-%i' % arrangement_pane.pane_id,
                input_processors=[BeforeInput(get_before_input), AfterInput(get_after_input)],
                lexer=SearchLexer(),
                default_char=Char(token=Token)),
            dont_extend_height=True)


class MessageToolbar(TokenListToolbar):
    """
    Pop-up (at the bottom) for showing error/status messages.
    """
    def __init__(self, pymux):
        def get_message(cli):
            # If there is a message to be shown for this client, show that.
            client_state = pymux.get_client_state(cli)

            if client_state.message:
                return client_state.message
            else:
                return ''

        def get_tokens(cli):
            message = get_message(cli)
            if message:
                return [
                    (Token.Message, message),
                    (Token.SetCursorPosition, ''),
                    (Token.Message, ' '),
                ]
            else:
                return []

        f = Condition(lambda cli: get_message(cli) is not None)

        super(MessageToolbar, self).__init__(get_tokens, filter=f, has_focus=f)


class LayoutManager(object):
    """
    The main layout class, that contains the whole Pymux layout.
    """
    def __init__(self, pymux):
        self.pymux = pymux
        self.layout = self._create_layout()

        # Keep track of render information.
        self.pane_write_positions = {}
        self.body_write_position = None

    def _create_select_window_handler(self, window):
        " Return a mouse handler that selects the given window when clicking. "
        def handler(cli, mouse_event):
            if mouse_event.event_type == MouseEventTypes.MOUSE_DOWN:
                self.pymux.arrangement.set_active_window(cli, window)
                self.pymux.invalidate()
            else:
                return NotImplemented  # Event not handled here.
        return handler

    def _get_status_tokens(self, cli):
        " The tokens for the status bar. "
        result = []

        # Display panes.
        for i, w in enumerate(self.pymux.arrangement.windows):
            if i > 0:
                result.append((Token.StatusBar, ' '))

            if w == self.pymux.arrangement.get_active_window(cli):
                token = Token.StatusBar.Window.Current
                format_str = self.pymux.window_status_current_format

            else:
                token = Token.StatusBar.Window
                format_str = self.pymux.window_status_format

            result.append((
                token,
                format_pymux_string(self.pymux, cli, format_str, window=w),
                self._create_select_window_handler(w)))

        return result

    def _get_status_left_tokens(self, cli):
        return [
            (Token.StatusBar,
             format_pymux_string(self.pymux, cli, self.pymux.status_left)),
        ]

    def _get_status_right_tokens(self, cli):
        return [
            (Token.StatusBar,
             format_pymux_string(self.pymux, cli, self.pymux.status_right)),
        ]

    def _status_align_right(self, cli):
        return self.pymux.status_justify == Justify.RIGHT

    def _status_align_center(self, cli):
        return self.pymux.status_justify == Justify.CENTER

    def _before_prompt_command_tokens(self, cli):
        client_state = self.pymux.get_client_state(cli)
        return [(Token.CommandLine.Prompt, '%s ' % (client_state.prompt_text, ))]

    def _create_layout(self):
        """
        Generate the main prompt_toolkit layout.
        """
        waits_for_confirmation = WaitsForConfirmation(self.pymux)
        waits_for_prompt = WaitsForPrompt(self.pymux)
        in_command_mode = InCommandMode(self.pymux)

        return FloatContainer(
            content=HSplit([
                # The main window.
                HighlightBorders(self, self.pymux, FloatContainer(
                    Background(),
                    floats=[
                        Float(get_width=lambda cli: self.pymux.get_window_size(cli).columns,
                              get_height=lambda cli: self.pymux.get_window_size(cli).rows,
                              content=TraceBodyWritePosition(self.pymux, DynamicBody(self.pymux)))
                    ])),
                # Status bar.
                ConditionalContainer(
                    content=VSplit([
                        # Left.
                        Window(
                            height=D.exact(1),
                            get_width=(lambda cli: D(max=self.pymux.status_left_length)),
                            dont_extend_width=True,
                            content=TokenListControl(
                                self._get_status_left_tokens,
                                default_char=Char(' ', Token.StatusBar))),
                        # List of windows in the middle.
                        Window(
                            height=D.exact(1),
                            content=TokenListControl(
                                self._get_status_tokens,
                                align_right=Condition(self._status_align_right),
                                align_center=Condition(self._status_align_center),
                                default_char=Char(' ', Token.StatusBar))),
                        # Right.
                        Window(
                            height=D.exact(1),
                            get_width=(lambda cli: D(max=self.pymux.status_right_length)),
                            dont_extend_width=True,
                            content=TokenListControl(
                                self._get_status_right_tokens,
                                align_right=True,
                                default_char=Char(' ', Token.StatusBar)))
                    ]),
                    filter=Condition(lambda cli: self.pymux.enable_status),
                )
            ]),
            floats=[
                Float(bottom=1, left=0, content=MessageToolbar(self.pymux)),
                Float(left=0, right=0, bottom=0, content=HSplit([
                    # Wait for confirmation toolbar.
                    ConditionalContainer(
                        content=Window(
                            height=D.exact(1),
                            content=ConfirmationToolbar(self.pymux),
                        ),
                        filter=waits_for_confirmation,
                    ),
                    # ':' prompt toolbar.
                    ConditionalContainer(
                        content=Window(
                            height=D(min=1),  # Can be more if the command is multiline.
                            dont_extend_height=True,
                            content=BufferControl(
                                buffer_name=COMMAND,
                                default_char=Char(' ', Token.CommandLine),
                                lexer=SimpleLexer(Token.CommandLine),
                                preview_search=True,
                                highlighters=[SelectionHighlighter()],
                                input_processors=[
                                    AppendAutoSuggestion(),
                                    DefaultPrompt(lambda cli:[(Token.CommandLine.Prompt, ':')]),
                                ])
                        ),
                        filter=in_command_mode,
                    ),
                    # Other command-prompt commands toolbar.
                    ConditionalContainer(
                        content=Window(
                            height=D.exact(1),
                            content=BufferControl(
                                buffer_name=PROMPT,
                                default_char=Char(' ', Token.CommandLine),
                                lexer=SimpleLexer(Token.CommandLine),
                                highlighters=[SelectionHighlighter()],
                                input_processors=[
                                    BeforeInput(self._before_prompt_command_tokens),
                                    AppendAutoSuggestion(),
                                ])
                        ),
                        filter=waits_for_prompt,
                    ),
                ])),
                Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=12)),
            ]
        )


class ConfirmationToolbar(TokenListControl):
    """
    Window that displays the yes/no confirmation dialog.
    """
    def __init__(self, pymux):
        token = Token.ConfirmationToolbar

        def get_tokens(cli):
            client_state = pymux.get_client_state(cli)
            return [
                (token.Question, ' '),
                (token.Question, format_pymux_string(
                    pymux, cli, client_state.confirm_text or '')),
                (token.Question, ' '),
                (token.YesNo, '  y/n'),
                (Token.SetCursorPosition, ''),
                (token.YesNo, '  '),
            ]

        super(ConfirmationToolbar, self).__init__(get_tokens, default_char=Char(' ', token))


class DynamicBody(Container):
    """
    The dynamic part, which is different for each CLI (for each client). It
    depends on which window/pane is active.

    This makes it possible to have just one main layout class, and
    automatically rebuild the parts that change if the windows/panes
    arrangement changes, without doing any synchronisation.
    """
    def __init__(self, pymux):
        self.pymux = pymux
        self._bodies_for_clis = weakref.WeakKeyDictionary()  # Maps CLI to (hash, Container)

    def _get_body(self, cli):
        " Return the Container object for the current CLI. "
        new_hash = self.pymux.arrangement.invalidation_hash(cli)

        # Return existing layout if nothing has changed to the arrangement.
        if cli in self._bodies_for_clis:
            existing_hash, container = self._bodies_for_clis[cli]
            if existing_hash == new_hash:
                return container

        # The layout changed. Build a new layout when the arrangement changed.
        new_layout = self._build_layout(cli)
        self._bodies_for_clis[cli] = (new_hash, new_layout)
        return new_layout

    def _build_layout(self, cli):
        " Rebuild a new Container object and return that. "
        logger.info('Rebuilding layout.')
        active_window = self.pymux.arrangement.get_active_window(cli)

        # When zoomed, only show the current pane, otherwise show all of them.
        if active_window.zoom:
            return _create_container_for_process(self.pymux, active_window.active_pane, zoom=True)
        else:
            return _create_split(self.pymux, self.pymux.arrangement.get_active_window(cli).root)

    def reset(self):
        for invalidation_hash, body in self._bodies_for_clis.values():
            body.reset()

    def preferred_width(self, cli, max_available_width):
        body = self._get_body(cli)
        return body.preferred_width(cli, max_available_width)

    def preferred_height(self, cli, width):
        body = self._get_body(cli)
        return body.preferred_height(cli, width)

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        body = self._get_body(cli)
        body.write_to_screen(cli, screen, mouse_handlers, write_position)

    def walk(self, cli):
        # (Required for prompt_toolkit.layout.utils.find_window_for_buffer_name.)
        body = self._get_body(cli)
        return body.walk(cli)


def _create_split(pymux, split):
    """
    Create a prompt_toolkit `Container` instance for the given pymux split.
    """
    assert isinstance(split, (arrangement.HSplit, arrangement.VSplit))

    is_vsplit = isinstance(split, arrangement.VSplit)

    content = []

    def vertical_line():
        " Draw a vertical line between windows. (In case of a vsplit) "
        char = '│'
        content.append(HSplit([
                Window(
                   width=D.exact(1), height=D.exact(1),
                   content=FillControl(char, token=Token.TitleBar.Line)),
                Window(width=D.exact(1),
                       content=FillControl(char, token=Token.Line))
            ]))

    for i, item in enumerate(split):
        if isinstance(item, (arrangement.VSplit, arrangement.HSplit)):
            content.append(_create_split(pymux, item))
        elif isinstance(item, arrangement.Pane):
            content.append(_create_container_for_process(pymux, item))
        else:
            raise TypeError('Got %r' % (item,))

        if is_vsplit and i != len(split) - 1:
            vertical_line()

    def get_average_weight():
        """ Calculate average weight of the children. Return 1 if none of
        the children has a weight specified yet. """
        weights = 0
        count = 0

        for i in split:
            if i in split.weights:
                weights += split.weights[i]
                count += 1

        if weights:
            return max(1, weights // count)
        else:
            return 1

    def get_dimensions(cli):
        """
        Return a list of LayoutDimension instances for this split.
        These dimensions will take the weight from the
        arrangement.VSplit/HSplit instances.
        """
        average_weight = get_average_weight()

        # Make sure that weight is distributed

        result = []
        for i, item in enumerate(split):
            result.append(D(weight=split.weights.get(item) or average_weight))

            # Add dimension for the vertical border.
            if is_vsplit and i != len(split) - 1:
                result.append(D.exact(1))

        return result

    def report_dimensions_callback(cli, dimensions):
        """
        When the layout is rendered, store the actial dimensions as
        weights in the arrangement.VSplit/HSplit classes.

        This is required because when a pane is resized with an increase of +1,
        we want to be sure that this corresponds exactly with one row or
        column. So, that updating weights corresponds exactly 1/1 to updating
        the size of the panes.
        """
        sizes = []
        for i, size in enumerate(dimensions):
            if not (is_vsplit and i % 2 != 0):
                sizes.append(size)

        for c, size in zip(split, sizes):
            split.weights[c] = size

    # Create prompt_toolkit Container.
    return_cls = VSplit if is_vsplit else HSplit

    return return_cls(content, get_dimensions=get_dimensions,
                      report_dimensions_callback=report_dimensions_callback)


class _UseCopyTokenListProcessor(Processor):
    """
    In order to allow highlighting of the copy region, we use a preprocessed
    list of (Token, text) tuples. This processor returns just that list for the
    given pane.
    """
    def __init__(self, arrangement_pane):
        self.arrangement_pane = arrangement_pane

    def apply_transformation(self, cli, document, tokens):
        return Transformation(document, self.arrangement_pane.copy_token_list[:])

    def invalidation_hash(self, cli, document):
        return document.text


def _create_container_for_process(pymux, arrangement_pane, zoom=False):
    """
    Create a `Container` with a titlebar for a process.
    """
    assert isinstance(arrangement_pane, arrangement.Pane)
    process = arrangement_pane.process

    def has_focus(cli):
        return pymux.arrangement.get_active_pane(cli) == arrangement_pane

    def get_titlebar_token(cli):
        return Token.TitleBar.Focussed if has_focus(cli) else Token.TitleBar

    def get_titlebar_name_token(cli):
        return Token.TitleBar.Name.Focussed if has_focus(cli) else Token.TitleBar.Name

    def get_title_tokens(cli):
        token = get_titlebar_token(cli)
        name_token = get_titlebar_name_token(cli)
        result = []

        if zoom:
            result.append((Token.TitleBar.Zoom, ' Z '))

        if process.is_terminated:
            result.append((Token.Terminated, ' Terminated '))

        # Scroll buffer info.
        if arrangement_pane.display_scroll_buffer:
            result.append((token.CopyMode, ' %s ' % arrangement_pane.scroll_buffer_title))

            # Cursor position.
            document = arrangement_pane.scroll_buffer.document
            result.append((token.CopyMode.Position, ' %i,%i ' % (
                document.cursor_position_row, document.cursor_position_col)))

        if arrangement_pane.name:
            result.append((name_token, ' %s ' % arrangement_pane.name))
            result.append((token, ' '))

        return result + [
            (token.Title, format_pymux_string(pymux, cli, ' #T ', pane=arrangement_pane))  # XXX: Make configurable.
        ]

    def get_pane_index(cli):
        token = get_titlebar_token(cli)

        try:
            w = pymux.arrangement.get_active_window(cli)
            index = w.get_pane_index(arrangement_pane)
        except ValueError:
            index = '/'

        return [(token.PaneIndex, '%3s ' % index)]

    def on_click(cli):
        " Click handler for the clock. When clicked, select this pane. "
        pymux.arrangement.get_active_window(cli).active_pane = arrangement_pane
        pymux.invalidate()

    clock_is_visible = Condition(lambda cli: arrangement_pane.clock_mode)
    pane_numbers_are_visible = Condition(lambda cli: pymux.display_pane_numbers)

    return TracePaneWritePosition(
        pymux, arrangement_pane,
        content=HSplit([
            # The title bar.
            VSplit([
                Window(
                    height=D.exact(1),
                    content=TokenListControl(
                        get_title_tokens,
                        get_default_char=lambda cli: Char(' ', get_titlebar_token(cli)))
                ),
                Window(
                    height=D.exact(1),
                    width=D.exact(4),
                    content=TokenListControl(get_pane_index)
                )
            ]),
            # The pane content.
            FloatContainer(
                content=HSplit([
                    # The 'screen' of the pseudo terminal.
                    ConditionalContainer(
                        content=PaneWindow(pymux, arrangement_pane, process),
                        filter=~clock_is_visible & Condition(lambda cli: not arrangement_pane.display_scroll_buffer)),

                    # The copy/paste buffer.
                    ConditionalContainer(
                        content=Window(BufferControl(
                            buffer_name='pane-%i' % arrangement_pane.pane_id,
                            wrap_lines=False,
                            focus_on_click=True,
                            default_char=Char(token=Token),
                            preview_search=True,
                            get_search_state=lambda cli: arrangement_pane.search_state,
                            search_buffer_name='search-%i' % arrangement_pane.pane_id,
                            input_processors=[_UseCopyTokenListProcessor(arrangement_pane)],
                            highlighters=[
                                SearchHighlighter(
                                   search_buffer_name='search-%i' % arrangement_pane.pane_id,
                                   get_search_state=lambda cli: arrangement_pane.search_state,
                                   preview_search=True),
                                SelectionHighlighter(),
                            ],
                        )),
                        filter=~clock_is_visible & Condition(lambda cli: arrangement_pane.display_scroll_buffer)
                    ),
                    # Search toolbar. (Displayed when this pane has the focus, and searching.)
                    ConditionalContainer(
                        content=SearchWindow(pymux, arrangement_pane),
                        filter=~clock_is_visible & Condition(lambda cli: arrangement_pane.is_searching)
                    ),
                    # The clock.
                    ConditionalContainer(
                        # Add a dummy VSplit/HSplit around the BigClock in order to center it.
                        # (Using a FloatContainer to do the centering doesn't work well, because
                        # the boundaries are not clipt when the parent is smaller.)
                        content=VSplit([
                            Window(_FillControl(on_click)),
                            HSplit([
                                Window(_FillControl(on_click)),
                                Window(BigClock(on_click), height=D.exact(BigClock.HEIGHT)),
                                Window(_FillControl(on_click)),
                            ]),
                            Window(_FillControl(on_click)),
                        ], get_dimensions=lambda cli: [None, D.exact(BigClock.WIDTH), None]),

                        filter=clock_is_visible,
                    ),
                ]),
                # Pane numbers. (Centered.)
                floats=[
                    Float(content=ConditionalContainer(
                        content=Window(PaneNumber(pymux, arrangement_pane, on_click)),
                        filter=pane_numbers_are_visible)),
                ]
            )
        ])
    )

class _FillControl(FillControl):
    """
    Extension to `FillControl` with click handlers.
    """
    def __init__(self, click_callback=None):
        self.click_callback = click_callback
        super(_FillControl, self).__init__()

    def mouse_handler(self, cli, mouse_event):
        " Call callback on click. "
        if mouse_event.event_type == MouseEventTypes.MOUSE_UP and self.click_callback:
            self.click_callback(cli)
        else:
            return NotImplemented


class _ContainerProxy(Container):
    def __init__(self, content):
        self.content = content

    def reset(self):
        self.content.reset()

    def preferred_width(self, cli, max_available_width):
        return self.content.preferred_width(cli, max_available_width)

    def preferred_height(self, cli, width):
        return self.content.preferred_height(cli, width)

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        self.content.write_to_screen(cli, screen, mouse_handlers, write_position)

    def walk(self, cli):
        return self.content.walk(cli)


_focussed_border_titlebar = Char('┃', Token.TitleBar.Line.Focussed)
_focussed_border_vertical = Char('┃', Token.Line.Focussed)
_focussed_border_horizontal = Char('━', Token.Line.Focussed)
_focussed_border_left_top = Char('┏', Token.Line.Focussed)
_focussed_border_right_top = Char('┓', Token.Line.Focussed)
_focussed_border_left_bottom = Char('┗', Token.Line.Focussed)
_focussed_border_right_bottom = Char('┛', Token.Line.Focussed)

_border_vertical = Char('│', Token.Line)
_border_horizontal = Char('─', Token.Line)
_border_left_bottom = Char('└', Token.Line)
_border_right_bottom = Char('┘', Token.Line)
_border_left_top = Char('┌', Token.Line)
_border_right_top = Char('┐', Token.Line)


class HighlightBorders(_ContainerProxy):
    """
    Highlight the active borders. Happens post rendering.

    (We highlight the active pane when the rendering of everything else is
    done, otherwise, rendering of panes on the right will replace the result of
    this one.
    """
    def __init__(self, layout_manager, pymux, content):
        _ContainerProxy.__init__(self, content)
        self.pymux = pymux
        self.layout_manager = layout_manager

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        # Clear previous list of pane coordinates.
        self.layout_manager.pane_write_positions = {}   # XXX: Should be for each CLI individually!!!!!
        self.layout_manager.body_write_position = None

        # Render everything.
        _ContainerProxy.write_to_screen(self, cli, screen, mouse_handlers, write_position)

        # When rendering is done. Draw borders and highlight the borders of the
        # active pane.
        self._draw_borders(screen, write_position)

        try:
            pane_wp = self.layout_manager.pane_write_positions[
                self.pymux.arrangement.get_active_pane(cli)]
        except KeyError:
            pass
        else:
            self._highlight_active_pane(screen, pane_wp, write_position)

    def _draw_borders(self, screen, write_position):
        """
        Draw borders around the whole window. (When there is space.)
        """
        data_buffer = screen.data_buffer

        if self.layout_manager.body_write_position:
            wp = self.layout_manager.body_write_position

            # Bottom line.
            if wp.ypos + wp.height < write_position.ypos + write_position.height:
                row = data_buffer[wp.ypos + wp.height]

                for x in range(wp.xpos, wp.xpos + wp.width):
                    row[x] = _border_horizontal

                # Left/right bottom.
                data_buffer[wp.ypos + wp.height][wp.xpos - 1] = _border_left_bottom
                data_buffer[wp.ypos + wp.height][wp.xpos + wp.width] = _border_right_bottom

            # Left and right line.
            for y in range(wp.ypos + 1, wp.ypos + wp.height):
                data_buffer[y][wp.xpos - 1] = _border_vertical
                data_buffer[y][wp.xpos + wp.width] = _border_vertical

            # Left/right top
            data_buffer[wp.ypos][wp.xpos - 1] = _border_left_top
            data_buffer[wp.ypos][wp.xpos + wp.width] = _border_right_top

    def _highlight_active_pane(self, screen, pane_wp, write_position):
        " Highlight the current, active pane. "
        data_buffer = screen.data_buffer
        xpos, ypos, width, height = pane_wp.xpos, pane_wp.ypos, pane_wp.width, pane_wp.height

        xleft = xpos - 1
        xright = xpos + width

        # First line.
        row = data_buffer[ypos]

        if row[xleft].token == Token.Line:
            row[xleft] = _focussed_border_left_top
        else:
            row[xleft] = _focussed_border_titlebar

        if row[xright].token == Token.Line:
            row[xright] = _focussed_border_right_top
        else:
            row[xright] = _focussed_border_titlebar

        # Every following line.
        for y in range(ypos + 1, ypos + height):
            row = data_buffer[y]
            row[xleft] = row[xright] = _focussed_border_vertical

        # Draw the bottom line. (Only when there is space.)
        if ypos + height < write_position.ypos + write_position.height:
            row = data_buffer[ypos + height]

            for x in range(xpos, xpos + width):
                # Don't overwrite the titlebar of a pane below.
                if row[x].token == Token.Line:
                    row[x] = _focussed_border_horizontal

            # Bottom corners.
            row[xpos - 1] = _focussed_border_left_bottom
            row[xpos + width] = _focussed_border_right_bottom


class TracePaneWritePosition(_ContainerProxy):
    " Trace the write position of this pane. "
    def __init__(self, pymux, arrangement_pane, content):
        _ContainerProxy.__init__(self, content)

        self.pymux = pymux
        self.arrangement_pane = arrangement_pane

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        _ContainerProxy.write_to_screen(self, cli, screen, mouse_handlers, write_position)

        self.pymux.layout_manager.pane_write_positions[self.arrangement_pane] = write_position


class TraceBodyWritePosition(_ContainerProxy):
    " Trace the write position of the whole body. "
    def __init__(self, pymux, content):
        _ContainerProxy.__init__(self, content)
        self.pymux = pymux

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        _ContainerProxy.write_to_screen(self, cli, screen, mouse_handlers, write_position)
        self.pymux.layout_manager.body_write_position = write_position


def focus_left(pymux, cli):
    " Move focus to the left. "
    _move_focus(pymux, cli,
                lambda wp: wp.xpos - 2,  # 2 in order to skip over the border.
                lambda wp: wp.ypos)


def focus_right(pymux, cli):
    " Move focus to the right. "
    _move_focus(pymux, cli,
                lambda wp: wp.xpos + wp.width + 1,
                lambda wp: wp.ypos)


def focus_down(pymux, cli):
    " Move focus down. "
    _move_focus(pymux, cli,
                lambda wp: wp.xpos,
                lambda wp: wp.ypos + wp.height + 1)


def focus_up(pymux, cli):
    " Move focus up. "
    _move_focus(pymux, cli,
                lambda wp: wp.xpos,
                lambda wp: wp.ypos - 1)


def _move_focus(pymux, cli, get_x, get_y):
    " Move focus of the active window. "
    window = pymux.arrangement.get_active_window(cli)

    try:
        write_pos = pymux.layout_manager.pane_write_positions[window.active_pane]
    except KeyError:
        pass
    else:
        x = get_x(write_pos)
        y = get_y(write_pos)

        # Look for the pane at this position.
        for pane, wp in pymux.layout_manager.pane_write_positions.items():
            if (wp.xpos <= x < wp.xpos + wp.width and
                    wp.ypos <= y < wp.ypos + wp.height):
                window.active_pane = pane
                return
