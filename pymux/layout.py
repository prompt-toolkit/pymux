# encoding: utf-8
"""
The layout engine. This builds the prompt_toolkit layout.
"""
from __future__ import unicode_literals

from prompt_toolkit.enums import IncrementalSearchDirection
from prompt_toolkit.filters import Condition, to_cli_filter
from prompt_toolkit.layout.containers import VSplit, HSplit, Window, FloatContainer, Float, ConditionalContainer, Container
from prompt_toolkit.layout.controls import TokenListControl, FillControl, BufferControl
from prompt_toolkit.layout.dimension import LayoutDimension
from prompt_toolkit.layout.dimension import LayoutDimension as D
from prompt_toolkit.layout.lexers import Lexer
from prompt_toolkit.layout.lexers import SimpleLexer
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import BeforeInput, AfterInput, AppendAutoSuggestion, Processor, Transformation, HighlightSearchProcessor, HighlightSelectionProcessor
from prompt_toolkit.layout.prompt import DefaultPrompt
from prompt_toolkit.layout.screen import Char
from prompt_toolkit.layout.screen import Point
from prompt_toolkit.layout.toolbars import TokenListToolbar
from prompt_toolkit.mouse_events import MouseEvent
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

    def preferred_height(self, cli, width, max_available_height):
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


def _draw_number(screen, x_offset, y_offset, number, token=Token.Clock,
                 transparent=False):
    " Write number at position. "
    fg = Char(' ', token)
    bg = Char(' ', Token)

    for y, row in enumerate(_numbers[number]):
        screen_row = screen.data_buffer[y + y_offset]
        for x, n in enumerate(row):
            if n == '#':
                screen_row[x + x_offset] = fg
            elif not transparent:
                screen_row[x + x_offset] = bg


