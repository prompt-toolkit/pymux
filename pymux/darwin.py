from ctypes import cdll, pointer, c_uint, c_ubyte, c_ulong
from struct import pack

# Current Values as of El Capitan

# /usr/include/sys/sysctl.h
CTL_KERN = 1
KERN_PROC = 14
KERN_PROC_PID = 1
KERN_PROC_PGRP = 2

# /usr/include/sys/param.h
MAXCOMLEN = 16

# kinfo_proc (/usr/include/sys/sysctl.h)
#  \-> extern_proc (/usr/include/sys/proc.h)
P_COMM_OFFSET = 243

# Finding the type for PIDs was *interesting*
# pid_t in /usr/include/sys/types.h -> \
#   pid_t in /usr/include/sys/_types/_pid_t.h -> \
#   __darwin_pid_t -> /usr/include/sys/_types.h -> \
#   __int32_t

LIBC = None

def init():
    """
    initialize ctypes DLL link
    """
    global LIBC

    if LIBC is None:
        LIBC = cdll.LoadLibrary('libc.dylib')

def get_proc_info(pid):
    """
    use sysctl to retrieve process info
    """
    # ensure that we have the DLL loaded
    init()

    # request the length of the process data
    mib = (c_uint * 4)(CTL_KERN, KERN_PROC, KERN_PROC_PID, pid)
    oldlen = c_ulong()
    oldlenp = pointer(oldlen)
    r = LIBC.sysctl(mib, len(mib), None, oldlenp, None, 0)
    if r:
        return

    # request the process data
    reslen = oldlen.value
    old = (c_ubyte * reslen)()
    oldp = pointer(old)
    r = LIBC.sysctl(mib, len(mib), old, oldlenp, None, 0)
    if r:
        return
    #assert oldlen.value <= reslen

    return old[:reslen]


def get_proc_name(pid):
    """
    use sysctl to retrive process name
    """
    proc_kinfo = get_proc_info(pid)
    if not proc_kinfo:
        return

    p_comm_range = proc_kinfo[P_COMM_OFFSET:P_COMM_OFFSET+MAXCOMLEN+1]
    p_comm_raw = ''.join(chr(c) for c in p_comm_range)
    p_comm = p_comm_raw.split('\0', 1)[0]

    return p_comm

__all__ = ['get_proc_info', 'get_proc_name']

