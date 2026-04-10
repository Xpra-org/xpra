# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Display discovery and introspection utilities.
# Separated from xpra/scripts/main.py to allow unit testing without pulling in
# the full main module (GTK, GLib, server/client startup logic, etc.).

import os
import glob
import stat
import shlex
from subprocess import Popen, PIPE
from importlib.util import find_spec
from typing import Any, Final

from xpra.os_util import getuid, getgid, WIN32, OSX
from xpra.util.env import envint, osexpand, OSEnvContext
from xpra.util.io import is_socket, wait_for_socket, warn
from xpra.util.str_fn import sorted_nicely, csv
from xpra.util.pid import load_pid
from xpra.log import Logger
from xpra.scripts.config import InitExit

VERIFY_SOCKET_TIMEOUT: int = envint("XPRA_VERIFY_SOCKET_TIMEOUT", 1)

X11_SOCKET_DIR: Final[str] = "/tmp/.X11-unix"


def find_wayland_display_sockets(uid: int = getuid(), gid: int = getgid()) -> dict[str, str]:
    if WIN32 or OSX:
        return {}
    displays = {}

    def addwaylandsock(d: str, p: str) -> None:
        if os.path.isabs(p) and is_socket(p) and os.path.exists(p) and d not in displays:
            displays[d] = p

    from xpra.platform.posix.paths import get_runtime_dir
    xrd = osexpand(get_runtime_dir(), uid=uid, gid=gid)
    # try the one from the environment first:
    wd = os.environ.get("WAYLAND_DISPLAY", "")
    if wd:
        addwaylandsock(wd, wd)
        addwaylandsock(wd, os.path.join(xrd, wd))
    # now try a file glob:
    for x in glob.glob(os.path.join(xrd, "wayland-*")):
        wd = os.path.basename(x)
        addwaylandsock(wd, x)
    return displays


def find_x11_display_sockets(max_display_no: int = 0) -> dict[str, str]:
    displays: dict[str, str] = {}
    if not os.path.exists(X11_SOCKET_DIR):
        return displays
    if not os.path.isdir(X11_SOCKET_DIR):
        return displays
    for x in os.listdir(X11_SOCKET_DIR):
        if not x.startswith("X"):
            warn(f"path {x!r} does not look like an X11 socket")
            continue
        try:
            display_no = int(x[1:])
        except ValueError:
            warn(f"{x} does not parse as a display number")
            continue
        # arbitrary limit: we only shadow automatically displays below 10...
        if max_display_no and display_no > max_display_no:
            # warn("display no %i too high (max %i)" % (v, max_display_no))
            continue
        displays[f":{display_no}"] = os.path.join(X11_SOCKET_DIR, x)
    return displays


def stat_display_socket(socket_path: str, timeout=VERIFY_SOCKET_TIMEOUT) -> dict[str, Any]:
    try:
        if not os.path.exists(socket_path):
            return {}
        # check that this is a socket
        sstat = os.stat(socket_path)
        if not stat.S_ISSOCK(sstat.st_mode):
            warn(f"display path {socket_path!r} is not a socket!")
            return {}
        if timeout > 0 and not wait_for_socket(socket_path, timeout):
            # warn(f"Error trying to connect to {socket_path!r}: {e}")
            return {}
        return {
            "uid": sstat.st_uid,
            "gid": sstat.st_gid,
        }
    except OSError as e:
        warn(f"Warning: unexpected failure on {socket_path!r}: {e}")
    return {}


def guess_display(current_display, uid: int = getuid(), gid: int = getgid(), sessions_dir="") -> str:
    """
    try to find the one "real" active display
    either X11 or wayland displays used by real user sessions
    """
    MAX_X11_DISPLAY_NO = 10
    args = tuple(x for x in (uid, gid) if x is not None)
    all_displays: list[str] = []
    info_cache: dict[str, dict] = {}
    log = Logger("util")

    def dinfo(display) -> dict:
        if display not in info_cache:
            info = get_display_info(display, sessions_dir)
            log(f"display_info({display})={info}")
            info_cache[display] = info
        return info_cache.get(display, {})

    def islive(display) -> bool:
        return dinfo(display).get("state", "") == "LIVE"

    def notlivexpra(display) -> bool:
        return dinfo(display).get("state", "") != "LIVE" or dinfo(display).get("wmname").find("xpra") < 0

    while True:
        displays = list(find_displays(MAX_X11_DISPLAY_NO, *args).keys())
        log(f"find_displays({MAX_X11_DISPLAY_NO}, {args})={displays}")
        if current_display and current_display not in displays:
            displays.append(current_display)
        all_displays = all_displays or displays
        if len(displays) > 1:
            # remove displays that have a LIVE xpra session:
            displays = sorted(filter(notlivexpra, displays))
            log(f"notlivexpra: {displays}")
        if len(displays) > 1:
            displays = sorted(filter(islive, displays))
            log(f"live: {displays}")
        if len(displays) == 1:
            log(f"guess_display: {displays[0]}")
            return displays[0]
        if current_display in displays:
            log(f"using {current_display=}")
            return current_display
        # remove displays that are likely equivalent
        # ie: ":0" and ":0.0"
        noscreen = set(display.split(".")[0] for display in displays)
        if len(noscreen) == 1:
            return tuple(noscreen)[0]
        if not args:
            log(f"guess_display({current_display}, {uid}, {gid}, {sessions_dir}) {displays=}, {all_displays=}")
            if len(displays) > 1:
                raise InitExit(1, "too many live displays to choose from: " + csv(sorted_nicely(displays)))
            if all_displays:
                raise InitExit(1, "too many live displays to choose from: " + csv(sorted_nicely(all_displays)))
            raise InitExit(1, "could not detect any live displays")
        # remove last arg (gid then uid) and try again:
        args = args[:-1]


