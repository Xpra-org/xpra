# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Starting servers: locally (via the system proxy or `xpra.scripts.server`),
or remotely by asking a server over ssh / tcp / ssl / etc to start one.
Unlike `xpra.scripts.server`, this module is included in client-only builds.
"""

import os
from subprocess import run

from xpra.common import may_show_progress
from xpra.util.parsing import ALL_BOOLEAN_OPTIONS, parse_scaling, str_to_bool
from xpra.exit_codes import ExitCode, ExitValue, RETRY_EXIT_CODES, exit_str
from xpra.os_util import WIN32, OSX, POSIX
from xpra.util.io import warn
from xpra.config import InitException, InitExit
from xpra.config.types import CLIENT_OPTIONS, START_COMMAND_OPTIONS
from xpra.net.constants import SocketState
from xpra.log import Logger
from xpra.scripts.parsing import parse_display_name, MODE_ALIAS
from xpra.scripts.args import (
    isdisplaytype,
    is_connection_arg,
    strip_defaults_start_child,
    strip_attach_extra_positional_args,
    find_mode_pos,
    get_start_server_args,
)
from xpra.scripts.picker import pick_display
from xpra.scripts.common import bypass_no_gtk, reqx11
from xpra.scripts.clients import run_client, make_client, connect_to_server, do_run_client, exec_reconnect
from xpra.scripts.proxy import start_server_via_proxy

# pylint: disable=import-outside-toplevel


def get_logger() -> Logger:
    return Logger("util")


def split_start_child_args(cmdline: list[str], options, args: list[str]) -> list[str]:
    """
    all args that aren't specifying a connection will be interpreted as a start-child command:
    ie: "xpra" "seamless" "xterm"
    ie: "xpra" "desktop" "ssh://host/" "fluxbox"
    and we also enable `exit-with-children` if unspecified
    returns the connection args
    """
    commands = []
    connargs = []
    for arg in args:
        if is_connection_arg(arg):
            # keep this one
            connargs.append(arg)
        else:
            commands.append(arg)
    if not commands:
        return args
    # figure out if we also auto-enable:
    # * --exit-with-children:
    if not any(x.startswith("--exit-with-children") or x == "--no-exit-with-children" for x in cmdline):
        options.exit_with_children = True
    # * --attach if we have a real display:
    # but not if attach was specified on the command line
    # and not if we have html=open
    html_open = (options.html or "").lower() not in (list(ALL_BOOLEAN_OPTIONS) + ["auto", "none", None])
    if not html_open and not any(x.startswith("--attach") or x == "--no-attach" for x in cmdline):
        options.attach = OSX or WIN32 or any(os.environ.get(x) for x in (
            "DISPLAY", "WAYLAND_DISPLAY", "SSH_CONNECTION",
        ))
    options.start_child += commands
    return connargs


def run_server_mode(script_file: str, cmdline: list[str], options, args: list[str], mode: str, full_mode: str, defaults) -> ExitValue:
    if mode in ("seamless", "desktop", "monitor", "expand", "shadow", "shadow-screen"):
        if args and mode in ("seamless", "desktop", "monitor"):
            args = split_start_child_args(cmdline, options, args)
        if isdisplaytype(args, "ssh", "tcp", "ssl", "vsock", "hyperv", "quic"):
            # ie: "xpra start ssh://USER@HOST:SSHPORT/DISPLAY --start-child=xterm"
            return run_remote_server(script_file, cmdline, options, args, mode, defaults)
        if args and str_to_bool(options.attach, False):
            # maybe the server is already running,
            # and we don't need to bother trying to start it:
            try:
                display = pick_display(options, args, cmdline)
            except Exception:
                pass
            else:
                from xpra.platform.dotxpra import DotXpra
                dotxpra = DotXpra(options.socket_dirs)
                if display_name := display.get("display_name"):
                    state = dotxpra.get_display_state(display_name)
                    if state == SocketState.LIVE:
                        get_logger().info(f"existing live display found on {display_name}, attaching")
                        # we're connecting locally, so no need for these:
                        options.csc_modules = ["none"]
                        options.video_decoders = ["none"]
                        options.mode = "attach"
                        return run_client(script_file, cmdline, options, args, "attach")
    return run_server(script_file, cmdline, options, args, full_mode, defaults)


def match_client_display_size(options, display_is_remote=True) -> None:
    if options.resize_display.lower() != "auto":
        return
    # Disable the local display-size probe until the Wayland backend can
    # safely use it without connecting Gdk to an Xpra Wayland display.
    if options.backend.lower() == "wayland":
        return
    # if possible, use the current display size as initial vfb size
    root_w, root_h = get_current_root_size(display_is_remote)
    if 0 < root_w < 16384 and 0 < root_h < 16384:
        scaling_x, scaling_y = parse_scaling(options.desktop_scaling, root_w, root_h)
        scaled_w = round(root_w / scaling_x)
        scaled_h = round(root_h / scaling_y)
        options.resize_display = f"{scaled_w}x{scaled_h}"


def run_server(script_file, cmdline: list[str], options, args: list[str], full_mode: str, defaults) -> ExitValue:
    mode_parts = full_mode.split(",", 1)
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])
    if mode in (
            "seamless", "desktop", "monitor",
            "upgrade", "upgrade-seamless", "upgrade-desktop", "upgrade-monitor",
    ):
        reqx11(mode)
    display_is_remote = isdisplaytype(args, "ssh", "tcp", "ssl", "ws", "wss", "vsock")
    with_display = mode in ("seamless", "desktop", "monitor", "expand")
    if with_display and str_to_bool(options.attach, False) and args and not display_is_remote:
        # maybe the server is already running for the display specified
        # then we don't even need to bother trying to start it:
        try:
            display_desc = pick_display(options, args, cmdline)
        except (ValueError, InitException, InitExit):
            pass
        else:
            from xpra.platform.dotxpra import DotXpra
            dotxpra = DotXpra(options.socket_dirs)
            if display := display_desc.get("display_name"):
                state = dotxpra.get_display_state(display)
                if state == SocketState.LIVE:
                    get_logger().info(f"existing live display found on {display}, attaching")
                    # we're connecting locally, so no need for these:
                    options.csc_modules = ["none"]
                    options.video_decoders = ["none"]
                    from xpra.scripts.main import do_run_mode
                    return do_run_mode(script_file, cmdline, options, args, "attach", defaults)
    if mode == "seamless":
        match_client_display_size(options, display_is_remote)

    if mode not in ("encoder", "runner"):
        r = start_server_via_proxy(cmdline, options, args, full_mode)
        if isinstance(r, int):
            return r

    try:
        from xpra import server
        if not server:
            # cythonized code can bind None for missing imports
            raise ImportError("xpra.server")
        from xpra.scripts.server import do_run_server
        return do_run_server(script_file, cmdline, options, args, full_mode, defaults)
    except ImportError as e:
        raise InitExit(ExitCode.COMPONENT_MISSING, f"`xpra-server` is not installed: {e}")


def get_current_root_size(display_is_remote: bool) -> tuple[int, int]:
    root_w = root_h = 0
    if display_is_remote or OSX or not POSIX:
        # easy path, just load gtk early:
        from xpra.scripts.main import check_gtk_client
        check_gtk_client()
        bypass_no_gtk()
        # we should be able to get the root window size:
        from xpra.gtk.util import get_root_size
        return get_root_size((0, 0))
    # we can't load gtk on posix if the server is local,
    # (as we would need to unload the initial display to attach to the new one)
    # so use a subprocess as a temporary context and parse the output..
    try:
        # ie: ["/usr/bin/python3", "-c"] + ...
        from xpra.platform.paths import get_xpra_command
        cmd = get_xpra_command() + ["root-size"]
        proc = run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout:
            # ie: "3840x2160\n"
            pair = proc.stdout.rstrip("\n").split("x")
            if len(pair) == 2:
                root_w, root_h = int(pair[0]), int(pair[1])
    except (OSError, ValueError):
        pass
    return root_w, root_h


def run_remote_server(script_file: str, cmdline, opts, args, mode: str, defaults) -> ExitValue:
    """ Uses the regular XpraClient with patched proxy arguments to tell run_proxy to start the server """
    if not args:
        raise RuntimeError("no remote server specified")
    display_name = args[0]
    params = parse_display_name(opts, display_name, cmdline)
    hello_extra = {}
    # strip defaults, only keep extra ones:
    for x in START_COMMAND_OPTIONS:  # ["start", "start-child", etc]
        fn = x.replace("-", "_")
        v = strip_defaults_start_child(getattr(opts, fn), getattr(defaults, fn))
        setattr(opts, fn, v)
    if mode == "seamless":
        match_client_display_size(opts)
    if isdisplaytype(args, "ssh"):
        # add special flags to "display_as_args"
        proxy_args = params.get("display_as_args", [])
        if params.get("display") is not None:
            geometry = params.get("geometry")
            display = params["display"]
            try:
                pos = proxy_args.index(display)
            except ValueError:
                pos = -1
            if display.replace(".", "").isnumeric():
                # numeric displays are X11 display names:
                display = f":{display}"
            if mode.startswith("shadow") and geometry:
                display += f",{geometry}"
            if pos >= 0:
                proxy_args[pos] = display
            elif display:
                proxy_args.append(display)
        for x in get_start_server_args(opts, compat=True, cmdline=cmdline):
            proxy_args.append(x)
        # we have consumed the start[-child] options
        for x in (
                "start", "start-child",
                "start-late", "start-child-late",
                "start-after-connect", "start-child-after-connect",
                "start-on-connect", "start-child-on-connect",
                "start-on-disconnect", "start-child-on-disconnect",
                "start-on-last-client-exit", "start-child-on-last-client-exit",
        ):
            setattr(opts, x.replace("-", "_"), [])
        params["display_as_args"] = proxy_args
        # and use a proxy subcommand to start the server:
        if mode == "seamless":
            # this should also be switched to the generic syntax below in v6:
            proxy_command = "_proxy_start"
        elif mode == "shadow":
            # this should also be switched to the generic syntax below in v6:
            proxy_command = "_proxy_shadow_start"
        else:
            # ie: "_proxy_start_desktop"
            proxy_command = f"_proxy_start_{mode.replace('-', '_')}"
        params["proxy_command"] = [proxy_command]
        sns = {}  # will be unused, but this silences a warning
    else:
        # tcp, ssl or vsock:
        sns = {
            "mode": mode,
            "display": params.get("display", ""),
        }
        for x in START_COMMAND_OPTIONS:
            fn = x.replace("-", "_")
            if v := getattr(opts, fn):
                sns[x] = v
        hello_extra = {"start-new-session": sns}

    app = None
    try:
        if opts.attach is False:
            from xpra.client.base.command import WaitForDisconnectXpraClient, RequestStartClient
            if isdisplaytype(args, "ssh"):
                # ssh will start the instance we requested,
                # then we just detach and we're done
                app = WaitForDisconnectXpraClient(opts)
            else:
                app = RequestStartClient(opts)
                app.start_new_session = sns
            app.hello_extra = {"connect": False}
            opts.reconnect = False
        else:
            app = make_client(opts)
            may_show_progress(app, 30, "client configuration")
            app.init(opts)
            may_show_progress(app, 40, "loading user interface")
            app.init_ui(opts)
            app.load()
            app.hello_extra = hello_extra

            def handshake_complete(*_args) -> None:
                may_show_progress(app, 100, "connection established")

            app.after_handshake(handshake_complete)
        may_show_progress(app, 60, "starting server")

        connect_to_server(app, params, opts)
    except Exception as e:
        if app:
            may_show_progress(app, 100, "failure", e)
        raise
    r = do_run_client(app)
    if opts.reconnect is not False and r in RETRY_EXIT_CODES:
        warn("%s, reconnecting" % exit_str(r))
        args = list(cmdline)
        # modify the 'mode' in the command line to use `attach`:
        # made more difficult by mode name aliases
        mode_pos = find_mode_pos(args, mode)
        args[mode_pos] = "attach"
        if not params.get("display", ""):
            # try to find which display was used,
            # so we can re-connect to this specific one:
            display = getattr(app, "_remote_display", None)
            if not display:
                warn("cannot identify the remote display to reconnect to")
                warn(" this may fail if there is more than one")
            else:
                # then re-generate a URI with this display name in it:
                new_params = params.copy()
                new_params["display"] = display
                from xpra.net.connect import display_desc_to_uri
                uri = display_desc_to_uri(new_params)
                # and change it in the command line:
                try:
                    uri_pos = args.index(display_name)
                except ValueError:
                    raise InitException("URI not found in command line arguments") from None
                args[uri_pos] = uri
        # remove command line options consumed by 'start' that should not be used again:
        attach_args = []
        i = 0
        while i < len(args):
            arg = args[i]
            i += 1
            if arg.startswith("--"):
                pos = arg.find("=")
                if pos > 0:
                    option = arg[2:pos]
                else:
                    option = arg[2:]
                if option.startswith("start") or option not in CLIENT_OPTIONS:
                    if pos < 0 and i < len(args) and not args[i].startswith("--"):
                        i += 1
                    continue
            attach_args.append(arg)
        attach_args = strip_attach_extra_positional_args(attach_args)
        return exec_reconnect(script_file, attach_args)
    return r
