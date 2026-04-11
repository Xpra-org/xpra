# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Display/session selection utilities extracted from xpra.scripts.main.
Depends on sessions.py and DotXpra, but not on GTK.
"""

import os
import time
from subprocess import Popen, PIPE
from time import monotonic
from collections.abc import Sequence
from typing import Any

from xpra.exit_codes import ExitCode
from xpra.os_util import getuid, getgid, get_username_for_uid, WIN32
from xpra.net.constants import SocketState
from xpra.util.str_fn import bytestostr
from xpra.util.io import stderr_print
from xpra.util.env import envint
from xpra.scripts.config import InitException, InitExit, InitInfo
from xpra.scripts.parsing import parse_display_name
from xpra.scripts.display import X11_SOCKET_DIR
from xpra.log import Logger

CONNECT_TIMEOUT: int = envint("XPRA_CONNECT_TIMEOUT", 20)


def _DotXpra(*args, **kwargs):
    from xpra.platform.dotxpra import DotXpra
    return DotXpra(*args, **kwargs)


def _werr(*msg) -> None:
    for x in msg:
        stderr_print(str(x))


def find_session_by_name(opts, session_name: str) -> str:
    from xpra.platform.paths import get_nodock_command
    dotxpra = _DotXpra(opts.socket_dir, opts.socket_dirs)
    socket_paths = dotxpra.socket_paths(check_uid=getuid(), matching_state=SocketState.LIVE)
    if not socket_paths:
        return ""
    id_sessions = {}
    for socket_path in socket_paths:
        cmd = get_nodock_command() + ["id", f"socket://{socket_path}"]
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
        id_sessions[socket_path] = proc
    now = monotonic()
    while any(proc.poll() is None for proc in id_sessions.values()) and monotonic() - now < 10:
        time.sleep(0.5)
    session_uuid_to_path = {}
    for socket_path, proc in id_sessions.items():
        if proc.poll() == 0:
            out, err = proc.communicate()
            d = {}
            for line in bytestostr(out or err).splitlines():
                try:
                    k, v = line.split("=", 1)
                    d[k] = v
                except ValueError:
                    continue
            name = d.get("session-name")
            uuid = d.get("uuid")
            if name == session_name and uuid:
                session_uuid_to_path[uuid] = socket_path
    if not session_uuid_to_path:
        return ""
    if len(session_uuid_to_path) > 1:
        raise InitException(f"more than one session found matching {session_name!r}")
    socket_path = tuple(session_uuid_to_path.values())[0]
    return f"socket://{socket_path}"


def pick_vnc_display(error_cb, vnc_arg: str) -> dict[str, Any]:
    assert vnc_arg.startswith("vnc")
    display = vnc_arg.split("vnc", 1)[1]
    if display.lstrip(":"):
        try:
            display_no = int(display.lstrip(":"))
        except (ValueError, TypeError):
            raise ValueError(f"invalid vnc display number {display!r}") from None
        return {
            "display": f":{display_no}",
            "display_name": display,
            "host": "localhost",
            "port": 5900 + display_no,
            "local": True,
            "type": "tcp",
        }
    # can't identify vnc displays with xpra sockets
    # try the first N standard vnc ports:
    # (we could use threads to port scan more quickly)
    N = 100
    from xpra.net.socket_util import socket_connect
    for i in range(N):
        if not os.path.exists(f"{X11_SOCKET_DIR}/X{i}"):
            # no X11 socket, assume no VNC server
            continue
        port = 5900 + i
        sock = socket_connect("localhost", port, timeout=0.1)
        if sock:
            return {
                "type": "vnc",
                "local": True,
                "host": "localhost",
                "port": port,
                "display": f":{i}",
                "display_name": f":{i}",
            }
    error_cb("cannot find vnc displays yet")
    return {}


def pick_display(error_cb, opts, extra_args, cmdline: Sequence[str] = ()) -> dict[str, Any]:
    if len(extra_args) == 1 and extra_args[0].startswith("vnc"):
        vnc_display = pick_vnc_display(error_cb, extra_args[0])
        if vnc_display:
            return vnc_display
        # if not, then fall through and hope that the xpra server supports vnc:
    return do_pick_display(error_cb, opts, extra_args, cmdline)


def do_pick_display(error_cb, opts, extra_args, cmdline: Sequence[str] = ()) -> dict[str, Any]:
    dotxpra = _DotXpra(opts.socket_dir, opts.socket_dirs)
    if not extra_args:
        # Pick a default server
        dir_servers = dotxpra.socket_details()
        try:
            sockdir, display, sockpath = single_display_match(dir_servers, error_cb)
        except Exception:
            if getuid() == 0 and opts.system_proxy_socket:
                display = ":PROXY"
                sockdir = os.path.dirname(opts.system_proxy_socket)
                sockpath = opts.system_proxy_socket
            else:
                raise
        desc = {
            "local": True,
            "display": display,
            "display_name": display,
        }
        if WIN32:  # pragma: no cover
            desc.update(
                {
                    "type": "named-pipe",
                    "named-pipe": sockpath,
                }
            )
        else:
            desc.update(
                {
                    "type": "socket",
                    "socket_dir": sockdir,
                    "socket_path": sockpath,
                }
            )
        return desc
    if len(extra_args) == 1:
        return parse_display_name(error_cb, opts, extra_args[0], cmdline, find_session_by_name=find_session_by_name)
    error_cb(f"too many arguments to choose a display ({len(extra_args)}): {extra_args}")
    assert False


def single_display_match(dir_servers, error_cb,
                         nomatch="cannot find any live servers to connect to") -> tuple[str, str, str]:
    # ie: {"/tmp" : [LIVE, "desktop-10", "/tmp/desktop-10"]}
    # aggregate all the different locations:
    allservers = []
    noproxy = []
    for sockdir, servers in dir_servers.items():
        for state, display, path in servers:
            if state == SocketState.LIVE:
                allservers.append((sockdir, display, path))
                if not display.startswith(":proxy-"):
                    noproxy.append((sockdir, display, path))
    if not allservers:
        # maybe one is starting?
        for sockdir, servers in dir_servers.items():
            for state, display, path in servers:
                if state == SocketState.UNKNOWN:
                    allservers.append((sockdir, display, path))
                    if not display.startswith(":proxy-"):
                        noproxy.append((sockdir, display, path))
    if not allservers:
        error_cb(nomatch)
    if len(allservers) > 1:
        # maybe the same server is available under multiple paths
        displays = set(v[1] for v in allservers)
        if len(displays) == 1:
            # they all point to the same display, use the first one:
            allservers = allservers[:1]
    if len(allservers) > 1 and noproxy:
        # try to ignore proxy instances:
        displays = set(v[1] for v in noproxy)
        if len(displays) == 1:
            # they all point to the same display, use the first one:
            allservers = noproxy[:1]
    if len(allservers) > 1:
        error_cb("there are multiple servers running,\nplease specify.\nYou can see the list using `xpra list`")
    assert len(allservers) == 1
    sockdir, name, path = allservers[0]
    # ie: ("/tmp", "desktop-10", "/tmp/desktop-10")
    return sockdir, name, path


def connect_or_fail(display_desc, opts):
    from xpra.net.bytestreams import ConnectionClosedException
    from xpra.net.connect import connect_to
    try:
        return connect_to(display_desc, opts)
    except ConnectionClosedException as e:
        raise InitExit(ExitCode.CONNECTION_FAILED, str(e)) from None
    except InitException:
        raise
    except InitExit:
        raise
    except InitInfo:
        raise
    except Exception as e:
        Logger("network").debug(f"failed to connect to {display_desc}", exc_info=True)
        einfo = str(e) or type(e)
        raise InitExit(ExitCode.CONNECTION_FAILED, f"connection failed: {einfo}") from None


def get_sockpath(display_desc: dict[str, Any], error_cb, timeout=CONNECT_TIMEOUT) -> str:
    # if the path was specified, use that:
    sockpath = display_desc.get("socket_path")
    if sockpath:
        return sockpath
    # find the socket using the display:
    # if uid, gid or username are missing or not found on the local system,
    # use the uid, gid and username of the current user:
    uid = display_desc.get("uid", getuid())
    gid = display_desc.get("gid", getgid())
    username = display_desc.get("username", get_username_for_uid(uid))
    if not username:
        uid = getuid()
        gid = getgid()
        username = get_username_for_uid(uid)
    dotxpra = _DotXpra(
        display_desc.get("socket_dir"),
        display_desc.get("socket_dirs", ()),
        username,
        uid,
        gid,
    )
    display = display_desc["display"]

    def socket_details(state=SocketState.LIVE) -> dict:
        return dotxpra.socket_details(matching_state=state, matching_display=display)

    dir_servers = socket_details()
    if display and not dir_servers:
        state = dotxpra.get_display_state(display)
        if state in (SocketState.UNKNOWN, SocketState.DEAD) and timeout > 0:
            # found the socket for this specific display in UNKNOWN state,
            # or not found any sockets at all (DEAD),
            # this could be a server starting up,
            # so give it a bit of time:
            if state == SocketState.UNKNOWN:
                _werr(f"server socket for display {display} is in {SocketState.UNKNOWN} state")
            else:
                _werr(f"server socket for display {display} not found")
            _werr(f" waiting up to {timeout} seconds")
            start = monotonic()
            log = Logger("network")
            while monotonic() - start < timeout:
                state = dotxpra.get_display_state(display)
                log(f"get_display_state({display})={state}")
                if state in (SocketState.LIVE, SocketState.INACCESSIBLE):
                    # found a final state
                    break
                wait = 0.1 if state == SocketState.UNKNOWN else 1
                time.sleep(wait)
            dir_servers = socket_details()
    return single_display_match(dir_servers, error_cb,
                                nomatch=f"cannot find live server for display {display}")[-1]