def find_displays(max_display_no=0, uid: int = getuid(), gid: int = getgid()) -> dict[str, Any]:
    if OSX or WIN32:
        return {"Main": {}}
    displays = {}
    if find_spec("xpra.x11"):
        displays = find_x11_display_sockets(max_display_no=max_display_no)
    # add wayland displays:
    displays.update(find_wayland_display_sockets(uid, gid))
    # now verify that the sockets are usable
    # and filter out by uid and gid if requested:
    display_info = {}
    for display, sockpath in displays.items():
        sstat = stat_display_socket(sockpath)
        if not sstat:
            continue
        sock_uid = sstat.get("uid", -1)
        sock_gid = sstat.get("gid", -1)
        if uid is not None and uid != sock_uid:
            continue
        if gid is not None and gid != sock_gid:
            continue
        display_info[display] = {"uid": sock_uid, "gid": sock_gid, "socket": sockpath}
    return display_info


def x11_display_socket(display: str) -> str:
    try:
        dno = int(display.lstrip(":"))
    except (ValueError, TypeError):
        return ""
    return os.path.join(X11_SOCKET_DIR, f"X{dno}")


def get_xvfb_pid(display: str, session_dir: str) -> int:
    def load_session_pid(pidfile: str) -> int:
        return load_pid(os.path.join(session_dir, pidfile))

    try:
        dno = int(display.lstrip(":"))
    except (ValueError, TypeError):
        return 0
    x11_socket_path = os.path.join(X11_SOCKET_DIR, f"X{dno}")
    r = stat_display_socket(x11_socket_path)
    if not r:
        return 0
    # so the X11 server may still be running
    return load_session_pid("xvfb.pid")


def get_display_inodes(*displays: str) -> dict[int, str]:
    inodes_display: dict[int, str] = {}
    for display in sorted_nicely(displays):
        # find the X11 server PID
        inodes = []
        sockpath = os.path.join(X11_SOCKET_DIR, "X%s" % display.lstrip(":"))
        PROC_NET_UNIX = "/proc/net/unix"
        with open(PROC_NET_UNIX, encoding="latin1") as proc_net_unix:
            for line in proc_net_unix:
                parts = line.rstrip("\n\r").split(" ")
                if not parts or len(parts) < 8:
                    continue
                if parts[-1] == sockpath or parts[-1] == "@%s" % sockpath:
                    try:
                        inode = int(parts[-2])
                    except ValueError:
                        continue
                    else:
                        inodes.append(inode)
                        inodes_display[inode] = display
    return inodes_display


def get_display_pids(*displays: str) -> dict[str, tuple[int, str]]:
    inodes_display = get_display_inodes(*displays)
    # now find the processes that own these inodes
    display_pids: dict[str, tuple[int, str]] = {}
    if not inodes_display:
        return display_pids
    for f in os.listdir("/proc"):
        try:
            pid = int(f)
        except ValueError:
            continue
        if pid == 1:
            # pid 1 is our friend, don't try to kill it
            continue
        procpath = os.path.join("/proc", f)
        if not os.path.isdir(procpath):
            continue
        fddir = os.path.join(procpath, "fd")
        if not os.path.exists(fddir) or not os.path.isdir(fddir):
            continue
        try:
            fds = os.listdir(fddir)
        except PermissionError:
            continue
        for fd in fds:
            fdpath = os.path.join(fddir, fd)
            if not os.path.islink(fdpath):
                continue
            try:
                ref = os.readlink(fdpath)
            except PermissionError:
                continue
            if not ref:
                continue
            for inode, display in inodes_display.items():
                if ref == "socket:[%i]" % inode:
                    cmd = ""
                    try:
                        proc_cmdline = os.path.join(procpath, "cmdline")
                        cmd = open(proc_cmdline, encoding="utf8").read()
                        cmd = shlex.join(cmd.split("\0"))
                    except OSError:
                        pass
                    display_pids[display] = (pid, cmd)
    return display_pids


