# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Session/socket enumeration and list subcommand utilities.
# Separated from xpra/scripts/main.py to allow unit testing without pulling in
# the full main module (GTK, GLib, server/client startup logic, etc.).

import os
import sys
import time
from math import ceil
from time import monotonic
from subprocess import Popen, PIPE, TimeoutExpired
from collections.abc import Callable
from typing import Any

from xpra.exit_codes import ExitValue
from xpra.os_util import getuid, get_username_for_uid, WIN32
from xpra.util.io import warn
from xpra.util.str_fn import csv, sort_human
from xpra.util.env import envint
from xpra.net.constants import SocketState
from xpra.log import Logger
from xpra.scripts.config import InitException, InitInfo

# pylint: disable=import-outside-toplevel

WAIT_SERVER_TIMEOUT: int = envint("WAIT_SERVER_TIMEOUT", 90)
LIST_REPROBE_TIMEOUT: int = envint("XPRA_LIST_REPROBE_TIMEOUT", 10)


def identify_new_socket(proc: Popen | None, dotxpra,
                        existing_sockets: set[str], matching_display: str, new_server_uuid: str,
                        display_name: str, matching_uid: int = 0):
    log = Logger("server", "network")
    log("identify_new_socket%s",
        (proc, dotxpra, existing_sockets, matching_display, new_server_uuid, display_name, matching_uid))
    # wait until the new socket appears:
    start = monotonic()
    UUID_PREFIX = "uuid="
    DISPLAY_PREFIX = "display="
    from xpra.platform.paths import get_nodock_command
    while monotonic() - start < WAIT_SERVER_TIMEOUT and (proc is None or proc.poll() in (None, 0)):
        sockets = set(dotxpra.socket_paths(check_uid=matching_uid,
                                           matching_state=SocketState.LIVE,
                                           matching_display=matching_display))
        # sort because we prefer a socket in /run/* to one in /home/*:
        new_sockets = tuple(reversed(tuple(sockets - existing_sockets)))
        log(f"identify_new_socket new_sockets={new_sockets}")
        for socket_path in new_sockets:
            # verify that this is the right server:
            try:
                # we must use a subprocess to avoid messing things up - yuk
                cmd = get_nodock_command() + ["id", f"socket://{socket_path}"]
                p = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
                stdout = p.communicate()[0]
                if p.returncode != 0:
                    log("%r returned %i", cmd, p.returncode)
                    continue
                lines = stdout.splitlines()
                log(f"id({socket_path}): " + csv(lines))
                found = False
                display = matching_display
                for line in lines:
                    if line.startswith(UUID_PREFIX):
                        this_uuid = line[len(UUID_PREFIX):]
                        if this_uuid == new_server_uuid:
                            found = True
                    elif line.startswith(DISPLAY_PREFIX):
                        display = line[len(DISPLAY_PREFIX):]
                        if display and display == matching_display:
                            found = True
                if not found or not display:
                    warn(f"uuid prefix {UUID_PREFIX!r} or display value not found in `id` output for %r" % (socket_path, ))
                    continue
                log(f"identify_new_socket found match: path={socket_path!r}, display={display}")
                return socket_path, display
            except Exception as e:
                warn(f"error during server process detection: {e}")
        time.sleep(0.10)
    raise InitException("failed to identify the new server display!")


def may_cleanup_socket(state, display, sockpath, clean_states=(SocketState.DEAD,)) -> None:
    state_str = getattr(state, "value", str(state))
    sys.stdout.write(f"\t{state_str} session at {display}")
    if state in clean_states:
        try:
            stat_info = os.stat(sockpath)
            if stat_info.st_uid == getuid():
                os.unlink(sockpath)
                sys.stdout.write(" (cleaned up)")
        except OSError as e:
            sys.stdout.write(f" (delete failed: {e})")
    sys.stdout.write("\n")


