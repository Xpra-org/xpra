#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import stat
import sys
from subprocess import PIPE, Popen
from tempfile import NamedTemporaryFile
from typing import Any
from collections.abc import Sequence

from xpra.common import noerr
from xpra.os_util import POSIX

util_logger = None


def get_util_logger():
    global util_logger
    if not util_logger:
        from xpra.log import Logger
        util_logger = Logger("network", "util")
    return util_logger


def load_binary_file(filename) -> bytes:
    if not filename or not os.path.exists(filename):
        return b""
    try:
        with open(filename, "rb") as f:
            return f.read()
    except Exception as e:  # pragma: no cover
        log = get_util_logger()
        log.debug(f"load_binary_file({filename})", exc_info=True)
        log.warn(f"Warning: failed to load {filename!r}")
        log.warn(f" {e}")
        return b""


def filedata_nocrlf(filename: str) -> bytes:
    v = load_binary_file(filename)
    if v is None:
        log = get_util_logger()
        log.error(f"failed to load {filename!r}")
        return b""
    return v.strip(b"\n\r")


def is_socket(sockpath: str, check_uid: int = -1) -> bool:
    try:
        s = os.stat(sockpath)
    except OSError as e:
        get_util_logger().debug(f"is_socket({sockpath}) path cannot be accessed: {e}")
        # socket cannot be accessed
        return False
    if not stat.S_ISSOCK(s.st_mode):
        return False
    if check_uid >= 0:
        logger = get_util_logger()
        if s.st_uid != check_uid:
            # socket uid does not match
            logger.debug(f"is_socket({sockpath}, {check_uid}) uid {s.st_uid} does not match {check_uid}")
            return False
        logger.debug(f"is_socket({sockpath}, {check_uid}) uid matches")
    return True


def wait_for_socket(sockpath: str, timeout=1) -> bool:
    assert POSIX, f"wait_for_socket cannot be used on {sys.platform!r}"
    import socket
    sock: socket.socket | None = None
    from time import monotonic, sleep
    now = monotonic()
    wait = timeout / 10 if not os.path.exists(sockpath) else 0
    while monotonic() - now < timeout:
        sleep(wait)
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout / 10)
            sock.connect(sockpath)
            return True
        except PermissionError:
            get_util_logger().debug(f"wait_for_socket({sockpath!r}, {timeout})", exc_info=True)
            return False
        except BlockingIOError:
            get_util_logger().debug(f"wait_for_socket({sockpath!r}, {timeout})", exc_info=True)
            wait = timeout / 10
        except OSError:
            get_util_logger().debug(f"wait_for_socket({sockpath!r}, {timeout})", exc_info=True)
        finally:
            if sock:
                sock.close()
    return False


def is_writable(path: str, uid: int, gid: int) -> bool:
    from xpra.os_util import getuid
    if uid == getuid() and os.access(path, os.W_OK):
        return True
    try:
        s = os.stat(path)
    except OSError as e:
        get_util_logger().debug(f"is_writable({path}) path cannot be accessed: {e}")
        # socket cannot be accessed
        return False
    mode = s.st_mode
    if s.st_uid == uid and mode & stat.S_IWUSR:
        # uid has write access
        return True
    if s.st_gid == gid and mode & stat.S_IWGRP:
        # gid has write access:
        return True
    return False


def stderr_print(msg: str = "") -> bool:
    stderr = sys.stderr
    if stderr:
        try:
            noerr(stderr.write, msg + "\n")
            noerr(stderr.flush)
            return True
        except (OSError, AttributeError):
            pass
    return False


def info(msg: str) -> None:
    if not stderr_print(msg) and POSIX:
        import syslog
        syslog.syslog(syslog.LOG_INFO, msg)


def warn(msg: str) -> None:
    if not stderr_print(msg) and POSIX:
        import syslog
        syslog.syslog(syslog.LOG_WARNING, msg)


def error(msg: str) -> None:
    if not stderr_print(msg) and POSIX:
        import syslog
        syslog.syslog(syslog.LOG_ERR, msg)


class CaptureStdErr:
    __slots__ = ("savedstderr", "tmp", "stderr")

    def __init__(self, *_args):
        self.savedstderr = None
        self.stderr = b""

    def __enter__(self):
        noerr(sys.stderr.flush)  # <--- important when redirecting to files
        self.savedstderr = os.dup(2)
        self.tmp = NamedTemporaryFile(prefix="stderr")
        fd = self.tmp.fileno()
        os.dup2(fd, 2)
        try:
            sys.stderr = os.fdopen(self.savedstderr, "w")
        except OSError as e:
            noerr(sys.stderr.write, f"failed to replace stderr: {e}\n")

    def __exit__(self, *_args):
        try:
            fd = self.tmp.fileno()
            os.lseek(fd, 0, 0)
            self.stderr = os.read(fd, 32768)
            self.tmp.close()
        except OSError as e:
            noerr(sys.stderr.write, f"failed to restore stderr: {e}\n")
        if self.savedstderr is not None:
            os.dup2(self.savedstderr, 2)


def path_permission_info(filename: str, ftype="") -> Sequence[str]:
    from xpra.os_util import POSIX
    if not POSIX:
        return ()
    pinfo = []
    try:
        stat_info = os.stat(filename)
        if not ftype:
            ftype = "file"
            if os.path.isdir(filename):
                ftype = "directory"
        operm = oct(stat.S_IMODE(stat_info.st_mode))
        pinfo.append(f"permissions on {ftype} {filename}: {operm}")
        # pylint: disable=import-outside-toplevel
        import pwd
        import grp
        user = pwd.getpwuid(stat_info.st_uid)[0]
        group = grp.getgrgid(stat_info.st_gid)[0]
        pinfo.append(f"ownership {user}:{group}")
    except Exception as e:
        pinfo.append(f"failed to query path information for {filename!r}: {e}")
    return tuple(pinfo)


