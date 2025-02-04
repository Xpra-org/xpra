# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import glob

from xpra.os_util import POSIX, getuid
from xpra.util.env import osexpand, envbool
from xpra.util.io import load_binary_file

CLEAN_SESSION_FILES = envbool("XPRA_CLEAN_SESSION_FILES", True)


def get_session_dir(mode: str, sessions_dir: str, display_name: str, uid: int) -> str:
    session_dir = osexpand(os.path.join(sessions_dir, display_name.lstrip(":")), uid=uid)
    if not os.path.exists(session_dir):
        ROOT = POSIX and getuid() == 0
        ROOT_FALLBACK = ("/run/xpra", "/var/run/xpra", "/tmp")
        if ROOT and uid == 0 and not any(session_dir.startswith(x) for x in ROOT_FALLBACK):
            # there is usually no $XDG_RUNTIME_DIR when running as root
            # and even if there was, that's probably not a good path to use,
            # so try to find a more suitable directory we can use:
            for d in ROOT_FALLBACK:
                if os.path.exists(d):
                    if mode == "proxy" and (display_name or "").lstrip(":").split(",")[0] == "14500":
                        # stash the system-wide proxy session files in a 'proxy' subdirectory:
                        return os.path.join(d, "proxy")
                    # otherwise just use the display as subdirectory name:
                    return os.path.join(d, (display_name or "").lstrip(":"))
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
    session_dir = os.environ.get("XPRA_SESSION_DIR")
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


def rm_session_dir(warn: bool = True) -> None:
    session_dir = os.environ.get("XPRA_SESSION_DIR")
    if not session_dir or not os.path.exists(session_dir):
        return
    from xpra.log import Logger
    log = Logger("server")
    try:
        session_files = os.listdir(session_dir)
    except OSError as e:
        log("os.listdir(%s)", session_dir, exc_info=True)
        if warn:
            log.error(f"Error: cannot access {session_dir!r}")
            log.estr(e)
        return
    if session_files:
        if warn:
            log.info(f"session directory {session_dir!r} was not removed")
            log.info(" because it still contains some files:")
            for f in session_files:
                extra = " (directory)" if os.path.isdir(os.path.join(session_dir, f)) else ""
                log.info(f" {f!r}{extra}")
        return
    try:
        os.rmdir(session_dir)
    except OSError as e:
        log = Logger("server")
        log(f"rmdir({session_dir})", exc_info=True)
        log.error(f"Error: failed to remove session directory {session_dir!r}")
        log.estr(e)


def clean_session_files(*filenames) -> None:
    if not CLEAN_SESSION_FILES:
        return
    for filename in filenames:
        path = session_file_path(filename)
        if filename.find("*") >= 0 or filename.find("?") >= 0:
            for p in glob.glob(path):
                clean_session_path(p)
        else:
            clean_session_path(path)
    rm_session_dir(False)


def clean_session_path(path) -> None:
    from xpra.log import Logger
    log = Logger("server")
    log(f"clean_session_path({path})")
    if os.path.exists(path):
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
