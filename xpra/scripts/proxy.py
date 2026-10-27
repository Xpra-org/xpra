# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# the proxy subcommands and server subprocess startup, separated from main.py

import os
import sys
from subprocess import Popen

from xpra.common import noerr
from xpra.util.str_fn import csv
from xpra.util.io import warn, stderr_print
from xpra.util.parsing import parse_bool_or
from xpra.exit_codes import ExitCode, ExitValue, exit_str
from xpra.os_util import getuid, getgid, WIN32, OSX, POSIX
from xpra.config import InitException, InitExit
from xpra.config.fixup import fixup_options
from xpra.net.constants import SocketState
from xpra.log import Logger, get_debug_args
from xpra.scripts.parsing import parse_display_name, parse_env, MODE_ALIAS
from xpra.scripts.args import strip_defaults_start_child, split_display_arg, get_start_server_args
from xpra.scripts.picker import pick_shadow_display, pick_display, connect_or_fail
from xpra.scripts.common import no_gtk
from xpra.scripts.display import get_displays_info
from xpra.scripts.sessions import identify_new_socket
from xpra.scripts.clients import run_client, get_client_app, do_run_client
from xpra.util.env import envint

# pylint: disable=import-outside-toplevel

# how long `xpra control` may take to start a command on an existing server:
CONTROL_TIMEOUT = envint("XPRA_PROXY_CONTROL_TIMEOUT", 30)


def add_process(*args, **kwargs):
    from xpra.util.child_reaper import get_child_reaper
    return get_child_reaper().add_process(*args, **kwargs)


# noinspection PySimplifyBooleanCheck
def start_server_via_proxy(cmdline, options, args, mode: str) -> ExitValue | None:
    start_via_proxy = parse_bool_or("start-via-proxy", options.start_via_proxy)
    if start_via_proxy is False:
        return None
    if not options.daemon:
        if start_via_proxy is True:
            raise InitExit(ExitCode.ARGUMENT_MISMATCH, "cannot start-via-proxy without daemonizing")
        return None
    if POSIX and getuid() == 0:
        raise InitExit(ExitCode.ARGUMENT_MISMATCH, "cannot start via proxy for root")
    try:
        from xpra import client  # pylint: disable=import-outside-toplevel
        if not client:
            # cythonized code can bind None for missing imports
            raise ImportError("xpra.client")
    except ImportError as e:
        if start_via_proxy is True:
            raise InitExit(ExitCode.COMPONENT_MISSING, f"cannot start-via-proxy: `xpra-client` is not installed: {e}") from None
        return None
    ################################################################################
    try:
        # this will use the client "start-new-session" feature,
        # to start a new session and connect to it at the same time:
        if not args:
            from xpra.net.constants import SYSTEM_PROXY_SOCKET
            args = [SYSTEM_PROXY_SOCKET]
        app = get_client_app(cmdline, options, args, "request-%s" % mode)
        r = do_run_client(app)
        # OK or got a signal:
        NO_RETRY: list[int] = [int(ExitCode.OK)] + list(range(128, 128 + 16))
        # TODO: honour "--attach=yes"
        if app.completed_startup:
            # if we had connected to the session,
            # we can ignore more error codes:
            NO_RETRY += [int(x) for x in (
                ExitCode.CONNECTION_LOST,
                ExitCode.REMOTE_ERROR,
                ExitCode.INTERNAL_ERROR,
                ExitCode.FILE_TOO_BIG,
            )]
        if r in NO_RETRY:
            return r
        if r == ExitCode.FAILURE:
            err = "unknown general failure"
        else:
            err = exit_str(r)
    except Exception as e:
        log = Logger("proxy")
        log("failed to start via proxy", exc_info=True)
        err = str(e)
    if start_via_proxy is True:
        raise InitExit(ExitCode.FAILURE, f"failed to start-via-proxy: {err}")
    # warn and fall through to regular server start:
    warn(f"Warning: cannot use the system proxy for {mode!r} subcommand,")
    warn(f" {err}")
    warn(" more information may be available in your system log")
    return None