def disable_stdout_buffering() -> None:
    import gc
    # Appending to gc.garbage is a way to stop an object from being
    # destroyed.  If the old sys.stdout is ever collected, it will
    # close() stdout, which is not good.
    gc.garbage.append(sys.stdout)
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)


def setbinarymode(fd: int) -> None:
    from xpra.os_util import WIN32
    if WIN32:
        # turn on binary mode:
        try:
            import msvcrt
            msvcrt.setmode(fd, os.O_BINARY)  # pylint: disable=no-member
        except OSError:
            get_util_logger().error("setting stdin to binary mode failed", exc_info=True)


def livefds() -> set[int]:
    live = set()
    try:
        maxfd = os.sysconf("SC_OPEN_MAX")
    except (ValueError, AttributeError):
        maxfd = 256
    for fd in range(0, maxfd):
        try:
            s = os.fstat(fd)
        except OSError:
            continue
        else:
            if s:
                live.add(fd)
    return live


def use_tty() -> bool:
    from xpra.util.env import envbool
    if envbool("XPRA_NOTTY", False):
        return False
    from xpra.platform.gui import use_stdin
    return use_stdin()


def use_gui_prompt() -> bool:
    from xpra.os_util import WIN32, OSX
    return WIN32 or OSX or not use_tty()


class umask_context:
    __slots__ = ("umask", "orig_umask")

    def __init__(self, umask):
        self.umask = umask

    def __enter__(self):
        self.orig_umask = os.umask(self.umask)

    def __exit__(self, *_args):
        os.umask(self.orig_umask)

    def __repr__(self):
        return f"umask_context({self.umask})"


def find_libexec_command(cmd: str) -> str:
    if cmd and os.path.isabs(cmd):
        return cmd
    if cmd:
        from xpra.platform.paths import get_resources_dir
        for prefix in ("/usr", get_resources_dir()):
            pcmd = prefix + "/libexec/xpra/" + cmd
            if os.path.exists(pcmd):
                return pcmd
    return ""


def find_lib_ldconfig(libname: str) -> str:
    libname = re.escape(libname)
    arch_map = {"x86_64": "libc6,x86-64"}
    arch = arch_map.get(os.uname()[4], "libc6")
    pattern = r'^\s+lib%s\.[^\s]+ \(%s(?:,.*?)?\) => (.*lib%s[^\s]+)' % (libname, arch, libname)
    # try to find ldconfig first, which may not be on the $PATH
    # (it isn't on Debian..)
    ldconfig = "ldconfig"
    for d in ("/sbin", "/usr/sbin"):
        t = os.path.join(d, "ldconfig")
        if os.path.exists(t):
            ldconfig = t
            break
    import subprocess
    p = subprocess.Popen(f"{ldconfig} -p", stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
    data = p.communicate()[0]
    libpath = re.search(pattern, data, re.MULTILINE)
    if libpath:
        return libpath.group(1)
    return ""


def find_lib(libname: str) -> str:
    # it would be better to rely on dlopen to find the paths,
    # but I cannot find a way of getting ctypes to tell us the path
    # it found the library in
    libpaths: list[str] = os.environ.get("LD_LIBRARY_PATH", "").split(":")
    if sys.platlibdir not in libpaths:
        libpaths.append(str(sys.platlibdir))
    for libpath in libpaths:
        if not libpath or not os.path.exists(libpath):
            continue
        libname_so = os.path.join(libpath, libname)
        if os.path.exists(libname_so):
            return libname_so
    return ""


def pollwait(process, timeout=5) -> int | None:
    from subprocess import TimeoutExpired
    try:
        return process.wait(timeout)
    except TimeoutExpired:
        return None


def find_in_PATH(command: str) -> str | None:
    path = os.environ.get("PATH", None)
    if not path:
        return None
    paths = path.split(os.pathsep)
    for p in paths:
        f = os.path.join(p, command)
        if os.path.isfile(f):
            return f
    return None


def which(command: str) -> str:
    try:
        from shutil import which
        return which(command) or ""
    except OSError:
        get_util_logger().debug(f"find_executable({command})", exc_info=True)
        return ""


def get_status_output(*args, **kwargs) -> tuple[int, Any, Any]:
    kwargs |= {
        "stdout": PIPE,
        "stderr": PIPE,
        "universal_newlines": True,
    }
    try:
        p = Popen(*args, **kwargs)
    except Exception as e:
        from xpra.log import Logger
        log = Logger("util")
        log.error(f"Error running {args},{kwargs}: {e}")
        return -1, "", ""
    stdout, stderr = p.communicate()
    return p.returncode, stdout, stderr


def get_proc_cmdline(pid: int) -> Sequence[str]:
    from xpra.os_util import POSIX
    if pid and POSIX:
        # try to find the command via /proc:
        proc_cmd_line = os.path.join("/proc", f"{pid}", "cmdline")
        if os.path.exists(proc_cmd_line):
            cmdline = load_binary_file(proc_cmd_line).rstrip(b"\0").split(b"\0")
            try:
                return tuple(x.decode() for x in cmdline)
            except UnicodeDecodeError:
                return tuple(x.decode("latin1") for x in cmdline)
    return ()


def osclose(*fds: int) -> None:
    for fd in fds:
        if not fd:
            continue
        try:
            os.close(fd)
        except OSError as e:
            log = get_util_logger()
            log("os.close(%s)", fd, exc_info=True)
            log.error("Error closing file download:")
            log.estr(e)