def get_xpra_sessions(dotxpra, ignore_state=(SocketState.UNKNOWN,), matching_display=None,
                      query: bool = True) -> dict[str, Any]:
    results = dotxpra.socket_details(matching_display=matching_display)
    log = Logger("util")
    log("get_xpra_sessions%s socket_details=%s", (dotxpra, ignore_state, matching_display), results)
    sessions = {}
    for socket_dir, values in results.items():
        for state, display, sockpath in values:
            if state in ignore_state:
                continue
            session = {
                "state": state,
                "socket-dir": socket_dir,
                "socket-path": sockpath,
            }
            try:
                s = os.stat(sockpath)
            except OSError as e:
                log("'%s' path cannot be accessed: %s", sockpath, e)
            else:
                session.update(
                    {
                        "uid": s.st_uid,
                        "gid": s.st_gid,
                    }
                )
                username = get_username_for_uid(s.st_uid)
                if username:
                    session["username"] = username
            if query:
                try:
                    from xpra.platform.paths import get_xpra_command
                    cmd = get_xpra_command() + ["id", sockpath]
                    proc = Popen(cmd, stdout=PIPE, stderr=PIPE)
                    out = proc.communicate(None, timeout=1)[0]
                    if proc.returncode == 0:
                        for line in out.decode().splitlines():
                            parts = line.split("=", 1)
                            if len(parts) == 2:
                                session[parts[0]] = parts[1]
                except (OSError, TimeoutExpired):
                    pass
            sessions[display] = session
    return sessions


def run_list_sessions(args, options) -> ExitValue:
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(options.socket_dir, options.socket_dirs)
    if args:
        raise InitInfo("too many arguments for 'list-sessions' mode")
    sessions = get_xpra_sessions(dotxpra)
    print(f"Found {len(sessions)} xpra sessions:")
    for display, attrs in sessions.items():
        print("%4s    %-8s    %-12s    %-16s    %s" % (
            display,
            attrs.get("state"),
            attrs.get("session-type", ""),
            attrs.get("username") or attrs.get("uid") or "",
            attrs.get("session-name", "")))
    return 0


def run_list(error_cb: Callable, opts, extra_args, clean: bool = True) -> ExitValue:
    from xpra.scripts.common import no_gtk
    no_gtk()
    if extra_args:
        error_cb("too many arguments for `list` mode")
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs + opts.client_socket_dirs)
    results = dotxpra.socket_details()
    if not results:
        sys.stdout.write("No xpra sessions found\n")
        return 0
    sys.stdout.write("Found the following xpra sessions:\n")
    unknown = []
    for socket_dir, values in results.items():
        sys.stdout.write(f"{socket_dir}:\n")
        for state, display, sockpath in values:
            if clean:
                may_cleanup_socket(state, display, sockpath)
            if state is SocketState.UNKNOWN:
                unknown.append((socket_dir, display, sockpath))
    if clean:
        # now, re-probe the "unknown" ones:
        clean_sockets(dotxpra, unknown)
    return 0


def clean_sockets(dotxpra, sockets, timeout=LIST_REPROBE_TIMEOUT) -> None:
    # only clean the ones we own:
    reprobe = []
    for x in sockets:
        try:
            stat_info = os.stat(x[2])
            if stat_info.st_uid == getuid():
                reprobe.append(x)
        except OSError:
            pass
    if not reprobe:
        return
    sys.stdout.write("Re-probing unknown sessions in: %s\n" % csv(list(set(x[0] for x in sockets))))
    counter = 0
    unknown = list(reprobe)
    while unknown and counter < timeout:
        time.sleep(1)
        counter += 1
        probe_list = list(reprobe)
        unknown = []
        for v in probe_list:
            socket_dir, display, sockpath = v
            state = dotxpra.get_server_state(sockpath, 1)
            if state is SocketState.DEAD:
                may_cleanup_socket(state, display, sockpath)
            elif state is SocketState.UNKNOWN:
                unknown.append(v)
            else:
                sys.stdout.write(f"\t{state} session at {display} ({socket_dir})\n")
    # now cleanup those still unknown:
    clean_states = [SocketState.DEAD, SocketState.UNKNOWN]
    for state, display, sockpath in unknown:
        state = dotxpra.get_server_state(sockpath)
        if state == SocketState.UNKNOWN:
            try:
                mtime = os.stat(sockpath).st_mtime
                elapsed = ceil(time.time() - mtime)
                if elapsed <= 120:
                    sys.stdout.write(f"\t{state} session at {sockpath} ignored, modified {elapsed} seconds ago\n")
                    continue
            except OSError:
                pass
        may_cleanup_socket(state, display, sockpath, clean_states=clean_states)