def start_server_subprocess(script_file: str, args: list[str], mode: str, opts,
                            username="", uid=getuid(), gid=getgid(), env=None, cwd=None):
    log = Logger("server", "exec")
    if env is None:
        env = os.environ.copy()
    log("start_server_subprocess%s", (script_file, args, mode, opts, uid, gid, env, cwd))
    # we must use a subprocess to avoid messing things up - yuk
    mode = MODE_ALIAS.get(mode, mode)
    if mode not in ("seamless", "desktop", "monitor", "expand", "shadow", "shadow-screen"):
        raise ValueError(f"invalid mode {mode!r}")
    if len(args) not in (0, 1):
        raise InitException(f"{mode}: expected 0 or 1 arguments but got {len(args)}: {args}")
    if mode in ("seamless", "desktop", "monitor"):
        if len(args) == 1:
            display_name = args[0]
        else:
            assert len(args) == 0
            # let the server get one from Xorg via displayfd:
            display_name = "S" + str(os.getpid())
    else:
        if mode not in ("expand", "shadow", "shadow-screen"):
            raise ValueError(f"invalid mode {mode!r}")
        display_name = pick_shadow_display(args, uid, gid, opts.sessions_dir)
        # we now know the display name, so add it:
        args = [display_name]
        opts.exit_with_client = True

    if display_name.startswith("S"):
        matching_display = ""
    else:
        if display_name.startswith(":") and display_name.find(",") > 0:
            # remove options from display name
            matching_display = display_name.split(",", 1)[0]
        else:
            matching_display = display_name

    from xpra.platform.dotxpra import DotXpra
    dotxpra = DotXpra(opts.socket_dirs, username, uid=uid, gid=gid)
    if WIN32:
        if not mode.startswith("shadow"):
            raise ValueError(f"invalid mode {mode!r} for MS Windows")
        assert display_name
        from xpra.platform.win32.shadow.main import proxy_start_win32_shadow
        return proxy_start_win32_shadow(script_file, args, opts, dotxpra, display_name)

    # get the current list of existing sockets,
    # so we can spot the new ones:
    existing_sockets: set[str] = set(dotxpra.socket_paths(check_uid=uid,
                                                          matching_state=SocketState.LIVE,
                                                          matching_display=matching_display))
    log(f"start_server_subprocess: existing_sockets={existing_sockets}")

    cmd = [script_file, mode] + args  # ie: ["/usr/bin/xpra", "start-desktop", ":100"]
    cmd += get_start_server_args(opts, uid, gid)  # ie: ["--exit-with-children", "--start-child=xterm"]
    debug_args = os.environ.get("XPRA_SUBPROCESS_DEBUG")
    if debug_args is None:
        debug_args = ",".join(get_debug_args())
    if debug_args:
        cmd.append(f"--debug={debug_args}")
    # when starting via the system proxy server,
    # we may already have a XPRA_PROXY_START_UUID,
    # specified by the proxy-start command:
    new_server_uuid = parse_env(opts.env or []).get("XPRA_PROXY_START_UUID")
    if not new_server_uuid:
        # generate one now:
        from xpra.os_util import get_hex_uuid
        new_server_uuid = get_hex_uuid()
        cmd.append(f"--env=XPRA_PROXY_START_UUID={new_server_uuid}")
    if mode.startswith("shadow") and OSX:
        from xpra.platform.darwin.shadow.main import start_macos_shadow
        start_macos_shadow(cmd, env, cwd)
        proc = None
    else:
        # useful for testing failures that cause the whole XDG_RUNTIME_DIR to get nuked
        # (and the log file with it):
        # cmd.append("--log-file=/tmp/proxy.log")
        preexec_fn = None
        pass_fds = ()
        r_pipe = w_pipe = 0
        if POSIX:
            preexec_fn = os.setpgrp
            cmd.append("--daemon=yes")
            cmd.append("--systemd-run=no")
            if getuid() == 0 and (uid != 0 or gid != 0):
                cmd.append(f"--uid={uid}")
                cmd.append(f"--gid={gid}")
            if not OSX and mode in ("seamless", "desktop", "monitor"):
                # the "--displayfd" switch tells us which display was chosen, once the server is ready,
                # and we get EOF if it fails - even when we chose the display:
                r_pipe, w_pipe = os.pipe()
                log("subprocess displayfd pipes: %s", (r_pipe, w_pipe))
                cmd.append(f"--displayfd={w_pipe}")
                pass_fds = (w_pipe,)
        log("start_server_subprocess: command=" + csv(repr(x) for x in cmd))
        proc = Popen(cmd, env=env, cwd=cwd, preexec_fn=preexec_fn, pass_fds=pass_fds)
        log(f"proc={proc}")
        add_process(proc, "server", cmd, ignore=True, forget=True)
        if w_pipe:
            # only the server should hold the write end,
            # so that we get EOF if it exits without writing the display:
            noerr(os.close, w_pipe)
        if r_pipe:
            from xpra.platform.displayfd import read_displayfd, parse_displayfd, pipe_closed
            # the server only writes to displayfd once it is ready,
            # but we get EOF straight away if it fails:
            from xpra.scripts.sessions import WAIT_SERVER_TIMEOUT
            buf = read_displayfd(r_pipe, timeout=WAIT_SERVER_TIMEOUT, proc=None)  # proc daemonizes!
            closed = not buf and pipe_closed(r_pipe)
            noerr(os.close, r_pipe)
            if closed:
                # the server has exited before telling us which display it is using,
                # and as it daemonizes, its errors are in its log file:
                raise InitExit(ExitCode.FAILURE, "the server failed to start, check its log file for details")

            def displayfd_err(msg: str) -> None:
                log.error("Error: displayfd failed")
                log.error(f" {msg}")

            if not matching_display:
                n = parse_displayfd(buf, displayfd_err)
                if n >= 0:
                    matching_display = f":{n}"
                    log(f"displayfd={matching_display}")
    socket_path, display = identify_new_socket(proc, dotxpra, existing_sockets,
                                               matching_display,
                                               new_server_uuid,
                                               display_name,
                                               uid)
    return proc, socket_path, display


