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
from typing import Any
from collections.abc import Iterable

from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import getuid, get_username_for_uid, WIN32, OSX, POSIX
from xpra.util.io import warn, error, load_binary_file
from xpra.util.pid import load_pid, kill_pid
from xpra.util.str_fn import csv, sort_human
from xpra.util.env import envint, osexpand
from xpra.net.constants import SocketState
from xpra.log import Logger
from xpra.config import InitException, InitInfo, InitExit
from xpra.scripts.common import no_gtk
from xpra.scripts.display import (
    countdown, x11_display_socket, stat_display_socket, get_xvfb_pid,
    get_display_info, get_displays_info,
)
from xpra.scripts.picker import pick_display, get_sockpath

# pylint: disable=import-outside-toplevel

WAIT_SERVER_TIMEOUT: int = envint("WAIT_SERVER_TIMEOUT", 90)
LIST_REPROBE_TIMEOUT: int = envint("XPRA_LIST_REPROBE_TIMEOUT", 30)


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
            if existing := sessions.get(display):
                # the same session can be reachable via multiple sockets:
                existing.setdefault("socket-paths", []).append(sockpath)
                continue
            session = {
                "state": state,
                "socket-dir": socket_dir,
                "socket-path": sockpath,
                "socket-paths": [sockpath],
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
                if username := get_username_for_uid(s.st_uid):
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


def find_session_dir(sessions_dir: str, display: str, attrs: dict[str, Any]) -> str:
    # sockets named 'socket' live in the session directory, ie: /run/user/1000/xpra/10/socket
    for sockpath in attrs.get("socket-paths", ()):
        if os.path.basename(sockpath) == "socket":
            return os.path.dirname(sockpath)
    if not sessions_dir:
        return ""
    from xpra.scripts.session import get_session_dir
    session_dir = get_session_dir("list", sessions_dir, display, attrs.get("uid", getuid()))
    return session_dir if os.path.isdir(session_dir) else ""


def read_session_file(session_dir: str, filename: str) -> str:
    try:
        with open(os.path.join(session_dir, filename), encoding="utf8") as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def get_session_details(session_dir: str, attrs: dict[str, Any]) -> dict[str, str]:
    import shlex
    from xpra.util.io import get_proc_cmdline
    details = {
        "pid": attrs.get("pid", ""),
        "uuid": attrs.get("uuid", ""),
    }
    if session_dir:
        details["pid"] = read_session_file(session_dir, "server.pid") or details["pid"]
        details["uuid"] = read_session_file(session_dir, "server.uuid") or details["uuid"]
        if cmdline := read_session_file(session_dir, "cmdline"):
            details["command"] = shlex.join(cmdline.splitlines())
        xvfb_pid = read_session_file(session_dir, "xvfb.pid")
        if xvfb_pid.isdigit():
            if display_cmd := get_proc_cmdline(int(xvfb_pid)):
                details["display-command"] = shlex.join(display_cmd)
    return details


def run_list_sessions(options, _args) -> ExitValue:
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(options.socket_dirs)
    sessions = get_xpra_sessions(dotxpra)
    print(f"Found {len(sessions)} xpra sessions:")
    indent = " " * 8
    for display, attrs in sessions.items():
        print("%4s    %-8s    %-12s    %-16s    %s" % (
            display,
            attrs.get("state"),
            attrs.get("session-type", ""),
            attrs.get("username") or attrs.get("uid") or "",
            attrs.get("session-name", "")))
        for i, sockpath in enumerate(attrs.get("socket-paths", ())):
            print(indent + ("sockets:     " if i == 0 else " " * 13) + sockpath)
        if session_dir := find_session_dir(options.sessions_dir, display, attrs):
            print(f"{indent}session-dir: {session_dir}")
        details = get_session_details(session_dir, attrs)
        if server := csv(f"{k} {v}" for k, v in details.items() if k in ("pid", "uuid") and v):
            print(f"{indent}server:      {server}")
        if details.get("command"):
            print(f"{indent}command:     {details['command']}")
        if details.get("display-command"):
            print(f"{indent}display:     {details['display-command']}")
    return 0


def run_list(opts, _args, clean: bool = True) -> ExitValue:
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(opts.socket_dirs + opts.client_socket_dirs)
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
            if state in (SocketState.DEAD, SocketState.UNKNOWN):
                # A socket can briefly look dead while its server is still
                # starting.  Keep probing until the timeout before removing
                # it: deleting it here races with server startup.
                unknown.append(v)
            else:
                sys.stdout.write(f"\t{state} session at {display} ({socket_dir})\n")
    # now cleanup those still unknown:
    clean_states = [SocketState.DEAD, SocketState.UNKNOWN]
    for state, display, sockpath in unknown:
        state = dotxpra.get_server_state(sockpath)
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


def run_list_windows(opts, _args) -> ExitValue:
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(opts.socket_dirs)
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
            if dinfo := exec_and_parse("info", display):
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


def run_list_clients(opts, _args) -> ExitValue:
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


def run_stopexit(mode: str, opts, extra_args: list[str], cmdline: list[str]) -> ExitValue:
    assert mode in ("stop", "exit")

    def multimode(displays: list[str]) -> int:
        sys.stdout.write(f"Trying to {mode} {len(displays)} displays:\n")
        sys.stdout.write(" %s\n" % csv(displays))
        procs = []
        # ["xpra", "stop", ..]
        from xpra.platform.paths import get_nodock_command
        cmd = get_nodock_command() + [mode]
        socket_dirs = list(opts.socket_dirs)
        # TODO: this still relies on the deprecated primary socket-dir value.
        if opts.socket_dir and opts.socket_dir not in socket_dirs:
            socket_dirs.insert(0, opts.socket_dir)
        for x in socket_dirs:
            if x:
                cmd.append(f"--socket-dirs={x}")
        # use a subprocess per display:
        for display in displays:
            dcmd = cmd + [display]
            proc = Popen(dcmd)
            procs.append(proc)
        start = monotonic()
        live = procs
        while monotonic() - start < 10 and live:
            live = [x for x in procs if x.poll() is None]
        return 0

    if len(extra_args) == 1 and extra_args[0] == "all":
        # stop or exit all
        from xpra.platform.dotxpra import DotXpra
        dotxpra = DotXpra(opts.socket_dirs)
        displays = dotxpra.displays(check_uid=getuid(), matching_state=SocketState.LIVE)
        if not displays:
            sys.stdout.write("No xpra sessions found\n")
            return 1
        if len(displays) == 1:
            # fall through, but use the display we found:
            extra_args = displays
        else:
            assert len(displays) > 1
            return multimode(displays)
    elif len(extra_args) > 1:
        return multimode(extra_args)

    if mode == "stop" and len(extra_args) == 1 and POSIX and not OSX:
        # the server may be gone (`xpra exit` or a crash), but not the processes it started:
        r = stop_dead_session(opts, extra_args[0])
        if r is not None:
            return r

    display_desc = pick_display(opts, extra_args, cmdline)
    app = None
    try:
        if mode == "stop":
            from xpra.client.base.command import StopXpraClient
            app = StopXpraClient(opts)
        else:
            assert mode == "exit"
            from xpra.client.base.command import ExitXpraClient
            app = ExitXpraClient(opts)
        app.display_desc = display_desc
        from xpra.scripts.main import connect_to_server
        connect_to_server(app, display_desc, opts)
        e = app.run()
    except ImportError as e:
        sys.stderr.write(f"Error: unable to use the {mode!r} subcommand:\n")
        sys.stderr.write(f" the 'xpra-client' component is not installed: {e}\n")
        return ExitCode.COMPONENT_MISSING
    finally:
        if app:
            app.cleanup()
    if e == 0:
        if display_desc["local"] and display_desc.get("display"):
            show_final_state(display_desc)
        else:
            print(f"Sent {mode} command")
    return e


def show_final_state(display_desc: dict[str, Any]) -> int:
    # this is for local sockets only!
    display = display_desc["display"]
    sockdirs = list(display_desc.get("socket_dirs", ()))
    sockdir = display_desc.get("socket_dir", "")
    if sockdir and sockdir not in sockdirs:
        sockdirs.insert(0, sockdir)
    from xpra.platform.dotxpra import DotXpra
    sockdir = DotXpra(sockdirs)
    try:
        sockfile = get_sockpath(display_desc, 0)
    except (InitException, InitExit):
        # could be a named-pipe:
        sockfile = display_desc.get("named-pipe", "")
    if sockfile and os.path.isabs(sockfile):
        # first 5 seconds: just check if the socket still exists:
        # without connecting (avoid warnings and log messages on server)
        for _ in range(25):
            if not os.path.exists(sockfile):
                break
            time.sleep(0.2)
    final_state = SocketState.UNKNOWN
    if sockfile:
        # next 5 seconds: actually try to connect
        final_state = SocketState.UNKNOWN
        for _ in range(5):
            final_state = sockdir.get_server_state(sockfile, 1)
            if final_state is SocketState.DEAD:
                break
            time.sleep(1)
    if final_state is SocketState.DEAD:
        print(f"xpra at {display} has exited.")
        return 0
    if final_state is SocketState.UNKNOWN:
        print(f"How odd... I'm not sure what's going on with xpra at {display}")
        return 1
    if final_state is SocketState.LIVE:
        print(f"Failed to shutdown xpra at {display}")
        return 1
    raise RuntimeError(f"invalid state: {final_state}")


def stop_dead_session(opts, display: str) -> ExitValue | None:
    """
    terminate the processes left behind by a server that is no longer running,
    returns `None` if this does not look like a dead local session
    """
    if not display.lstrip(":").isdigit():
        return None
    display = ":" + display.lstrip(":")
    uid = getuid()
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(opts.socket_dirs)
    if display in dotxpra.displays(check_uid=uid, matching_state=SocketState.LIVE):
        return None
    from xpra.scripts.session import get_session_dir
    session_dir = get_session_dir("", opts.sessions_dir, display, uid)
    if not os.path.isdir(session_dir):
        return None
    server_pid = load_pid(os.path.join(session_dir, "server.pid"))
    if server_pid and os.path.exists(f"/proc/{server_pid}"):
        # the server is still running, even if we cannot see its socket:
        return None
    pids: dict[int, str] = {}
    for fname in sorted(os.listdir(session_dir)):
        if not fname.endswith(".pid") or fname == "server.pid":
            continue
        pid = load_pid(os.path.join(session_dir, fname))
        try:
            if not pid or os.stat(f"/proc/{pid}").st_uid != uid:
                continue
        except OSError:
            continue
        cmd = (load_binary_file(f"/proc/{pid}/cmdline") or b"").replace(b"\0", b" ").decode("latin1").strip()
        pids[pid] = cmd or fname[:-4]
    if pids:
        print(f"The server for session {display} is no longer running, found {len(pids)} processes left behind:")
        for pid, cmd in pids.items():
            print("%8i    %s" % (pid, cmd))
        print()
        countdown("These processes")
        for pid, cmd in pids.items():
            kill_pid(pid, cmd)
        start = monotonic()
        while monotonic() - start < 5 and any(os.path.exists(f"/proc/{pid}") for pid in pids):
            time.sleep(0.1)
    # remove the session directory and sockets:
    return run_clean(opts, [display])


def run_clean(opts, args: Iterable[str]) -> ExitValue:
    try:
        uid = int(opts.uid)
    except (ValueError, TypeError):
        uid = getuid()
    from xpra.scripts.session import get_session_dir, clean_session_dir
    clean: dict[str, str] = {}
    if args:
        for display in args:
            session_dir = get_session_dir("", opts.sessions_dir, display, uid)
            if not os.path.exists(session_dir) or not os.path.isdir(session_dir):
                print(f"session {display} not found")
            else:
                clean[display] = session_dir
        # the user specified the sessions to clean,
        # so we can also kill the display:
        kill_displays = True
    else:
        session_dir = osexpand(opts.sessions_dir)
        if not os.path.exists(session_dir):
            raise ValueError(f"cannot find sessions directory {opts.sessions_dir}")
        # try to find all the session directories:
        for x in os.listdir(session_dir):
            d = os.path.join(session_dir, x)
            if not os.path.isdir(d):
                continue
            try:
                int(x)
            except ValueError:
                continue
            else:
                clean[x] = d
        kill_displays = False

    def load_session_pid(pidfile: str) -> int:
        return load_pid(os.path.join(session_dir, pidfile))

    # also clean client sockets?
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(opts.socket_dirs)
    for display, session_dir in clean.items():
        if not os.path.exists(session_dir):
            print(f"session {display} not found")
            continue
        sockpath = os.path.join(session_dir, "socket")
        state = dotxpra.is_socket_match(sockpath, check_uid=uid)
        if state in (SocketState.LIVE, SocketState.INACCESSIBLE):
            # this session is still active
            # do not try to clean it!
            if args:
                print(f"session {display} is {state}")
                print(f" the session directory {session_dir} has not been removed")
            continue
        server_pid = load_session_pid("server.pid")
        if server_pid and POSIX and not OSX and os.path.exists(f"/proc/{server_pid}"):
            print(f"server process for session {display} is still running with pid {server_pid}")
            print(f" the session directory {session_dir!r} has not been removed")
            continue
        x11_socket = x11_display_socket(display)
        x11_live = stat_display_socket(x11_socket)
        xvfb_pid = get_xvfb_pid(display, session_dir)
        if x11_live:
            if xvfb_pid and kill_displays:
                kill_pid(xvfb_pid, "xvfb")
            else:
                print(f"X11 server :{display} is still running ")
                if xvfb_pid:
                    print(" run clean-displays to terminate it")
                print(" cowardly refusing to clean the session")
                continue
        clean_session_dir(session_dir)
        # remove the other sockets:
        socket_paths = dotxpra.socket_paths(check_uid=uid, matching_display=display)
        for filename in socket_paths:
            try:
                os.unlink(filename)
            except OSError as rme:
                error(f"Error removing socket {filename!r}: {rme}")
    return 0


def run_clean_sockets(opts, args) -> ExitValue:
    matching_display = args[0] if args else None
    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(opts.socket_dirs + opts.client_socket_dirs)
    results = dotxpra.socket_details(check_uid=getuid(),
                                     matching_state=SocketState.UNKNOWN,
                                     matching_display=matching_display)
    if matching_display and not results:
        raise InitInfo(f"no UNKNOWN socket for display {matching_display!r}")
    # `socket_details` returns a dict of socket_dir -> [(state, display, sockpath), ..],
    # but `clean_sockets` wants a list of (socket_dir, display, sockpath):
    sockets = [(socket_dir, display, sockpath)
               for socket_dir, values in results.items() for _, display, sockpath in values]
    clean_sockets(dotxpra, sockets)
    return ExitCode.OK


def run_recover(script_file: str, cmdline: list[str], options, args: list[str], defaults) -> ExitValue:
    if not POSIX or OSX:
        raise InitExit(ExitCode.UNSUPPORTED, "the 'xpra recover' subcommand is not supported on this platform")
    no_gtk()
    display_descr: dict = {}
    ALL = len(args) == 1 and args[0].lower() == "all"
    if not ALL and len(args) == 1:
        try:
            display_descr = pick_display(options, args, cmdline)
            args = []
        except Exception:
            pass
    if display_descr:
        display = display_descr.get("display")
        # args are enough to identify the display,
        # get the `display_info` so that we know the mode to use:
        descr = get_display_info(display, options.sessions_dir)
    else:

        def recover_many(displays) -> int:
            from xpra.platform.paths import get_xpra_command  # pylint: disable=import-outside-toplevel
            for display in displays:
                cmd = get_xpra_command() + ["recover", display]
                Popen(cmd)
            return 0

        if len(args) > 1:
            return recover_many(args)
        displays = get_displays_info(sessions_dir=options.sessions_dir)
        # find the 'DEAD' ones:
        dead_displays = tuple(display for display, descr in displays.items() if descr.get("state") == "DEAD")
        if not dead_displays:
            print("No dead displays found, see 'xpra displays'")
            return ExitCode.NO_DISPLAY
        if len(dead_displays) > 1:
            if ALL:
                return recover_many(dead_displays)
            print("More than one 'DEAD' display found, see 'xpra displays'")
            print(" you can use 'xpra recover all',")
            print(" or specify a display")
            return ExitCode.NO_DISPLAY
        display = dead_displays[0]
        descr = displays[display]
    args = [display]
    # figure out what mode was used:
    mode = descr.get("xpra-server-mode", "seamless")
    for m in ("seamless", "desktop", "proxy", "shadow", "shadow-screen"):
        if mode.find(m) >= 0:
            mode = m
            break
    print(f"Recovering display {display!r} as a {mode} server")
    # use the existing display:
    options.use_display = "yes"
    no_gtk()
    from xpra.scripts.main import run_server
    return run_server(script_file, cmdline, options, args, mode, defaults)
