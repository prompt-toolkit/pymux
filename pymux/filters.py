from __future__ import unicode_literals
from prompt_toolkit.filters import Filter

__all__ = (
    'HasPrefix',
    'WaitsForConfirmation',
    'InCommandMode',
    'WaitsForPrompt',
    'InScrollBuffer',
    'InScrollBufferNotSearching',
    'InScrollBufferSearching',
)


class HasPrefix(Filter):
    """
    When the prefix key (Usual C-b) has been pressed.
    """
    def __init__(self, pymux):
        self.pymux = pymux

    def __call__(self, cli):
        return self.pymux.get_client_state(cli).has_prefix


class WaitsForConfirmation(Filter):
    """
    Waiting for a yes/no key press.
    """
    def __init__(self, pymux):
        self.pymux = pymux

    def __call__(self, cli):
        return bool(self.pymux.get_client_state(cli).confirm_command)


class InCommandMode(Filter):
    """
    When ':' has been pressed.'
    """
    def __init__(self, pymux):
        self.pymux = pymux

    def __call__(self, cli):
        client_state = self.pymux.get_client_state(cli)
        return client_state.command_mode and not client_state.confirm_command


class WaitsForPrompt(Filter):
    """
    Waiting for input for a "command-prompt" command.
    """
    def __init__(self, pymux):
        self.pymux = pymux

    def __call__(self, cli):
        client_state = self.pymux.get_client_state(cli)
        return bool(client_state.prompt_command) and not client_state.confirm_command


def _confirm_or_prompt_or_command(pymux, cli):
    " True when we are waiting for a command, prompt or confirmation. "
    client_state = pymux.get_client_state(cli)
    if client_state.confirm_text or client_state.prompt_command or client_state.command_mode:
        return True


class InScrollBuffer(Filter):
    def __init__(self, pymux):
        self.pymux = pymux

    def __call__(self, cli):
        if _confirm_or_prompt_or_command(self.pymux, cli):
            return False

        pane = self.pymux.arrangement.get_active_pane(cli)
        return pane.display_scroll_buffer


class InScrollBufferNotSearching(Filter):
    def __init__(self, pymux):
        self.pymux = pymux

    def __call__(self, cli):
        if _confirm_or_prompt_or_command(self.pymux, cli):
            return False

        pane = self.pymux.arrangement.get_active_pane(cli)
        return pane.display_scroll_buffer and not pane.is_searching


class InScrollBufferSearching(Filter):
    def __init__(self, pymux):
        self.pymux = pymux

    def __call__(self, cli):
        if _confirm_or_prompt_or_command(self.pymux, cli):
            return False

        pane = self.pymux.arrangement.get_active_pane(cli)
        return pane.display_scroll_buffer and pane.is_searching