def run_proxy_run(options, script_file: str, cmdline: list[str], args: list[str], mode: str = "run") -> ExitValue:
    display_args, cmd_args = split_display_arg(args)
    # print(f"{display_args=} {cmd_args=}")

    def is_live(display: str) -> bool:
        from xpra.platform.dotxpra import DotXpra
        dotxpra = DotXpra(options.socket_dirs)
        return dotxpra.get_display_state(display) == SocketState.LIVE

    try:
        display_desc = pick_display(options, display_args, cmdline)
        # print(f"picked display: {display_desc}")
    except (InitException, InitExit):
        if display_args:
            # the display was specified, so we can't continue:
            raise
        display_desc = {}

    if not display_desc and not display_args:
        # try harder, maybe there is a single display that isn't managed by an xpra session:
        displays = get_displays_info(display_names=display_args if display_args else None,
                                     sessions_dir=options.sessions_dir,
                                     backend=options.backend)
        if len(displays) == 1:
            display_desc = tuple(displays.values())[0]

    display = display_desc.get("display_name", "") or display_desc.get("display", "")
    if not display:
        raise InitExit(ExitCode.NO_DISPLAY, "unable to locate the display to run on")

    # now let's decide how to run the command on this display:
    if is_live(display):
        # found a live xpra socket, use the `xpra run` client:
        return run_client(script_file, cmdline, options, args, mode)

    env = os.environ.copy()
    env["DISPLAY"] = display
    run_daemon(cmd_args, env=env)
    return 0


def run_daemon(cmd: list[str], **kwargs):
    from xpra.util.daemon import daemonize

    def preexec() -> None:
        daemonize()
        sys.stdout.write("command started with pid %s\n" % os.getpid())

    proc = Popen(cmd, preexec_fn=preexec, **kwargs)
    proc.poll()
    return proc


def start_commands_on_existing(script_file: str, display_name: str, opts, defaults) -> None:
    """
    `_proxy_start` for a display which is already running:
    there is no new server to give the `start` and `start-child` commands to,
    so ask the existing one to run them, as `xpra control DISPLAY start[-child]` would.
    """
    log = Logger("server", "exec")
    import shlex
    from subprocess import run, DEVNULL, TimeoutExpired
    failed: list[str] = []
    for option, subcommand in (("start", "start"), ("start_child", "start-child")):
        for command in strip_defaults_start_child(getattr(opts, option), getattr(defaults, option)):
            if not command:
                continue
            # the server splits the command string the same way:
            cmd = [script_file, "control", display_name, subcommand, "--"] + shlex.split(command)
            log("start_commands_on_existing: %s", cmd)
            try:
                # our stdout carries the connection, so nothing else must be written to it:
                proc = run(cmd, stdin=DEVNULL, capture_output=True, timeout=CONTROL_TIMEOUT)
            except (OSError, TimeoutExpired) as e:
                stderr_print(f"Error: failed to start {command!r} on display {display_name}: {e}")
                failed.append(command)
                continue
            for line in (proc.stdout + proc.stderr).decode(errors="replace").splitlines():
                if line.strip():
                    stderr_print(line)
            if proc.returncode:
                stderr_print(f"Error: failed to start {command!r} on display {display_name}: {exit_str(proc.returncode)}")
                failed.append(command)
    if failed:
        # exit with an error rather than connecting, so the client can tell:
        commands = csv(repr(x) for x in failed)
        raise InitExit(ExitCode.FAILURE, f"failed to start {commands} on display {display_name}")