def exec_and_parse(subcommand="id", display="") -> dict[str, str]:
    from xpra.platform.paths import get_nodock_command
    cmd = get_nodock_command() + [subcommand, display]
    d: dict[str, str] = {}
    try:
        env = os.environ.copy()
        env["XPRA_SKIP_UI"] = "1"
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, env=env, universal_newlines=True)
        out, err = proc.communicate()
        for line in (out or err).splitlines():
            try:
                k, v = line.split("=", 1)
                d[k] = v
            except ValueError:
                continue
    except Exception:
        pass
    return d


def run_list_windows(error_cb: Callable, opts, extra_args) -> ExitValue:
    from xpra.scripts.common import no_gtk
    no_gtk()
    if extra_args:
        error_cb("too many arguments for `list-windows` mode")
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
    displays = dotxpra.displays()
    if not displays:
        sys.stdout.write("No xpra sessions found\n")
        return 0

    sys.stdout.write("Display   Status    Name           Windows\n")
    for display in sort_human(displays):
        state = dotxpra.get_display_state(display)
        sys.stdout.write("%-10s%-10s" % (display, state))
        sys.stdout.flush()
        name = "?"
        if state == SocketState.LIVE:
            name = exec_and_parse("id", display).get("session-name", "?")
            if len(name) >= 15:
                name = name[:12] + ".. "
        sys.stdout.write("%-15s" % (name,))
        sys.stdout.flush()
        windows = "?"
        if state == SocketState.LIVE:
            dinfo = exec_and_parse("info", display)
            if dinfo:
                # first, find all the window properties:
                winfo: dict[str, dict[str, Any]] = {}
                for k, v in dinfo.items():
                    # ie: "windows.1.size-constraints.base-size" -> ["windows", "1", "size-constraints.base-size"]
                    parts = k.split(".", 2)
                    if parts[0] == "windows" and len(parts) == 3:
                        winfo.setdefault(parts[1], {})[parts[2]] = v
                # then find a property we can show for each:
                wstrs = []
                for props in winfo.values():
                    for prop in ("command", "class-instance", "title"):
                        wstr = props.get(prop, "?")
                        if wstr and prop == "class-instance":
                            wstr = wstr.split("',")[0][2:]
                        if wstr and wstr != "?":
                            break
                    wstrs.append(wstr)
                windows = csv(wstrs)
        sys.stdout.write(f"{windows}\n")
        sys.stdout.flush()
    return 0


def run_list_clients(error_cb: Callable, opts, extra_args) -> ExitValue:
    from xpra.scripts.common import no_gtk
    no_gtk()
    if extra_args:
        error_cb("too many arguments for `list-windows` mode")
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(sockdirs=opts.client_socket_dirs)
    results = dotxpra.socket_details()
    if not results:
        sys.stdout.write("No xpra client sessions found\n")
        return 0
    sys.stdout.write(f"Found the following {len(results)} xpra client sessions:\n")
    for socket_dir, values in results.items():
        for state, display, sockpath in values:
            sys.stdout.write(f"{sockpath}:\n")
            sys.stdout.write(f"\t{state} ")
            sys.stdout.flush()
            connpath = f"named-pipe://{sockpath}" if WIN32 else f"socket://{sockpath}"
            sinfo = exec_and_parse("info", connpath)
            stype = sinfo.get("session-type", "")
            disp = sinfo.get("display", "")
            endpoint = sinfo.get("endpoint", "")
            istr = stype
            if disp:
                istr += f" on {disp!r}"
            if endpoint:
                istr += f" connected to {endpoint!r}"
            sys.stdout.write(f"{istr}\n")
            sys.stdout.flush()
    return 0
