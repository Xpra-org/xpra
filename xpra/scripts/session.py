# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import glob
from shutil import rmtree

from xpra.os_util import POSIX, WIN32, getuid
from xpra.util.child_reaper import get_child_reaper
from xpra.util.env import osexpand, envbool
from xpra.util.io import load_binary_file

CLEAN_SESSION_FILES = envbool("XPRA_CLEAN_SESSION_FILES", True)


def get_session_dir(mode: str, sessions_dir: str, display_name: str, uid: int) -> str:
    sane_display_name = (display_name or "").lstrip(":")
    if WIN32:
        sane_display_name = sane_display_name.replace(":", "-")
    session_dir = osexpand(os.path.join(sessions_dir, sane_display_name), uid=uid)
    if not os.path.exists(session_dir):
        ROOT = POSIX and getuid() == 0
        ROOT_FALLBACK = ("/run/xpra", "/var/run/xpra", "/tmp")
        if ROOT and uid == 0 and not any(session_dir.startswith(x) for x in ROOT_FALLBACK):
            # there is usually no $XDG_RUNTIME_DIR when running as root
            # and even if there was, that's probably not a good path to use,
            # so try to find a more suitable directory we can use:
            for d in ROOT_FALLBACK:
                if os.path.exists(d):
                    if mode == "proxy" and sane_display_name.split(",")[0] == "14500":
                        # stash the system-wide proxy session files in a 'proxy' subdirectory:
                        return os.path.join(d, "proxy")
                    # otherwise just use the display as subdirectory name:
                    return os.path.join(d, sane_display_name)
    return session_dir


def make_session_dir(mode: str, sessions_dir: str, display_name: str, uid: int = 0, gid: int = 0) -> str:
    session_dir = get_session_dir(mode, sessions_dir, display_name, uid)
    if not os.path.exists(session_dir):
        try:
            os.makedirs(session_dir, 0o750, exist_ok=True)
        except OSError:
            import tempfile
            session_dir = osexpand(os.path.join(tempfile.gettempdir(), display_name.lstrip(":")))
            os.makedirs(session_dir, 0o750, exist_ok=True)
        ROOT = POSIX and getuid() == 0
        mismatch = ROOT and uid != 0 or gid != 0
        if mismatch and (session_dir.startswith("/run/user/") or session_dir.startswith("/run/xpra/")):
            os.lchown(session_dir, uid, gid)
    return session_dir


def session_file_path(filename: str) -> str:
    session_dir = os.environ.get("XPRA_SESSION_DIR", "")
    if session_dir is None:
        raise RuntimeError("'XPRA_SESSION_DIR' must be set to use this function")
    return os.path.join(session_dir, filename)


def load_session_file(filename: str) -> bytes:
    return load_binary_file(session_file_path(filename))


def save_session_file(filename: str, contents: str | bytes, uid: int = -1, gid: int = -1) -> str:
    if not os.environ.get("XPRA_SESSION_DIR"):
        return ""
    if not isinstance(contents, bytes):
        contents = str(contents).encode("utf8")
    assert contents
    path = session_file_path(filename)
    try:
        with open(path, "wb+") as f:
            if POSIX:
                os.fchmod(f.fileno(), 0o640)
                if getuid() == 0 and uid >= 0 and gid >= 0:
                    os.fchown(f.fileno(), uid, gid)
            f.write(contents)
    except OSError as e:
        from xpra.log import Logger
        log = Logger("server")
        log("save_session_file", exc_info=True)
        log.error(f"Error saving session file {path!r}")
        log.estr(e)
    return path


def rm_session_dir() -> None:
    session_dir = os.environ.get("XPRA_SESSION_DIR", "")
    if not session_dir or not os.path.exists(session_dir):
        return
    clean_session_dir(session_dir)


def pidexists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return os.path.exists(f"/proc/{pid}")
    except OSError:
        return False