def run_proxy(opts, script_file: str, cmdline: list[str], args: list[str], mode: str, defaults) -> ExitValue:
    no_gtk()
    display = {}
    display_name = ""
    server_mode = {
        "_proxy": "seamless",
        "_proxy_shadow_start": "shadow",
    }.get(mode, mode.replace("_proxy_", "").replace("_", "-"))
    server_mode = MODE_ALIAS.get(server_mode, server_mode)
    if mode != "_proxy" and server_mode in ("seamless", "desktop", "monitor", "shadow", "shadow-screen", "expand"):
        attach = parse_bool_or("attach", opts.attach, None)
        state = SocketState.UNKNOWN
        if attach is not False:
            # maybe this server already exists?
            from xpra.platform.dotxpra import DotXpra
            dotxpra = DotXpra(opts.socket_dirs)
            if not args and server_mode in ("shadow", "shadow-screen", "expand"):
                try:
                    display_name = pick_shadow_display(args, sessions_dir=opts.sessions_dir)
                    args = [display_name]
                except Exception:
                    # failed to guess!
                    pass
            elif args:
                display = pick_display(opts, args, cmdline)
                display_name = display.get("display")
            if display_name:
                state = dotxpra.get_display_state(display_name)
                if state != SocketState.DEAD:
                    stderr_print(f"found existing display {display_name} : {state}")
        if state == SocketState.LIVE:
            start_commands_on_existing(script_file, display_name, opts, defaults)
        else:
            # strip defaults, only keep extra ones:
            for x in ("start", "start-child",
                      "start-after-connect", "start-child-after-connect",
                      "start-on-connect", "start-child-on-connect",
                      "start-on-disconnect", "start-child-on-disconnect",
                      "start-on-last-client-exit", "start-child-on-last-client-exit",
                      ):
                fn = x.replace("-", "_")
                v = strip_defaults_start_child(getattr(opts, fn), getattr(defaults, fn))
                setattr(opts, fn, v)
            opts.splash = False
            fixup_options(opts)
            proc, socket_path, display_name = start_server_subprocess(script_file, args, server_mode, opts)
            if not socket_path:
                # if we return non-zero, we will try the next run-xpra script in the list..
                return 0
            if WIN32:
                uri = f"named-pipe://{display_name}"
            else:
                uri = f"socket://{socket_path}"
            display = parse_display_name(opts, uri, cmdline)
            if proc and proc.poll() is None:
                # start a thread just to reap server startup process (yuk)
                # (as the server process will exit as it daemonizes)
                from xpra.util.thread import start_thread
                start_thread(proc.wait, "server-startup-reaper")
    if not display:
        # use display specified on command line:
        try:
            display = pick_display(opts, args, cmdline)
        except ValueError as e:
            raise InitExit(ExitCode.SERVER_NOT_FOUND, str(e)) from None
    delpath = ""
    if display and not server_mode.startswith("shadow"):
        display_name = display_name or display.get("display") or display.get("display_name")
        try:
            from xpra.net.ssh.agent import setup_proxy_ssh_socket
        except ImportError:
            pass
        else:
            try:
                from xpra.scripts.session import get_session_dir
                session_dir = get_session_dir("attach", opts.sessions_dir, display_name, getuid())
                # ie: "/run/user/$UID/xpra/$DISPLAY/ssh/$UUID
                delpath = setup_proxy_ssh_socket(cmdline, session_dir=session_dir)
            except OSError:
                sshlog = Logger("ssh")
                sshlog.error("Error setting up client ssh agent forwarding socket", exc_info=True)
    server_conn = connect_or_fail(display)
    from xpra.scripts.fdproxy import XpraProxy
    from xpra.net.bytestreams import TwoFileConnection
    pipe = TwoFileConnection(sys.stdout, sys.stdin, socktype="stdin/stdout")
    app = XpraProxy("xpra-pipe-proxy", pipe, server_conn)
    try:
        return app.run()
    finally:
        if delpath:
            noerr(os.unlink, delpath)