class BigClock(Container):
    """
    Display a big clock.
    """
    WIDTH = 28
    HEIGHT = 5

    def __init__(self, on_click):
        assert callable(on_click)
        self.on_click = on_click

    def reset(self):
        pass

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        xpos = write_position.xpos
        ypos = write_position.ypos

        # Erase background.
        bg = Char(' ', Token)

        for y in range(ypos, self.HEIGHT + ypos):
            row = screen.data_buffer[y]
            for x in range(xpos, xpos + self.WIDTH):
                row[x] = bg

        # Display time.
        now = datetime.datetime.now()
        _draw_number(screen, xpos + 0, ypos, now.hour // 10)
        _draw_number(screen, xpos + 6, ypos, now.hour % 10)
        _draw_number(screen, xpos + 16, ypos, now.minute // 10)
        _draw_number(screen, xpos + 23, ypos, now.minute % 10)

        # Add a colon
        screen.data_buffer[ypos + 1][xpos + 13] = Char(' ', Token.Clock)
        screen.data_buffer[ypos + 3][xpos + 13] = Char(' ', Token.Clock)

        screen.width = self.WIDTH
        screen.height = self.HEIGHT

        mouse_handlers.set_mouse_handler_for_range(
            x_min=xpos,
            x_max=xpos + write_position.width,
            y_min=ypos,
            y_max=ypos + write_position.height,
            handler=self._mouse_handler)

    def _mouse_handler(self, cli, mouse_event):
        " Click callback. "
        if mouse_event.event_type == MouseEventTypes.MOUSE_UP:
            self.on_click(cli)
        else:
            return NotImplemented

    def preferred_width(self, cli, max_available_width):
        return D.exact(BigClock.WIDTH)

    def preferred_height(self, cli, width, max_available_height):
        return D.exact(BigClock.HEIGHT)

    def walk(self, cli):
        yield self


class PaneNumber(Container):
    """
    Number of panes, to be drawn in the middle of the pane.
    """
    WIDTH = 5
    HEIGHT = 5

    def __init__(self, pymux, arrangement_pane):
        self.pymux = pymux
        self.arrangement_pane = arrangement_pane

    def reset(self):
        pass

    def _get_index(self, cli):
        window = self.pymux.arrangement.get_active_window(cli)
        try:
            return window.get_pane_index(self.arrangement_pane)
        except ValueError:
            return 0

    def preferred_width(self, cli, max_available_width):
        # Enough to display all the digits.
        return LayoutDimension.exact(6 * len('%s' % self._get_index(cli)) - 1)

    def preferred_height(self, cli, width, max_available_height):
        return LayoutDimension.exact(self.HEIGHT)

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        if self.pymux.arrangement.get_active_pane(cli) == self.arrangement_pane:
            token = Token.PaneNumber.Focussed
        else:
            token = Token.PaneNumber

        for i, d in enumerate('%s' % (self._get_index(cli))):
            _draw_number(screen, write_position.xpos + i * 6, write_position.ypos,
                         int(d), token=token, transparent=True)

    def walk(self, cli):
        yield self


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
            def lex_document(self, cli, document):
                def get_line(lineno):
                    text = document.lines[lineno]
                    if focussed(cli):
                        return [(Token.Search.Focussed.Text, text)]
                    else:
                        return [(Token.Search.Text, text)]
                return get_line

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
                                input_processors=[
                                    AppendAutoSuggestion(),
                                    DefaultPrompt(lambda cli:[(Token.CommandLine.Prompt, ':')]),
                                    HighlightSelectionProcessor(),
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
                                input_processors=[
                                    BeforeInput(self._before_prompt_command_tokens),
                                    AppendAutoSuggestion(),
                                    HighlightSelectionProcessor(),
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

    def preferred_height(self, cli, width, max_available_height):
        body = self._get_body(cli)
        return body.preferred_height(cli, width, max_available_height)

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
    is_hsplit = not is_vsplit

    content = []

    def vertical_line():
        " Draw a vertical line between windows. (In case of a vsplit) "
        char = '│'
        content.append(HSplit([
                ConditionalContainer(
                    content=Window(
                        width=D.exact(1), height=D.exact(1),
                        content=FillControl(char, token=Token.TitleBar.Line)),
                    filter=Condition(lambda cli: pymux.enable_pane_status),
                ),
                Window(width=D.exact(1),
                       content=FillControl(char, token=Token.Line))
            ]))

    def horizontal_line():
        char = '─'
        content.append(
            ConditionalContainer(
                content=Window(height=D.exact(1),
                               content=FillControl(char, token=Token.Line)),
                filter=Condition(lambda cli: not pymux.enable_pane_status)),
        )

    for i, item in enumerate(split):
        if isinstance(item, (arrangement.VSplit, arrangement.HSplit)):
            content.append(_create_split(pymux, item))
        elif isinstance(item, arrangement.Pane):
            content.append(_create_container_for_process(pymux, item))
        else:
            raise TypeError('Got %r' % (item,))

        last_item = i == len(split) - 1
        if not last_item:
            if is_vsplit:
                vertical_line()
            elif is_hsplit:
                horizontal_line()

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
            last_item = i == len(split) - 1
            if is_vsplit and not last_item:
                result.append(D.exact(1))
            elif is_hsplit and not last_item:
                if pymux.enable_pane_status:
                    result.append(D.exact(0))
                else:
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
            if i % 2 == 0:
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

    def apply_transformation(self, cli, document, lineno, source_to_display, tokens):
        tokens = self.arrangement_pane.copy_get_tokens_for_line(lineno)
        return Transformation(tokens[:])

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
        arrangement_pane.clock_mode = False
        pymux.arrangement.get_active_window(cli).active_pane = arrangement_pane
        pymux.invalidate()

    def set_focus(cli):
        pymux.arrangement.get_active_window(cli).active_pane = arrangement_pane
        pymux.invalidate()

    clock_is_visible = Condition(lambda cli: arrangement_pane.clock_mode)
    pane_numbers_are_visible = Condition(lambda cli: pymux.display_pane_numbers)

    return TracePaneWritePosition(
        pymux, arrangement_pane,
        content=HSplit([
            # The title bar.
            ConditionalContainer(
                content=VSplit([
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
                filter=Condition(lambda cli: pymux.enable_pane_status)),
            # The pane content.
            FloatContainer(
                content=HSplit([
                    # The 'screen' of the pseudo terminal.
                    ConditionalContainer(
                        content=Vt100Window(
                            process=process,
                            has_focus=Condition(lambda cli: (
                                cli.current_buffer_name != COMMAND and
                                pymux.arrangement.get_active_pane(cli) == arrangement_pane)),
                            set_focus=set_focus,
                        ),
                        filter=~clock_is_visible & Condition(lambda cli: not arrangement_pane.display_scroll_buffer)),

                    # The copy/paste buffer.
                    ConditionalContainer(
                        content=Window(BufferControl(
                            buffer_name='pane-%i' % arrangement_pane.pane_id,
                            focus_on_click=True,
                            default_char=Char(token=Token),
                            preview_search=True,
                            get_search_state=lambda cli: arrangement_pane.search_state,
                            search_buffer_name='search-%i' % arrangement_pane.pane_id,
                            input_processors=[
                                _UseCopyTokenListProcessor(arrangement_pane),
                                HighlightSearchProcessor(
                                    search_buffer_name='search-%i' % arrangement_pane.pane_id,
                                    get_search_state=lambda cli: arrangement_pane.search_state,
                                    preview_search=True,
                                ),
                                HighlightSelectionProcessor(),
                            ],
                        ),
                            wrap_lines=False,
                        ),
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
                        # the boundaries are not clipped when the parent is smaller.)
                        content=VSplit([
                            Window(_FillControl(on_click)),
                            HSplit([
                                Window(_FillControl(on_click)),
                                BigClock(on_click),
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
                        content=PaneNumber(pymux, arrangement_pane),
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

    def preferred_height(self, cli, width, max_available_height):
        return self.content.preferred_height(cli, width, max_available_height)

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

            # Top line. (When we don't show the pane status bar.)
            if not self.pymux.enable_pane_status and wp.ypos >= 1:
                row = data_buffer[wp.ypos - 1]

                for x in range(wp.xpos, wp.xpos + wp.width):
                    row[x] = _border_horizontal

                # Left/right top.
                data_buffer[wp.ypos - 1][wp.xpos - 1] = _border_left_top
                data_buffer[wp.ypos - 1][wp.xpos + wp.width] = _border_right_top

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

        # Borders that are touching the pane status bar line.
        if self.pymux.enable_pane_status:
            row = data_buffer[ypos]
            row[xleft] = _focussed_border_left_top
            row[xright] = _focussed_border_right_top

        # Left and right border.
        if self.pymux.enable_pane_status:
            start_ypos = ypos + 1
        else:
            start_ypos = ypos

        for y in range(start_ypos, ypos + height):
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

        # Draw the top line.
        if not self.pymux.enable_pane_status and ypos >= 1:
            row = data_buffer[ypos - 1]

            for x in range(xpos, xpos + width):
                # Don't overwrite the titlebar of a pane below.
                if row[x].token == Token.Line:
                    row[x] = _focussed_border_horizontal

            # Bottom corners.
            row[xpos - 1] = _focussed_border_left_top
            row[xpos + width] = _focussed_border_right_top


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
                lambda wp: wp.ypos + wp.height + 2)
        # 2 in order to skip over the border. Only required when the
        # pane-status is not shown, but a border instead.


def focus_up(pymux, cli):
    " Move focus up. "
    _move_focus(pymux, cli,
                lambda wp: wp.xpos,
                lambda wp: wp.ypos - 2)


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


class Vt100Window(Container):
    """
    Container that holds the VT100 control.
    """
    def __init__(self, process, has_focus, set_focus):
        self.process = process
        self.has_focus = to_cli_filter(has_focus)
        self.set_focus = set_focus

    def reset(self):
        pass

    def preferred_width(self, cli, max_available_width):
        return LayoutDimension()

    def preferred_height(self, cli, width, max_available_height):
        return LayoutDimension()

    def write_to_screen(self, cli, screen, mouse_handlers, write_position):
        """
        Write window to screen. This renders the user control, the margins and
        copies everything over to the absolute position at the given screen.
        """
        # Set size of the screen.
        self.process.set_size(write_position.width, write_position.height)

        vertical_scroll = self.process.screen.line_offset

        # Render UserControl.
        temp_screen = self.process.screen.pt_screen

        # Write body to screen.
        self._copy_body(cli, temp_screen, screen, write_position, vertical_scroll,
                        write_position.width)

        # Set mouse handlers.
        def mouse_handler(cli, mouse_event):
            """ Wrapper around the mouse_handler of the `UIControl` that turns
            absolute coordinates into relative coordinates. """
            position = mouse_event.position

            # Call the mouse handler of the UIControl first.
            self._mouse_handler(
                cli, MouseEvent(
                    position=Point(x=position.x - write_position.xpos,
                                   y=position.y - write_position.ypos + vertical_scroll),
                    event_type=mouse_event.event_type))

        mouse_handlers.set_mouse_handler_for_range(
            x_min=write_position.xpos,
            x_max=write_position.xpos + write_position.width,
            y_min=write_position.ypos,
            y_max=write_position.ypos + write_position.height,
            handler=mouse_handler)

        # If reverse video is enabled for the whole screen.
        if self.process.screen.has_reverse_video:
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

    def _copy_body(self, cli, temp_screen, new_screen, write_position,
                   vertical_scroll, width):
        """
        Copy characters from the temp screen that we got from the `UIControl`
        to the real screen.
        """
        xpos = write_position.xpos
        ypos = write_position.ypos
        height = write_position.height

        temp_buffer = temp_screen.data_buffer
        new_buffer = new_screen.data_buffer
        temp_screen_height = temp_screen.height

        vertical_scroll = self.process.screen.line_offset
        y = 0

        # Now copy the region we need to the real screen.
        for y in range(0, height):
            # We keep local row variables. (Don't look up the row in the dict
            # for each iteration of the nested loop.)
            new_row = new_buffer[y + ypos]

            if y >= temp_screen_height and y >= write_position.height:
                # Break out of for loop when we pass after the last row of the
                # temp screen. (We use the 'y' position for calculation of new
                # screen's height.)
                break
            else:
                temp_row = temp_buffer[y + vertical_scroll]

                # Copy row content, except for transparent tokens.
                # (This is useful in case of floats.)
                for x in range(0, width):
                    new_row[x + xpos] = temp_row[x]

        if self.has_focus(cli):
            new_screen.cursor_position = Point(
                y=temp_screen.cursor_position.y + ypos - vertical_scroll,
                x=temp_screen.cursor_position.x + xpos)

            new_screen.show_cursor = temp_screen.show_cursor

        # Update height of the output screen. (new_screen.write_data is not
        # called, so the screen is not aware of its height.)
        new_screen.height = max(new_screen.height, ypos + y + 1)

    def _mouse_handler(self, cli, mouse_event):
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
                self.set_focus(cli)
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

    def walk(self, cli):
        # Only yield self. A window doesn't have children.
        yield self