def clean_session_dir(session_dir: str) -> bool:
    from xpra.log import Logger
    log = Logger("server")

    pidmap = clean_pidfiles(session_dir)
    if pidmap:
        log.error(f"Error: cannot remove the session directory {session_dir!r},")
        log.error(f" {len(pidmap)} commands are still running:")
        for fname, (pid, command) in pidmap.items():
            log.error(f"  * {command!r} with pid {pid} recorded in {fname!r}")
        return False

    try:
        session_files = os.listdir(session_dir)
    except OSError as e:
        log.error(f"Error listing session files in {session_dir}: {e}")
        return False

    # files we can remove safely:
    KNOWN_SERVER_FILES = [
        "cmdline", "config",
        "dbus.env", "dbus.pid",
        "server.env", "server.pid", "server.log",
        "socket", "xauthority", "Xorg.log", "xvfb.pid",
        "pulseaudio.pid",
        "ibus-daemon.pid",
        "background.png",
        "background.jpg",
    ]
    KNOWN_SERVER_DIRS = [
        "pulse",
        "ssh",
        "tmp",
    ]
    ALL_KNOWN = KNOWN_SERVER_FILES + KNOWN_SERVER_DIRS
    unknown_files = [x for x in session_files if x not in ALL_KNOWN]
    if unknown_files:
        from xpra.util.str_fn import csv
        log.error("Error: found some unexpected session files:")
        log.error(" " + csv(unknown_files))
        log.error(f" the session directory {session_dir!r} has not been removed")
        return False
    for x in session_files:
        pathname = os.path.join(session_dir, x)
        try:
            if x in KNOWN_SERVER_FILES:
                os.unlink(pathname)
            elif x in KNOWN_SERVER_DIRS:
                rmtree(pathname)
            else:
                log.error(f"Error: unexpected session file {x!r}")
                return False
        except OSError as e:
            log.error(f"Error removing {pathname!r}: {e}")
    try:
        os.rmdir(session_dir)
        log.info("removed session directory %r", session_dir)
    except OSError as rme:
        log.error(f"Error removing session directory {session_dir!r}: {rme}")
        return False
    return True


def clean_pidfiles(session_dir: str, kill=()) -> dict[str, tuple[int, str]]:
    # remove any session pid files for which the process has already terminated,
    # and returns the ones that are still alive.
    get_child_reaper().poll()
    try:
        session_files = os.listdir(session_dir)
    except OSError:
        session_files = ()
    pidmap: dict[str, tuple[int, str]] = {}

    def load_session_pid(pidfile: str) -> int:
        from xpra.util.pid import load_pid
        return load_pid(os.path.join(session_dir, pidfile))

    def trydelpidfile(pid: int, fname: str) -> None:
        if not pidexists(pid) or (pid == os.getpid() and fname == "server.pid"):
            try:
                os.unlink(os.path.join(session_dir, fname))
            except FileNotFoundError:
                pass
            session_files.remove(fname)
            pidmap.pop(fname, None)

    for fname in tuple(session_files):
        if fname.endswith(".pid"):
            pid = load_session_pid(fname)
            command = (load_binary_file(f"/proc/{pid}/cmdline") or b"").split(b"\0")[0].decode("latin1")
            command = command or fname.rsplit(".", 1)[0]
            pidmap[fname] = (pid, command)
            if fname in kill:
                from xpra.util.pid import kill_pid
                kill_pid(pid, command)
            trydelpidfile(pid, fname)

    if pidmap:
        get_child_reaper().poll()
        # wait a bit and try again:
        from time import sleep
        sleep(0.1)
        get_child_reaper().poll()
        for fname, (pid, command) in dict(pidmap).items():
            trydelpidfile(pid, fname)
    return pidmap


def clean_session_files(*filenames: str) -> None:
    if not CLEAN_SESSION_FILES:
        return
    for filename in filenames:
        path = session_file_path(filename)
        if filename.find("*") >= 0 or filename.find("?") >= 0:
            for p in glob.glob(path):
                clean_session_path(p)
        else:
            clean_session_path(path)


def clean_session_path(path: str) -> None:
    from xpra.log import Logger
    log = Logger("server")
    log(f"clean_session_path({path})")
    if not os.path.exists(path):
        return
    try:
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.unlink(path)
    except OSError as e:
        log(f"clean_session_path({path})", exc_info=True)
        log.error(f"Error removing session path {path}")
        log.estr(e)
        if os.path.isdir(path):
            files = os.listdir(path)
            if files:
                log.error(" this directory still contains some files:")
                for file in files:
                    finfo = repr(file)
                    try:
                        if os.path.islink(file):
                            finfo += " -> "+repr(os.readlink(file))
                    except OSError:
                        pass
                    log.error(f" {finfo}")
