# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.os_util import POSIX
from xpra.server.util import get_logger


def write_pid(pidfile: str, pid: int) -> int:
    if pid <= 0:
        raise ValueError(f"invalid pid value {pid}")
    log = get_logger()
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
    log = get_logger()
    log("cleanuppidfile(%s, %s)", pidfile, inode)
    if inode > 0:
        try:
            i = os.stat(pidfile).st_ino
            log("cleanuppidfile: current inode=%i", i)
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
