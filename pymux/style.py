"""
The color scheme.
"""
from __future__ import unicode_literals
from prompt_toolkit.styles import style_from_dict, Style, Attrs
from prompt_toolkit.styles.utils import split_token_in_parts, merge_attrs
from prompt_toolkit.token import Token

__all__ = (
    'PymuxStyle',
)


ui_style = {
    Token.Line:                         '#888888',
    Token.Line.Focussed:                '#448844',

    Token.TitleBar:                     'bg:#888888 #dddddd ',
    Token.TitleBar.Title:               '',
    Token.TitleBar.Name:                '#ffffff noitalic',
    Token.TitleBar.Name.Focussed:       'bg:#88aa44',
    Token.TitleBar.Line:                '#444444',
    Token.TitleBar.Line.Focussed:       '#448844 noinherit',
    Token.TitleBar.Focussed:            'bg:#5f875f #ffffff bold',
    Token.TitleBar.Focussed.Title:      '',
    Token.TitleBar.Zoom:                'bg:#884400 #ffffff',
    Token.TitleBar.PaneIndex:           '',
    Token.TitleBar.CopyMode:            'bg:#88aa88 #444444',
    Token.TitleBar.CopyMode.Position:   '',

    Token.TitleBar.Focussed.PaneIndex:         'bg:#88aa44 #ffffff',
    Token.TitleBar.Focussed.CopyMode:          'bg:#aaff44 #000000',
    Token.TitleBar.Focussed.CopyMode.Position: '#888888',

    Token.CommandLine:                  'bg:#4e4e4e #ffffff',
    Token.CommandLine.Command:          'bold',
    Token.CommandLine.Prompt:           'bold',
    Token.StatusBar:                    'bg:#444444 #ffffff',
    Token.StatusBar.Window:             'bg:#888888',
    Token.StatusBar.Window.Current:     '#88ff88 bold',
    Token.AutoSuggestion:               'bg:#4e5e4e #88aa88',
    Token.Message:                      'bg:#bbee88 #222222',
    Token.Background:                   '#888888',
    Token.Clock:                        'bg:#88aa00',
    Token.PaneNumber:                   'bg:#888888',
    Token.PaneNumber.Focussed:          'bg:#aa8800',
    Token.Terminated:                   'bg:#aa0000 #ffffff',

    Token.ConfirmationToolbar:          'bg:#880000 #ffffff',
    Token.ConfirmationToolbar.Question: '',
    Token.ConfirmationToolbar.YesNo:    'bg:#440000',

    Token.Search:                       'bg:#88aa88 #444444',
    Token.Search.Text:                  '',
    Token.Search.Focussed:              'bg:#aaff44 #444444',
    Token.Search.Focussed.Text:         'bold #000000',

    Token.SearchMatch:                  '#000000 bg:#88aa88',
    Token.SearchMatch.Current:          '#000000 bg:#aaffaa underline',


    # Completions menu.
    Token.Menu.Completions.Completion:         'bg:#88aa88 #222222',
    Token.Menu.Completions.Completion.Current: 'bg:#88cc88 #000000',
    Token.Menu.Completions.ProgressBar:        'bg:#889988',
    Token.Menu.Completions.ProgressButton:     'bg:#004400',
}


class PymuxStyle(Style):
    """
    The styling. It includes the UI style from above. But further, in order to
    proxy all the output from the processes, it interprets all tokens starting
    with ('C,) as tokens that describe their own style.
    """
    def __init__(self):
        self.ui_style = style_from_dict(ui_style)
        self._token_to_attrs_dict = None

    def get_attrs_for_token(self, token):
        result = []
        for part in split_token_in_parts(token):
            result.append(self._get_attrs_for_token(part))
        return merge_attrs(result)

    def _get_attrs_for_token(self, token):
        if token and token[0] == 'C':
            # Token starts with ('C',). Token describes its own style.
            c, fg, bg, bold, underline, italic, blink, reverse = token
            return Attrs(fg, bg, bold, underline, italic, blink, reverse)
        else:
            # Take styles from UI style.
            return self.ui_style.get_attrs_for_token(token)

    def invalidation_hash(self):
        return None
