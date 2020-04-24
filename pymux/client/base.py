from abc import ABC

from prompt_toolkit.output import ColorDepth

__all__ = [
    "Client",
]


class Client(ABC):
    def run_command(self, command, pane_id=None):
        """
        Ask the server to run this command.
        """

    def attach(self, detach_other_clients=False, color_depth=ColorDepth.DEPTH_8_BIT):
        """
        Attach client user interface.
        """
