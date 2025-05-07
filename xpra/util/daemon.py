# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.os_util import POSIX
from xpra.platform.dotxpra import norm_makepath
from xpra.scripts.config import InitException
from xpra.util.env import shellsub
from xpra.util.io import get_util_logger


# Redirects stdin from /dev/null, and stdout and stderr to the file with the
# given file descriptor. Returns file objects pointing to the old stdout and
# stderr, which can be used to write a message about the redirection.

def open_log_file(logpath: str):
    """ renames the existing log file if it exists,
        then opens it for writing.
    """
    if os.path.exists(logpath):
        try:
            os.rename(logpath, logpath + ".old")
        except OSError:
            pass
    try:
        return os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    except OSError as e:
        raise InitException(f"cannot open log file {logpath!r}: {e}") from None


def select_log_file(log_dir: str, log_file: str, display_name: str) -> str:
    """ returns the log file path we should be using given the parameters,
        this may return a temporary logpath if display_name is not available.
    """
    if log_file:
        if os.path.isabs(log_file):
            logpath = log_file
        else:
            logpath = os.path.join(log_dir, log_file)
        v = shellsub(logpath, {"DISPLAY": display_name})
        if display_name or v == logpath:
            # we have 'display_name', or we just don't need it:
            return v
    if display_name:
        logpath = norm_makepath(log_dir, display_name) + ".log"
    else:
        logpath = os.path.join(log_dir, f"tmp_{os.getpid()}.log")
    return logpath


def redirect_std_to_log(logfd: int) -> tuple:
    # preserve old stdio in new filehandles for use (and subsequent closing)
    # by the caller
    old_fd_stdout = os.dup(1)
    old_fd_stderr = os.dup(2)
    stdout = os.fdopen(old_fd_stdout, "w", 1)
    stderr = os.fdopen(old_fd_stderr, "w", 1)

    # close the old stdio file handles
    os.close(0)
    os.close(1)
    os.close(2)

    # replace stdin with /dev/null
    fd0 = os.open("/dev/null", os.O_RDONLY)
    if fd0 != 0:
        os.dup2(fd0, 0)
        os.close(fd0)

    # replace standard stdout/stderr by the log file
    os.dup2(logfd, 1)
    os.dup2(logfd, 2)
    os.close(logfd)

    # Make these line-buffered:
    sys.stdout = os.fdopen(1, "w", 1)
    sys.stderr = os.fdopen(2, "w", 1)
    return stdout, stderr


def daemonize() -> None:
    os.chdir("/")
    if os.fork():
        os._exit(0)  # pylint: disable=protected-access
    os.setsid()
    if os.fork():
        os._exit(0)  # pylint: disable=protected-access


def setuidgid(uid: int, gid: int) -> None:
    if not POSIX:
        return
    log = get_util_logger()
    if os.getuid() != uid or os.getgid() != gid:
        # find the username for the given uid:
        from pwd import getpwuid
        try:
            username = getpwuid(uid).pw_name
        except KeyError:
            raise ValueError(f"uid {uid} not found") from None
        # set the groups:
        if hasattr(os, "initgroups"):  # python >= 2.7
            os.initgroups(username, gid)
        else:
            import grp
            groups = [gr.gr_gid for gr in grp.getgrall() if username in gr.gr_mem]
            os.setgroups(groups)
    # change uid and gid:
    try:
        if os.getgid() != gid:
            os.setgid(gid)
    except OSError as e:
        log.error(f"Error: cannot change gid to {gid}")
        if os.getgid() == 0:
            # don't run as root!
            raise
        log.estr(e)
        log.error(f" continuing with gid={os.getgid()}")
    try:
        if os.getuid() != uid:
            os.setuid(uid)
    except OSError as e:
        log.error(f"Error: cannot change uid to {uid}")
        if os.getuid() == 0:
            # don't run as root!
            raise
        log.estr(e)
        log.error(f" continuing with uid={os.getuid()}")
    log(f"new uid={os.getuid()}, gid={os.getgid()}")
