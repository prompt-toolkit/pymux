"""
Some utilities.
"""
from __future__ import unicode_literals
from prompt_toolkit.utils import is_windows

import os
import sys

__all__ = (
    'daemonize',
    'nonblocking',
    'get_default_shell',
)


def daemonize(stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
    """
    Double fork-trick. For starting a posix daemon.

    This forks the current process into a daemon. The stdin, stdout, and stderr
    arguments are file names that will be opened and be used to replace the
    standard file descriptors in sys.stdin, sys.stdout, and sys.stderr. These
    arguments are optional and default to /dev/null. Note that stderr is opened
    unbuffered, so if it shares a file with stdout then interleaved output may
    not appear in the order that you expect.

    Thanks to:
    http://code.activestate.com/recipes/66012-fork-a-daemon-process-on-unix/
    """
    # Do first fork.
    try:
        pid = os.fork()
        if pid > 0:
            os.waitpid(pid, 0)
            return 0  # Return 0 from first parent.
    except OSError as e:
        sys.stderr.write("fork #1 failed: (%d) %s\n" % (e.errno, e.strerror))
        sys.exit(1)

    # Decouple from parent environment.
    os.chdir("/")
    os.umask(0)
    os.setsid()

    # Do second fork.
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)  # Exit second parent.
    except OSError as e:
        sys.stderr.write("fork #2 failed: (%d) %s\n" % (e.errno, e.strerror))
        sys.exit(1)

    # Now I am a daemon!

    # Redirect standard file descriptors.

        # NOTE: For debugging, you meight want to take these instead of /dev/null.
    # so = open('/tmp/log2', 'ab+')
    # se = open('/tmp/log2', 'ab+', 0)

    si = open(stdin, 'rb')
    so = open(stdout, 'ab+')
    se = open(stderr, 'ab+', 0)
    os.dup2(si.fileno(), sys.stdin.fileno())
    os.dup2(so.fileno(), sys.stdout.fileno())
    os.dup2(se.fileno(), sys.stderr.fileno())

    # Return 1 from daemon.
    return 1


class nonblocking(object):
    """
    Make fd non blocking.
    """
    def __init__(self, fd):
        self.fd = fd

    def __enter__(self):
        import fcntl
        self.orig_fl = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.orig_fl | os.O_NONBLOCK)

    def __exit__(self, *args):
        import fcntl
        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.orig_fl)


def get_default_shell():
    """
    return the path to the default shell for the current user.
    """
    if is_windows():
        return 'cmd.exe'
    else:
        import pwd
        import getpass

        if 'SHELL' in os.environ:
            return os.environ['SHELL']
        else:
            username = getpass.getuser()
            shell = pwd.getpwnam(username).pw_shell
            return shell
