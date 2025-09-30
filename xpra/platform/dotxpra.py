# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import glob
import socket
import errno
from collections.abc import Iterator, Sequence

from xpra.common import SocketState
from xpra.util.env import osexpand
from xpra.util.io import is_socket, umask_context, get_util_logger
from xpra.os_util import POSIX
from xpra.platform.dotxpra_common import PREFIX
from xpra.platform import platform_import

DISPLAY_PREFIX = ":"


def norm_makepath(dirpath: str, name: str) -> str:
    return os.path.join(dirpath, PREFIX + strip_display_prefix(name))


def strip_display_prefix(s: str) -> str:
    if s.startswith(DISPLAY_PREFIX):
        return s[len(DISPLAY_PREFIX):]
    return s


def debug(msg: str, *args, **kwargs) -> None:
    log = get_util_logger()
    log(msg, *args, **kwargs)


class DotXpra:
    def __init__(self, sockdir="", sockdirs: Sequence[str] = (), actual_username="", uid=0, gid=0):
        self.uid = uid or os.getuid()
        self.gid = gid or os.getgid()
        self.username = actual_username
        sockdirs = list(sockdirs)
        if not sockdir:
            if sockdirs:
                sockdir = sockdirs[0]
            else:
                sockdir = "undefined"
        elif sockdir not in sockdirs:
            sockdirs.insert(0, sockdir)
        self._sockdir = self.osexpand(sockdir)
        self._sockdirs: list[str] = [self.osexpand(x) for x in sockdirs]

    def osexpand(self, v: str) -> str:
        return osexpand(v, self.username, self.uid, self.gid)

    def __repr__(self):
        return f"DotXpra({self._sockdir}, {self._sockdirs} - {self.uid}:{self.gid} - {self.username})"

    def mksockdir(self, d: str, mode=0o700, uid=None, gid=None) -> None:
        if not d:
            return
        if not os.path.exists(d):
            if uid is None:
                uid = self.uid
            if gid is None:
                gid = self.gid
            parent = os.path.dirname(d)
            if parent and parent != "/" and not os.path.exists(parent):
                self.mksockdir(parent, mode, uid, gid)
            with umask_context(0):
                os.mkdir(d, mode)
            if uid != os.getuid() or gid != os.getgid():
                os.lchown(d, uid, gid)
        elif d != "/tmp":
            try:
                st_mode = os.stat(d).st_mode & 0o777
                if st_mode == 0o750 and d.startswith("/run/xpra"):
                    # this directory is for shared sockets, o750 is OK
                    return
                if st_mode != mode:
                    # perhaps this directory lives in $XDG_RUNTIME_DIR
                    # ie: /run/user/$UID/xpra or /run/user/$UID/xpra/100
                    xrd = os.environ.get("XDG_RUNTIME_DIR", "")
                    if xrd and d.startswith(xrd) and os.stat(xrd).st_mode & 0o777 == 0o700:
                        # $XDG_RUNTIME_DIR has the correct permissions
                        return
                    log = get_util_logger()
                    log.warn(f"Warning: socket directory {d!r}")
                    log.warn(f" expected permissions {mode:o} but found {st_mode:o}")
            except OSError:
                get_util_logger().error("Error: mksockdir%s", (d, mode, uid, gid), exc_info=True)

    def socket_expand(self, path: str) -> str:
        return osexpand(path, self.username, uid=self.uid, gid=self.gid)

    def norm_socket_paths(self, local_display_name: str) -> list[str]:
        return [norm_makepath(x, local_display_name) for x in self._sockdirs]

    def socket_path(self, local_display_name: str) -> str:
        return norm_makepath(self._sockdir, local_display_name)

    def get_server_state(self, sockpath: str, timeout=5) -> SocketState:
        saved_sockpath = sockpath
        if sockpath.startswith("@"):
            assert POSIX
            sockpath = "\0" + sockpath[1:]
        elif not os.path.exists(sockpath):
            return SocketState.DEAD
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(timeout)
        try:
            sock.connect(sockpath)
            return SocketState.LIVE
        except OSError as e:
            debug(f"get_server_state: connect({saved_sockpath!r})={e} (timeout={timeout}")
            err = e.args[0]
            if err == errno.EACCES:
                return SocketState.INACCESSIBLE
            if err == errno.ECONNREFUSED:
                if saved_sockpath.startswith("@"):
                    return SocketState.DEAD
                # could be the server is starting up
                debug("ECONNREFUSED")
                return SocketState.UNKNOWN
            if err == errno.EWOULDBLOCK:
                debug("EWOULDBLOCK")
                return SocketState.DEAD
            if err == errno.ENOENT:
                debug("ENOENT")
                return SocketState.DEAD
            return SocketState.UNKNOWN
        finally:
            try:
                sock.close()
            except OSError:
                debug("%s.close()", sock, exc_info=True)

    def displays(self, check_uid=-1, matching_state=None) -> list[str]:
        return list(set(v[1] for v in self.sockets(check_uid, matching_state)))

    def sockets(self, check_uid=-1, matching_state=None) -> list:
        # flatten the dictionary into a list:
        return list(set((v[0], v[1]) for details_values in
                        self.socket_details(check_uid, matching_state).values() for v in details_values))

    def socket_paths(self, check_uid=-1, matching_state=None, matching_display="") -> list[str]:
        paths = []
        for details in self.socket_details(check_uid, matching_state, matching_display).values():
            for _, _, socket_path in details:
                paths.append(socket_path)
        return paths

    def _unique_sock_dirs(self) -> Iterator[str]:
        dirs = []
        if self._sockdir != "undefined":
            dirs.append(self._sockdir)
        dirs += [x for x in self._sockdirs if x not in dirs]
        seen = set()
        for d in dirs:
            if d in seen or not d:
                continue
            seen.add(d)
            real_dir = os.path.realpath(osexpand(d))
            if real_dir != d:
                if real_dir in seen:
                    continue
                seen.add(real_dir)
            if not os.path.exists(real_dir):
                debug(f"socket_details: directory {real_dir!r} does not exist")
                continue
            yield real_dir

    def get_display_state(self, display: str) -> SocketState:
        state = None
        for d in self._unique_sock_dirs():
            # look for a 'socket' in the session directory
            # ie: /run/user/1000/xpra/10
            session_dir = os.path.join(d, strip_display_prefix(display))
            if os.path.exists(session_dir):
                # ie: /run/user/1000/xpra/10/socket
                sockpath = os.path.join(session_dir, "socket")
                if os.path.exists(sockpath):
                    state = self.is_socket_match(sockpath)
                    if state is SocketState.LIVE:
                        return state
            # when not using a session directory,
            # add the prefix to prevent clashes on NFS:
            # ie: "~/.xpra/HOSTNAME-10"
            sockpath = os.path.join(d, PREFIX + strip_display_prefix(display))
            state = self.is_socket_match(sockpath)
            if state is SocketState.LIVE:
                return state
        if state is None:
            return SocketState.DEAD
        return state

    # find the matching sockets, and return:
    # (state, local_display, sockpath) for each socket directory we probe
    def socket_details(self, check_uid=-1, matching_state=None, matching_display="") \
            -> dict[str, list[tuple[SocketState, str, str]]]:
        sd: dict[str, list[tuple[SocketState, str, str]]] = {}
        debug("socket_details%s sockdir=%s, sockdirs=%s",
              (check_uid, matching_state, matching_display), self._sockdir, self._sockdirs)

        def add_result(d: str, item: tuple[SocketState, str, str]) -> None:
            results: list[tuple[SocketState, str, str]] = sd.setdefault(d, [])
            if item not in results:
                results.append(item)

        def local(display: str) -> str:
            if display.startswith("wayland-"):
                return display
            return DISPLAY_PREFIX + strip_display_prefix(display)

        def add_session_dir(session_dir: str, display: str) -> None:
            if not os.path.exists(session_dir):
                debug("add_session_dir%s path does not exist", (session_dir, display))
                return
            if not os.path.isdir(session_dir):
                debug("add_session_dir%s not a directory", (session_dir, display))
                return
            # ie: /run/user/1000/xpra/10/socket
            sockpath = os.path.join(session_dir, "socket")
            if os.path.exists(sockpath):
                state = self.is_socket_match(sockpath, matching_state=matching_state)
                debug("add_session_dir(%s) state(%s)=%s", (session_dir, display), sockpath, state)
                if state:
                    add_result(session_dir, (state, local(display), sockpath))

        for d in self._unique_sock_dirs():
            # if we know the display name,
            # we know the corresponding session dir:
            if matching_display:
                session_dir = os.path.join(d, strip_display_prefix(matching_display))
                add_session_dir(session_dir, matching_display)
            else:
                # find all the directories that could be session directories:
                for p in os.listdir(d):
                    if p.startswith("wayland-"):
                        p = p[len("wayland-"):]
                    try:
                        int(p)
                    except ValueError:
                        continue
                    session_dir = os.path.join(d, p)
                    add_session_dir(session_dir, p)
            # ie: "~/.xpra/HOSTNAME-"
            base = os.path.join(d, PREFIX)
            if matching_display:
                dstr = strip_display_prefix(matching_display)
            else:
                dstr = "*"
            potential_sockets = glob.glob(base + dstr)
            for sockpath in sorted(potential_sockets):
                state = self.is_socket_match(sockpath, check_uid, matching_state)
                if state:
                    display = local(sockpath[len(base):])
                    add_result(d, (state, display, sockpath))
        return sd

    def is_socket_match(self, sockpath: str, check_uid=-1, matching_state=None) -> SocketState | None:
        if not is_socket(sockpath, check_uid):
            return None
        state = self.get_server_state(sockpath)
        if matching_state and state != matching_state:
            debug("is_socket_match%s state '%s' does not match", (sockpath, check_uid, matching_state), state)
            return None
        return state


# win32 re-defines DotXpra for namedpipes:
platform_import(globals(), "dotxpra", False,
                "DotXpra",
                "DISPLAY_PREFIX",
                "norm_makepath")
