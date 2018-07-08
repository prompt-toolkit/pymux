"""
Initial configuration.
"""
from __future__ import unicode_literals

__all__ = (
    'STARTUP_COMMANDS'
)

STARTUP_COMMANDS = """
bind-key '"' split-window -v
bind-key % split-window -h
bind-key c new-window
bind-key Right select-pane -R
bind-key Left select-pane -L
bind-key Up select-pane -U
bind-key Down select-pane -D
bind-key C-l select-pane -R
bind-key C-h select-pane -L
bind-key C-j select-pane -D
bind-key C-k select-pane -U
bind-key ; last-pane
bind-key ! break-pane
bind-key d detach-client
bind-key t clock-mode
bind-key Space next-layout
bind-key C-z suspend-client

bind-key z resize-pane -Z
bind-key k resize-pane -U 2
bind-key j resize-pane -D 2
bind-key h resize-pane -L 2
bind-key l resize-pane -R 2
bind-key q display-panes
bind-key C-Up resize-pane -U 2
bind-key C-Down resize-pane -D 2
bind-key C-Left resize-pane -L 2
bind-key C-Right resize-pane -R 2
bind-key M-Up resize-pane -U 5
bind-key M-Down resize-pane -D 5
bind-key M-Left resize-pane -L 5
bind-key M-Right resize-pane -R 5

bind-key : command-prompt
bind-key 0 select-window -t :0
bind-key 1 select-window -t :1
bind-key 2 select-window -t :2
bind-key 3 select-window -t :3
bind-key 4 select-window -t :4
bind-key 5 select-window -t :5
bind-key 6 select-window -t :6
bind-key 7 select-window -t :7
bind-key 8 select-window -t :8
bind-key 9 select-window -t :9
bind-key n next-window
bind-key p previous-window
bind-key o select-pane -t :.+
bind-key { swap-pane -U
bind-key } swap-pane -D
bind-key x confirm-before -p "kill-pane #P?" kill-pane
bind-key & confirm-before -p "kill-window #W?" kill-window
bind-key C-o rotate-window
bind-key M-o rotate-window -D
bind-key C-b send-prefix
bind-key . command-prompt "move-window -t '%%'"
bind-key [ copy-mode
bind-key ] paste-buffer
bind-key ? list-keys
bind-key PPage copy-mode -u

# Layouts.
bind-key M-1 select-layout even-horizontal
bind-key M-2 select-layout even-vertical
bind-key M-3 select-layout main-horizontal
bind-key M-4 select-layout main-vertical
bind-key M-5 select-layout tiled

# Renaming stuff.
bind-key , command-prompt -I #W "rename-window '%%'"
#bind-key "'" command-prompt -I #W "rename-pane '%%'"
bind-key "'" command-prompt -p index "select-window -t ':%%'"
bind-key . command-prompt "move-window -t '%%'"
"""
