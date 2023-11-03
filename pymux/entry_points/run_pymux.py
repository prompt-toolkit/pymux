#!/usr/bin/env python
"""
pymux: Pure Python terminal multiplexer.
Usage:
    pymux [(standalone|start-server|attach)] [-d]
          [--truecolor] [--ansicolor] [(-S <socket>)] [(-f <file>)]
          [(--log <logfile>)]
          [--] [<command>]
    pymux list-sessions
    pymux -h | --help
    pymux <command>

Options:
    standalone   : Run as a standalone process. (for debugging, detaching is
                   not possible.
    start-server : Run a server daemon that can be attached later on.
    attach       : Attach to a running session.

    -f           : Path to configuration file. By default: '~/.pymux.conf'.
    -S           : Unix socket path.
    -d           : Detach all other clients, when attaching.
    --log        : Logfile.
    --truecolor  : Render true color (24 bit) instead of 256 colors.
                   (Each client can set this separately.)
"""
import getpass
import logging
import os
import sys
import tempfile

import docopt
from prompt_toolkit.output import ColorDepth
from pymux.client import create_client, list_clients
from pymux.main import Pymux
from pymux.utils import daemonize

__all__ = ["run"]


def run() -> None:
    a = docopt.docopt(__doc__)
    socket_name = a["<socket>"] or os.environ.get("PYMUX")
    socket_name_from_env = not a["<socket>"] and os.environ.get("PYMUX")
    filename = a["<file>"]
    command = a["<command>"]
    true_color = a["--truecolor"]
    ansi_colors_only = a["--ansicolor"] or bool(
        os.environ.get("PROMPT_TOOLKIT_ANSI_COLORS_ONLY", False)
    )

    # Parse pane_id from socket_name. It looks like "socket_name,pane_id".
    if socket_name and "," in socket_name:
        socket_name, pane_id = socket_name.rsplit(",", 1)
    else:
        pane_id = None

    # Color depth.
    if ansi_colors_only:
        color_depth = ColorDepth.DEPTH_4_BIT
    elif true_color:
        color_depth = ColorDepth.DEPTH_24_BIT
    else:
        color_depth = ColorDepth.DEPTH_8_BIT

    # Expand socket name. (Make it possible to just accept numbers.)
    if socket_name and socket_name.isdigit():
        socket_name = "%s/pymux.sock.%s.%s" % (
            tempfile.gettempdir(),
            getpass.getuser(),
            socket_name,
        )

    # Configuration filename.
    default_config = os.path.abspath(os.path.expanduser("~/.pymux.conf"))
    if not filename and os.path.exists(default_config):
        filename = default_config

    if filename:
        filename = os.path.abspath(os.path.expanduser(filename))

    # Create 'Pymux'.
    mux = Pymux(source_file=filename, startup_command=command)

    # Setup logging.
    if a["<logfile>"]:
        logging.basicConfig(filename=a["<logfile>"], level=logging.DEBUG)

    if a["standalone"]:
        mux.run_standalone(color_depth=color_depth)

    elif a["list-sessions"] or a["<command>"] in ("ls", "list-sessions"):
        for c in list_clients():
            print(c.socket_name)

    elif a["start-server"]:
        if socket_name_from_env:
            _socket_from_env_warning()
            sys.exit(1)

        # Log to stdout.
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

        # Run server.
        socket_name = mux.listen_on_socket()
        try:
            mux.run_server()
        except KeyboardInterrupt:
            sys.exit(1)

    elif a["attach"]:
        if socket_name_from_env:
            _socket_from_env_warning()
            sys.exit(1)

        detach_other_clients = a["-d"]

        if socket_name:
            create_client(socket_name).attach(
                detach_other_clients=detach_other_clients, color_depth=color_depth
            )
        else:
            # Connect to the first server.
            for c in list_clients():
                c.attach(
                    detach_other_clients=detach_other_clients, color_depth=color_depth
                )
                break
            else:  # Nobreak.
                print("No pymux instance found.")
                sys.exit(1)

    elif a["<command>"] and socket_name:
        create_client(socket_name).run_command(a["<command>"], pane_id)

    elif not socket_name:
        # Run client/server combination.
        socket_name = mux.listen_on_socket(socket_name)
        pid = daemonize()

        if pid > 0:
            # Create window. It is important that this happens in the daemon,
            # because the parent of the process running inside should be this
            # daemon. (Otherwise the `waitpid` call won't work.)
            mux.run_server()
        else:
            create_client(socket_name).attach(color_depth=color_depth)

    else:
        if socket_name_from_env:
            _socket_from_env_warning()
            sys.exit(1)
        else:
            print("Invalid command.")
            sys.exit(1)


def _socket_from_env_warning() -> None:
    print("Please be careful nesting pymux sessions.")
    print("Unset PYMUX environment variable first.")


if __name__ == "__main__":
    run()
