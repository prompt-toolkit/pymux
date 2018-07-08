from __future__ import unicode_literals

from prompt_toolkit.output import ColorDepth
from abc import ABCMeta
from six import with_metaclass


__all__ = [
    'Client',
]


class Client(with_metaclass(ABCMeta, object)):
    def run_command(self, command, pane_id=None):
        """
        Ask the server to run this command.
        """

    def attach(self, detach_other_clients=False, color_depth=ColorDepth.DEPTH_8_BIT):
        """
        Attach client user interface.
        """
