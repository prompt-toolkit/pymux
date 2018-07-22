"""
The color scheme.
"""
from __future__ import unicode_literals
from prompt_toolkit.styles import Style, Priority

__all__ = (
    'ui_style',
)


ui_style = Style.from_dict({
    'border':                         '#888888',
    'terminal.focused border':      'ansigreen bold',

    #'terminal titleba':            'bg:#aaaaaa #dddddd ',
    'terminal titlebar':            'bg:#888888 #ffffff',
#    'terminal titlebar paneindex':  'bg:#888888 #000000',

    'terminal.focused titlebar':   'bg:#448844 #ffffff',
    'terminal.focused titlebar name':   'bg:#88aa44 #ffffff',
    'terminal.focused titlebar paneindex':         'bg:#ff0000',

#    'titlebar title':               '',
#    'titlebar name':                '#ffffff noitalic',
#    'focused-terminal titlebar name':       'bg:#88aa44',
#    'titlebar.line':                '#444444',
#    'titlebar.line focused':       '#448844 noinherit',
#    'titlebar focused':            'bg:#5f875f #ffffff bold',
#    'titlebar.title focused':      '',
#    'titlebar.zoom':                'bg:#884400 #ffffff',
#    'titlebar paneindex':           '',
#    'titlebar.copymode':            'bg:#88aa88 #444444',
#    'titlebar.copymode.position':   '',

#    'focused-terminal titlebar.copymode':          'bg:#aaff44 #000000',
#    'titlebar.copymode.position': '#888888',

    'commandline':                  'bg:#4e4e4e #ffffff',
    'commandline.command':          'bold',
    'commandline.prompt':           'bold',
    #'statusbar':                    'noreverse bg:#448844 #000000',
    'statusbar':                    'noreverse bg:ansigreen #000000',
    'statusbar window':             '#ffffff',
    'statusbar window.current':     'bg:#44ff44 #000000',
    'auto-suggestion':               'bg:#4e5e4e #88aa88',
    'message':                      'bg:#bbee88 #222222',
    'background':                   '#888888',
    'clock':                        'bg:#88aa00',
    'panenumber':                   'bg:#888888',
    'panenumber focused':          'bg:#aa8800',
    'terminated':                   'bg:#aa0000 #ffffff',

    'confirmationtoolbar':          'bg:#880000 #ffffff',
    'confirmationtoolbar question': '',
    'confirmationtoolbar yesno':    'bg:#440000',

    'copy-mode-cursor-position':   'bg:ansiyellow ansiblack',

#    'search-toolbar':                       'bg:#88ff44 #444444',
    'search-toolbar.prompt':                'bg:#88ff44 #444444',
    'search-toolbar.text':                  'bg:#88ff44 #000000',
#    'search-toolbar focused':              'bg:#aaff44 #444444',
#    'search-toolbar.text focused':         'bold #000000',

    'search-match':                  '#000000 bg:#88aa88',
    'search-match.current':          '#000000 bg:#aaffaa underline',

    # Pop-up dialog. Ignore built-in style.
    'dialog':                        'noinherit',
    'dialog.body':                   'noinherit',
    'dialog frame':                  'noinherit',
    'dialog.body text-area':         'noinherit',
    'dialog.body text-area last-line': 'noinherit',

}, priority=Priority.MOST_PRECISE)
