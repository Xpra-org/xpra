# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal

from xpra.os_util import POSIX
from xpra.log import Logger


def load_pid(pid_file: str) -> int:
    if not pid_file or not os.path.exists(pid_file):
        return 0
    try:
        with open(pid_file, "rb") as f:
            return int(f.read().rstrip(b"\n\r"))
    except (ValueError, OSError) as e:
        log = Logger("util")
        log(f"load_pid({pid_file!r})", exc_info=True)
        log.error(f"Error reading pid from {pid_file!r}: {e}")
        return 0


def write_pid(pidfile: str, pid: int) -> int:
    if pid <= 0:
        raise ValueError(f"invalid pid value {pid}")
    log = Logger("util")
    pidstr = str(pid)
    try:
        with open(pidfile, "w", encoding="latin1") as f:
            if POSIX:
                os.fchmod(f.fileno(), 0o640)
            f.write(f"{pidstr}\n")
            f.flush()
            try:
                fd = f.fileno()
                inode = os.fstat(fd).st_ino
            except OSError as e:
                log("fstat", exc_info=True)
                log.error(f"Error accessing inode of {pidfile!r}: {e}")
                inode = 0
        space = "" if pid == os.getpid() else " "
        log.info(f"{space}wrote pid {pidstr} to {pidfile!r}")
        return inode
    except Exception as e:
        log(f"write_pid({pidfile}, {pid})", exc_info=True)
        log.info(f"Error: failed to write pid {pidstr} to {pidfile!r}")
        log.error(f" {e}")
        return 0


def write_pidfile(pidfile: str) -> int:
    return write_pid(pidfile, os.getpid())


def rm_pidfile(pidfile: str, inode: int) -> bool:
    # verify this is the right file!
    log = Logger("util")
    log("rm_pidfile(%s, %s)", pidfile, inode)
    if inode > 0:
        try:
            i = os.stat(pidfile).st_ino
            log("rm_pidfile: current inode=%i", i)
            if i != inode:
                log.warn(f"Warning: pidfile {pidfile!r} inode has changed")
                log.warn(f" was {inode}, now {i}")
                log.warn(" it would be unsafe to delete it")
                return False
        except OSError as e:
            log("rm_pidfile(%s, %s)", pidfile, inode, exc_info=True)
            log.warn(f"Warning: failed to stat pidfile {pidfile!r}")
            log.warn(f" {e!r}")
            return False
    try:
        os.unlink(pidfile)
        return True
    except OSError as e:
        log("rm_pidfile(%s, %s)", pidfile, inode, exc_info=True)
        log.warn(f"Warning: failed to remove pidfile {pidfile!r}")
        log.warn(f" {e!r}")
        return False


def kill_pid(pid: int, procname: str, sig=signal.SIGTERM) -> None:
    if pid:
        try:
            if pid and pid > 1 and pid != os.getpid():
                os.kill(pid, sig)
        except OSError as e:
            log = Logger("util")
            log.error(f"Error sending {sig!r} signal to {procname!r} pid {pid} {e}")