def exec_wminfo(display) -> dict[str, str]:
    log = Logger("util")
    # get the window manager info by executing the "wminfo" subcommand:
    try:
        from xpra.platform.paths import get_xpra_command  # pylint: disable=import-outside-toplevel
        cmd = get_xpra_command() + ["wminfo"]
        env = os.environ.copy()
        env["DISPLAY"] = display
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, env=env)
        out = proc.communicate(None, 5)[0]
    except Exception as e:
        log(f"exec_wminfo({display})", exc_info=True)
        log.error(f"Error querying wminfo for display {display!r}: {e}")
        return {}
    # parse wminfo output:
    if proc.returncode != 0 or not out:
        return {}
    wminfo = {}
    for line in out.decode().splitlines():
        parts = line.split("=", 1)
        if len(parts) == 2:
            wminfo[parts[0]] = parts[1]
    return wminfo


def get_displays_info(dotxpra=None, display_names=None, sessions_dir="") -> dict[str, Any]:
    displays = get_displays(dotxpra, display_names)
    log = Logger("util")
    log(f"get_displays({display_names})={displays}")
    displays_info: dict[str, Any] = {}
    for display, descr in displays.items():
        # descr already contains the uid, gid
        displays_info[display] = descr
        # add wminfo:
        descr.update(get_display_info(display, sessions_dir))
    sn = sorted_nicely(displays_info.keys())
    return {k: displays_info[k] for k in sn}


def get_display_info(display, sessions_dir="") -> dict[str, Any]:
    display_info = {"state": "LIVE"}
    if OSX:
        return display_info
    if not display.startswith(":"):
        return {}
    return get_x11_display_info(display, sessions_dir)


def get_x11_display_info(display, sessions_dir="") -> dict[str, Any]:
    log = Logger("util")
    log(f"get_x11_display_info({display}, {sessions_dir})")
    state = ""
    display_info: dict[str, Any] = {}
    # try to load the sessions files:
    xauthority: str = ""
    if sessions_dir:
        try:
            from xpra.scripts.session import load_session_file, session_file_path, get_session_dir
        except ImportError as e:
            log(f"get_x11_display_info: {e}")
        else:
            uid = getuid()
            session_dir = get_session_dir("unknown", sessions_dir, display, uid)
            found_session_dir = os.path.exists(session_dir) and os.path.isdir(session_dir)
            log(f"{session_dir} : found={found_session_dir}")
            if found_session_dir:
                with OSEnvContext(XPRA_SESSION_DIR=session_dir):
                    log(f"get_x11_display_info({display}, {sessions_dir}) using session directory {session_dir}")
                    try:
                        xvfb_pid = load_pid(os.path.join(session_dir, "xvfb.pid"))
                        log(f"xvfb.pid({display})={xvfb_pid}")
                        if xvfb_pid and os.path.exists("/proc") and not os.path.exists(f"/proc/{xvfb_pid}"):
                            state = "UNKNOWN"
                    except (TypeError, ValueError):
                        xvfb_pid = 0
                    xauthority = load_session_file("xauthority").decode()
                    log(f"xauthority({display})={xauthority}")
                    pidfile = session_file_path("server.pid")
                    sockfile = session_file_path("socket")
                    if not os.path.exists(pidfile) and not os.path.exists(sockfile):
                        # looks like the server has exited
                        log(f"pidfile {pidfile!r} and {sockfile!r} not found")
                        state = "DEAD"
                    if xvfb_pid:
                        display_info["pid"] = xvfb_pid
    xauthority = xauthority or os.environ.get("XAUTHORITY", "")
    with OSEnvContext():
        if xauthority:
            os.environ["XAUTHORITY"] = xauthority
        log("get_x11_display_info: XAUTHORITY=%r" % xauthority)
        try:
            from xpra.x11.bindings.xwayland import isxwayland
        except ImportError:
            pass
        else:
            try:
                if isxwayland(display):
                    display_info["xwayland"] = True
            except Exception:
                pass
        state = state or "DEAD"
        wminfo = exec_wminfo(display)
        if wminfo:
            log(f"wminfo({display})={wminfo}")
            display_info.update(wminfo)
            pid = wminfo.get("xpra-server-pid")
            # seamless servers and non-xpra servers should have a window manager:
            if wminfo.get("_NET_SUPPORTING_WM_CHECK"):
                log("found a window manager")
                state = "LIVE"
            elif pid and os.path.exists("/proc"):
                log(f"xpra server pid={pid}")
                if os.path.exists(f"/proc/{pid}"):
                    state = "LIVE"
                else:
                    log(f"xpra server pid {pid} not found!")
                    state = "DEAD"
    display_info["state"] = state
    return display_info


def get_displays(dotxpra=None, display_names=None) -> dict[str, Any]:
    if OSX or WIN32:
        return {"Main": {}}
    log = Logger("util")
    # add ":" prefix to display name,
    # and remove xpra sessions
    xpra_sessions = {}
    if dotxpra:
        from xpra.scripts.main import get_xpra_sessions  # pylint: disable=import-outside-toplevel
        xpra_sessions = get_xpra_sessions(dotxpra)
    displays = find_displays()
    log(f"find_displays()={displays}")
    # filter out:
    displays = {
        d: i for d, i in tuple(displays.items()) if
        (d not in xpra_sessions) and (display_names is None or d in display_names)
    }
    log(f"get_displays({dotxpra}, {display_names})={displays} (xpra_sessions={xpra_sessions})")
    return displays
