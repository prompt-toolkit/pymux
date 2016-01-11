"""
Some utilities.
"""
from __future__ import unicode_literals
import array
import fcntl
import getpass
import os
import pwd
import sys
import termios

__all__ = (
    'pty_make_controlling_tty',
    'daemonize',
    'set_terminal_size',
    'nonblocking',
    'get_default_shell',
)


def pty_make_controlling_tty(tty_fd):
    """
    This makes the pseudo-terminal the controlling tty. This should be
    more portable than the pty.fork() function. Specifically, this should
    work on Solaris.

    Thanks to pexpect:
    http://pexpect.sourceforge.net/pexpect.html
    """
    child_name = os.ttyname(tty_fd)

    # Disconnect from controlling tty. Harmless if not already connected.
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
        if fd >= 0:
            os.close(fd)
    # which exception, shouldnt' we catch explicitly .. ?
    except:
        # Already disconnected. This happens if running inside cron.
        pass

    os.setsid()

    # Verify we are disconnected from controlling tty
    # by attempting to open it again.
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
        if fd >= 0:
            os.close(fd)
            raise Exception('Failed to disconnect from controlling '
                            'tty. It is still possible to open /dev/tty.')
    # which exception, shouldnt' we catch explicitly .. ?
    except:
        # Good! We are disconnected from a controlling tty.
        pass

    # Verify we can open child pty.
    fd = os.open(child_name, os.O_RDWR)
    if fd < 0:
        raise Exception("Could not open child pty, " + child_name)
    else:
        os.close(fd)

    # Verify we now have a controlling tty.
    if os.name != 'posix':
        # Skip this on BSD-like systems since it will break.
        fd = os.open("/dev/tty", os.O_WRONLY)
        if fd < 0:
            raise Exception("Could not open controlling tty, /dev/tty")
        else:
            os.close(fd)


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


def set_terminal_size(stdout_fileno, rows, cols):
    """
    Set terminal size.

    (This is also mainly for internal use. Setting the terminal size
    automatically happens when the window resizes. However, sometimes the
    process that created a pseudo terminal, and the process that's attached to
    the output window are not the same, e.g. in case of a telnet connection, or
    unix domain socket, and then we have to sync the sizes by hand.)
    """
    # Buffer for the C call
    # (The first parameter of 'array.array' needs to be 'str' on both Python 2
    # and Python 3.)
    buf = array.array(str('h'), [rows, cols, 0, 0])

    # Do: TIOCSWINSZ (Set)
    fcntl.ioctl(stdout_fileno, termios.TIOCSWINSZ, buf)


class nonblocking(object):
    """
    Make fd non blocking.
    """
    def __init__(self, fd):
        self.fd = fd

    def __enter__(self):
        self.orig_fl = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.orig_fl | os.O_NONBLOCK)

    def __exit__(self, *args):
        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.orig_fl)


def get_default_shell():
    """
    return the path to the default shell for the current user.
    """
    if 'SHELL' in os.environ:
        return os.environ['SHELL']
    else:
        username = getpass.getuser()
        shell = pwd.getpwnam(username).pw_shell
        return shell
