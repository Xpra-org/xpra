#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import time
import logging
from time import monotonic
from importlib.util import find_spec
from collections.abc import Sequence

from subprocess import Popen, PIPE, TimeoutExpired, run
import signal
import shlex
import traceback
from typing import Any, NoReturn
from collections.abc import Callable, Iterable

from xpra.common import noerr, noop, may_show_progress, may_notify_client
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict
from xpra.util.pid import load_pid, kill_pid
from xpra.util.str_fn import csv, print_nested_dict, sorted_nicely, bytestostr
from xpra.util.env import envint, envbool, osexpand, save_env, get_exec_env, get_saved_env_var, OSEnvContext
from xpra.util.parsing import (
    ALL_BOOLEAN_OPTIONS,
    parse_scaling, str_to_bool, parse_bool_or,
    get_refresh_rate_for_value, adjust_monitor_refresh_rate, validated_monitor_data,
)
from xpra.exit_codes import ExitCode, ExitValue, RETRY_EXIT_CODES, exit_str
from xpra.os_util import getuid, getgid, is_admin, gi_import, WIN32, OSX, POSIX
from xpra.util.io import load_binary_file, stderr_print, info, warn, error, clean_std_pipes
from xpra.util.system import is_Wayland, set_proc_title, is_systemd_pid1, stop_proc
from xpra.scripts.parsing import (
    get_usage,
    parse_display_name, parse_env,
    fixup_defaults,
    validated_encodings, validate_encryption, do_parse_cmdline, show_audio_codec_help,
    MODE_ALIAS,
)
from xpra.scripts.config import (
    XpraConfig,
    CLIENT_OPTIONS,
    START_COMMAND_OPTIONS, PROXY_START_OVERRIDABLE_OPTIONS,
    InitException, InitInfo, InitExit,
    fixup_options,
    find_docs_path, find_html5_path,
    get_defaults,
    make_defaults_struct, has_audio_support,
    xvfb_command,
)
from xpra.net.constants import SOCKET_TYPES, SocketState
from xpra.log import is_debug_enabled, Logger, get_debug_args, enable_format, inject_debug_logging
from xpra.scripts.display import (
    stat_display_socket,
    x11_display_socket, get_xvfb_pid,
    get_display_pids,
    get_display_info, get_displays_info,
)
from xpra.scripts.sessions import (
    identify_new_socket,
    run_list_sessions,
    run_list, clean_sockets,
    run_list_windows, run_list_clients,
)
from xpra.scripts.args import (
    strip_defaults_start_child,
    split_display_arg,
    is_connection_arg,
    strip_attach_extra_positional_args,
    find_mode_pos,
    get_start_server_args,
)
from xpra.scripts.picker import (
    pick_shadow_display,
    pick_display,
    do_pick_display,
    connect_or_fail,
    get_sockpath,
)
from xpra.scripts.common import bypass_no_gtk, no_gtk

assert callable(error), "used by modules importing this function from here"

NO_ROOT_WARNING: bool = envbool("XPRA_NO_ROOT_WARNING", False)
WAIT_SERVER_TIMEOUT: int = envint("WAIT_SERVER_TIMEOUT", 90)
OPENGL_PROBE_TIMEOUT: int = envint("XPRA_OPENGL_PROBE_TIMEOUT", 5)
SYSTEMD_RUN: bool = envbool("XPRA_SYSTEMD_RUN", True)
VERIFY_SOCKET_TIMEOUT: int = envint("XPRA_VERIFY_SOCKET_TIMEOUT", 1)
LIST_REPROBE_TIMEOUT: int = envint("XPRA_LIST_REPROBE_TIMEOUT", 10)
SPLASH_EXIT_DELAY: int = envint("XPRA_SPLASH_EXIT_DELAY", 4)

NO_NETWORK_SUBCOMMANDS = (
    "sbom",
    "splash", "root-size",
    "list", "list-windows", "list-mdns", "mdns-gui",
    "list-clients",
    "list-sessions", "sessions", "displays",
    "clean-displays", "clean-sockets", "clean",
    "xwait", "xinfo", "wminfo", "wmname",
    "xshm",
    "desktop-greeter", "gui", "start-gui",
    "docs", "documentation", "about", "html5",
    "pinentry", "input_pass", "_dialog", "_pass",
    "opengl", "opengl-probe", "opengl-test", "opengl-save",
    "autostart",
    "encoding", "video",
    "nvinfo", "webcam",
    "keyboard", "gtk-info", "gui-info", "network-info", "monitor-info",
    "compression", "packet-encoding", "path-info",
    "printing-info", "version-info", "version-check", "toolbox",
    "initenv", "setup-ssl", "show-ssl",
    "auth",
    "notify",
    "dbus-system-list", "dbus-session-list",
    "applications-menu", "sessions-menu",
    "_proxy",
    "configure", "showconfig", "showsetting", "setting", "set", "unset",
    "otp",
    "wait-for-x11", "wait-for-wayland",
    "xvfb-command", "xvfb",
)
STDOUT_SUBCOMMANDS = (
    "attach", "listen", "launcher",
    "sessions", "mdns-gui",
    "bug-report", "session-info", "docs", "documentation", "about", "license",
    "recover",
    "splash", "qrcode",
    "opengl-test",
    "desktop-greeter",
    "show-menu", "show-about", "show-session-info",
    "webcam",
    "showconfig",
    "root-size",
)
CLIENT_SUBCOMMANDS = (
    "attach", "listen", "detach",
    "screenshot", "version", "info", "id",
    "control", "run", "_monitor", "shell", "print",
    "qrcode",
    "show-menu", "show-about", "show-session-info",
    "connect-test",
    "record",
)
SERVER_SUBCOMMANDS = (
    "seamless", "desktop", "monitor", "expand", "shadow", "shadow-screen",
    "upgrade", "upgrade-seamless", "upgrade-desktop",
    "proxy",
    "encoder",
    "runner",
)
# pylint: disable=import-outside-toplevel
# noinspection PyBroadException


def nox() -> str:
    DISPLAY = os.environ.get("DISPLAY")
    if DISPLAY is not None:
        del os.environ["DISPLAY"]
    # This is an error on Fedora/RH, so make it an error everywhere
    # to ensure that it will be noticed:
    import warnings
    warnings.filterwarnings("error", "could not open display")
    return str(DISPLAY or "") or os.environ.get("WAYLAND_DISPLAY", "")


def reqx11(mode: str) -> None:
    if OSX:
        # need to import gtk module early, not sure why!
        import xpra.gtk.util
        assert xpra.gtk.util
    if find_spec("xpra.x11"):
        return
    if OSX or WIN32:
        raise InitExit(ExitCode.UNSUPPORTED, f"{mode} requires a build with the X11 bindings")
    raise InitExit(ExitCode.UNSUPPORTED, f"you must install `xpra-x11` to use {mode!r}")


def werr(*msg) -> None:
    for x in msg:
        stderr_print(str(x))


def error_handler(*args) -> NoReturn:
    raise InitException(*args)


def add_process(*args, **kwargs):
    from xpra.util.child_reaper import get_child_reaper
    return get_child_reaper().add_process(*args, **kwargs)


def get_logger() -> Logger:
    return Logger("util")


def main(cmdline: list[str]) -> int:
    return int(do_main(cmdline[0], cmdline))


def do_main(script_file: str, cmdline: list[str]) -> ExitValue:
    save_env()
    ml = envint("XPRA_MEM_USAGE_LOGGER")
    if ml > 0:
        from xpra.util.pysystem import start_mem_watcher
        start_mem_watcher(ml)

    if sys.flags.optimize > 0:  # pragma: no cover
        stderr_print("************************************************************")
        stderr_print(f"Warning: the python optimize flag is set to {sys.flags.optimize}")
        stderr_print(" xpra is very likely to crash")
        stderr_print("************************************************************")
        time.sleep(5)

    from xpra.platform import clean as platform_clean, command_error, command_info
    if len([arg for arg in cmdline if not arg.startswith("--")]) == 1:
        cmdline.append("gui")

    inject_debug_logging(cmdline)

    def debug_exc(msg: str = "run_mode error") -> None:
        get_logger().debug(msg, exc_info=True)

    try:
        defaults: XpraConfig = make_defaults_struct()
        fixup_defaults(defaults)
        options, args = do_parse_cmdline(cmdline, defaults)
        # `set_proc_title` is set here so that we can override the cmdline later
        # (don't ask me why this works - on OSX, it breaks the dock)
        if not OSX:
            set_proc_title(" ".join(cmdline))
        if not args:
            raise InitExit(-1, "xpra: need a mode")
        mode = args.pop(0)
        mode = MODE_ALIAS.get(mode, mode)

        return run_mode(script_file, cmdline, error_handler, options, args, mode, defaults)
    except SystemExit:
        debug_exc()
        raise
    except InitExit as e:
        debug_exc()
        if str(e) and e.args and (e.args[0] or len(e.args) > 1):
            command_info(str(e))
        return e.status
    except InitInfo as e:
        debug_exc()
        command_info(str(e))
        return 0
    except InitException as e:
        debug_exc()
        command_error(f"xpra initialization error:\n{e}")
        return 1
    except AssertionError as e:
        debug_exc()
        command_error(f"xpra initialization error:\n{e}")
        traceback.print_tb(sys.exc_info()[2])
        return 1
    except Exception:
        debug_exc()
        command_error("xpra main error:\n%s" % traceback.format_exc())
        return 1
    finally:
        platform_clean()
        clean_std_pipes()


def configure_logging(options, mode: str) -> None:
    to = sys.stdout if mode in STDOUT_SUBCOMMANDS else sys.stderr
    # a bit naughty here, but it's easier to let xpra.log initialize
    # the logging system every time, and just undo things here..
    from xpra.log import (
        setloghandler, enable_color, LOG_FORMAT, NOPREFIX_FORMAT,
        SIGPIPEStreamHandler,
    )
    setloghandler(SIGPIPEStreamHandler(to))
    if "XPRA_LOG_FORMAT" in os.environ or mode in (
            "seamless", "desktop", "monitor", "expand",
            "shadow", "shadow-screen",
            "encoder", "encode",
            "runner",
            "splash",
            "recover",
            "attach", "listen", "proxy", "gui",
            "version", "info", "id",
            "_audio_record", "_audio_play",
            "stop", "print", "showconfig", "configure", "sbom",
            "otp",
            "_dialog", "_pass",
            "pinentry",
            "opengl",
            "example",
    ) or mode.startswith("upgrade") or mode.startswith("request-"):
        if "help" in options.speaker_codec or "help" in options.microphone_codec:
            server_mode = mode not in ("attach", "listen")
            codec_help = show_audio_codec_help(server_mode, options.speaker_codec, options.microphone_codec)
            raise InitInfo("\n".join(codec_help))
        fmt = LOG_FORMAT
        if mode in ("stop", "showconfig", "version", "info", "id", "sbom"):
            fmt = NOPREFIX_FORMAT
        if envbool("XPRA_COLOR_LOG", hasattr(to, "fileno") and os.isatty(to.fileno())):
            enable_color(to, fmt)
        else:
            enable_format(fmt)

    from xpra.log import add_debug_category, add_disabled_category, enable_debug_for, disable_debug_for
    if options.debug:
        categories = [cat.strip() for cat in options.debug.split(",") if cat.strip()]
        for cat in categories:
            if not cat:
                continue
            if cat[0] == "-":
                add_disabled_category(cat[1:])
                disable_debug_for(cat[1:])
            else:
                add_debug_category(cat)
                enable_debug_for(cat)

    # always log debug level, we just use it selectively (see above)
    logging.root.setLevel(logging.INFO)


def configure_network(options) -> None:
    from xpra.net import compression, packet_encoding
    compression.init_compressors(*(list(options.compressors) + ["none"]))
    ecs = compression.get_enabled_compressors()
    if not ecs:
        # force compression level to zero since we have no compressors available:
        options.compression_level = 0
    packet_encoding.init_encoders(*list(options.packet_encoders) + ["none"])
    ees = set(packet_encoding.get_enabled_encoders())
    try:
        ees.remove("none")
    except KeyError:
        pass
    # verify that at least one real encoder is available:
    if not ees:
        raise InitException("at least one valid packet encoder must be enabled")


def configure_env(env_str) -> None:
    if env_str:
        env = parse_env(env_str)
        if POSIX and getuid() == 0:
            # running as root!
            # sanitize: only allow "safe" environment variables
            # as these may have been specified by a non-root user
            env = {k: v for k, v in env.items() if k.startswith("XPRA_")}
        os.environ.update(env)


def systemd_run_command(mode: str, systemd_run_args="", user: bool = True) -> list[str]:
    cmd = ["systemd-run", "--description", "xpra-%s" % mode, "--scope"]
    if user:
        cmd.append("--user")
    log_systemd_wrap = envbool("XPRA_LOG_SYSTEMD_WRAP", True)
    if not log_systemd_wrap:
        cmd.append("--quiet")
    if systemd_run_args:
        cmd += shlex.split(systemd_run_args)
    return cmd


def systemd_run_wrap(mode: str, args, systemd_run_args="", user: bool = True, **kwargs) -> int:
    cmd = systemd_run_command(mode, systemd_run_args, user)
    cmd += args
    cmd.append("--systemd-run=no")
    errwrite = getattr(sys.stderr, "write", noop)
    log_systemd_wrap = envbool("XPRA_LOG_SYSTEMD_WRAP", True)
    if log_systemd_wrap:
        noerr(errwrite, f"using systemd-run to wrap {mode!r} xpra server subcommand\n")
    log_systemd_wrap_command = envbool("XPRA_LOG_SYSTEMD_WRAP_COMMAND", False)
    if log_systemd_wrap_command:
        noerr(errwrite, "%s\n" % " ".join(["'%s'" % x for x in cmd]))
    try:
        with Popen(cmd, **kwargs) as p:
            return p.wait()
    except KeyboardInterrupt:
        return 128 + signal.SIGINT


def isdisplaytype(args, *dtypes) -> bool:
    if not args:
        return False
    d = args[0]
    return any(d.startswith(f"{dtype}/") or d.startswith(f"{dtype}:") for dtype in dtypes)


def set_gdk_backend() -> None:
    try:
        from xpra.x11.bindings.xwayland import isX11, isxwayland
    except ImportError:
        pass
    else:
        if os.environ.get("DISPLAY") and isX11():
            # we have an X11 display!
            if isxwayland():
                os.environ["GDK_BACKEND"] = "wayland"
            else:
                os.environ["GDK_BACKEND"] = "x11"
    if is_Wayland():
        os.environ["GDK_BACKEND"] = "wayland"


def set_pyopengl_platform() -> None:
    gdk_backend = os.environ.get("GDK_BACKEND", "")
    if gdk_backend == "x11":
        os.environ["PYOPENGL_PLATFORM"] = "x11"
    elif gdk_backend == "wayland":
        os.environ["PYOPENGL_PLATFORM"] = "egl"


def check_gtk_client() -> None:
    no_gtk()

    if POSIX and not OSX and not os.environ.get("GDK_BACKEND"):
        set_gdk_backend()

    if not os.environ.get("PYOPENGL_PLATFORM"):
        set_pyopengl_platform()

    check_gtk("client")

    try:
        find_spec("xpra.client.gui")
        find_spec("xpra.client.gtk3")
    except ImportError:
        raise InitExit(ExitCode.FILE_NOT_FOUND, "`xpra-client-gtk3` is not installed") from None


def gtk_init_check() -> bool:
    Gtk = gi_import("Gtk")
    if Gtk._version[0] > "3":
        r = Gtk.init_check()
    else:
        r = Gtk.init_check(argv=None)[0]
    return bool(r)


def check_gtk(mode: str) -> None:
    if not gtk_init_check():
        raise InitExit(ExitCode.NO_DISPLAY, f"{mode!r} failed to initialize Gtk, no display?")
    check_display()


def check_display() -> None:
    from xpra.platform.gui import can_access_display
    if not can_access_display():  # pragma: no cover
        raise InitExit(ExitCode.NO_DISPLAY, "cannot access display")


def use_systemd_run(s) -> bool:
    if not SYSTEMD_RUN or not POSIX or OSX:
        return False  # pragma: no cover
    systemd_run = parse_bool_or("systemd-run", s)
    if systemd_run in (True, False):
        return systemd_run
    # detect if we should use it:
    if os.environ.get("SSH_TTY") or os.environ.get("SSH_CLIENT"):  # pragma: no cover
        # would fail
        return False
    if not is_systemd_pid1():
        return False  # pragma: no cover
    # test it:
    cmd = ["systemd-run", "--quiet"]
    if getuid() != 0:
        cmd += ["--user"]
    cmd += ["--scope", "--", "true"]
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=False)
    try:
        proc.communicate(timeout=2)
        r = proc.returncode
    except TimeoutExpired:  # pragma: no cover
        r = None
    if r is None:
        stop_proc(proc, "systemd-run")
        if proc.poll() is None:
            try:
                proc.communicate(timeout=1)
            except TimeoutExpired:  # pragma: no cover
                r = None
    return r == 0


def verify_gir() -> None:
    try:
        from gi import repository
        assert repository
    except ImportError as e:
        raise InitExit(ExitCode.FAILURE, f"the python gobject introspection bindings are missing: \n{e}")


def run_mode(script_file: str, cmdline: list[str], error_cb: Callable, options, args: list[str], full_mode: str, defaults) -> ExitValue:
    mode_parts = full_mode.split(",")
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])

    # configure default logging handler:
    if POSIX and getuid() == options.uid == 0 and mode not in (
            "proxy", "autostart", "showconfig", "setup-ssl", "show-ssl", "sbom",
    ) and not NO_ROOT_WARNING:
        warn("\nWarning: running as root\n")

    display_is_remote = isdisplaytype(args, "ssh", "tcp", "ssl", "vsock", "hyperv", "quic")
    if mode.startswith("shadow") and WIN32 and not envbool("XPRA_PAEXEC_WRAP", False):
        # are we started from a non-interactive context?
        from xpra.platform.win32.gui import get_desktop_name
        if get_desktop_name() is None:
            argv = list(cmdline)
            exe = argv[0]
            if argv[0].endswith("Xpra_cmd.exe"):
                # we have to use the "interactive" version:
                argv[0] = exe.split("Xpra_cmd.exe", 1)[0] + "Xpra.exe"
            cmd = ["paexec", "-i", "1", "-s"] + argv
            try:
                with Popen(cmd) as p:
                    return p.wait()
            except KeyboardInterrupt:
                return 128 + signal.SIGINT
    if mode in (
            "seamless", "desktop", "shadow", "shadow-screen", "expand",
            "upgrade", "upgrade-seamless", "upgrade-desktop",
            "encoder", "runner",
    ) and not display_is_remote and options.daemon and use_systemd_run(options.systemd_run):
        # make sure we run via the same interpreter,
        # inject it into the command line if we have to:
        argv = list(cmdline)
        if argv[0].find("python") < 0:
            from xpra.platform.paths import get_python_execfile_command
            for arg in reversed(get_python_execfile_command()):
                argv.insert(0, arg)
        return systemd_run_wrap(mode, argv, options.systemd_run_args, user=getuid() != 0)
    configure_env(options.env)
    configure_logging(options, mode)
    if mode not in NO_NETWORK_SUBCOMMANDS:
        configure_network(options)
        verify_gir()

    xrd = os.environ.get("XDG_RUNTIME_DIR", "")
    if mode not in ("showconfig", "splash", "sbom") and POSIX and not OSX and not xrd and getuid() > 0:
        xrd = "/run/user/%i" % getuid()
        if os.path.exists(xrd):
            warn(f"Warning: using {xrd!r} as XDG_RUNTIME_DIR")
            os.environ["XDG_RUNTIME_DIR"] = xrd
        else:
            warn("Warning: XDG_RUNTIME_DIR is not defined")
            warn(f" and {xrd!r} does not exist")
            if os.path.exists("/tmp") and os.path.isdir("/tmp"):
                xrd = "/tmp"
                warn(f" using {xrd!r}")
                os.environ["XDG_RUNTIME_DIR"] = xrd

    if not mode.startswith("_audio_"):
        # audio commands don't want to set the name
        # (they do it later to prevent glib import conflicts)
        # "attach" does it when it received the session name from the server
        if mode not in (
                "attach", "listen",
                "seamless", "desktop", "shadow", "shadow-screen", "expand",
                "proxy",
        ) and not mode.startswith("upgrade"):
            from xpra.platform import set_name
            set_name("Xpra", "Xpra %s" % mode.strip("_"))

    if mode in (
            "seamless", "desktop", "shadow", "shadow-screen", "expand",
            "recover",
            "encoder",
    ) or mode.startswith("upgrade") or mode.startswith("request-"):
        options.encodings = validated_encodings(options.encodings)
    try:
        return do_run_mode(script_file, cmdline, error_cb, options, args, full_mode, defaults)
    except ValueError as e:
        info(f"{e}")
        return ExitCode.UNSUPPORTED
    except KeyboardInterrupt as e:
        info(f"\ncaught {e!r}, exiting")
        return 128 + signal.SIGINT


def DotXpra(*args, **kwargs):
    from xpra.platform import dotxpra
    return dotxpra.DotXpra(*args, **kwargs)


def do_run_mode(script_file: str, cmdline: list[str], error_cb: Callable, options, args: list[str], full_mode: str, defaults) -> ExitValue:
    mode_parts = full_mode.split(",", 1)
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])
    display_is_remote = isdisplaytype(args, "ssh", "tcp", "ssl", "vsock", "hyperv", "quic")
    if args and mode in ("seamless", "desktop", "monitor"):
        # all args that aren't specifying a connection will be interpreted as a start-child command:
        # ie: "xpra" "seamless" "xterm"
        # ie: "xpra" "desktop" "ssh://host/" "fluxbox"
        # and we also enable `exit-with-children` if unspecified
        commands = []
        connargs = []
        for arg in tuple(args):
            if is_connection_arg(arg):
                # keep this one
                connargs.append(arg)
            else:
                commands.append(arg)
        if commands:
            args = connargs
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
            for command in commands:
                options.start_child.append(command)
    if mode in ("seamless", "desktop", "monitor", "expand", "shadow", "shadow-screen"):
        if display_is_remote:
            # ie: "xpra start ssh://USER@HOST:SSHPORT/DISPLAY --start-child=xterm"
            return run_remote_server(script_file, cmdline, error_cb, options, args, mode, defaults)
        elif args and str_to_bool(options.attach, False):
            # maybe the server is already running,
            # and we don't need to bother trying to start it:
            try:
                display = pick_display(error_cb, options, args, cmdline)
            except Exception:
                pass
            else:
                dotxpra = DotXpra(options.socket_dir, options.socket_dirs)
                display_name = display.get("display_name")
                if display_name:
                    state = dotxpra.get_display_state(display_name)
                    if state == SocketState.LIVE:
                        get_logger().info(f"existing live display found on {display_name}, attaching")
                        # we're connecting locally, so no need for these:
                        options.csc_modules = ["none"]
                        options.video_decoders = ["none"]
                        return do_run_mode(script_file, cmdline, error_cb, options, args, "attach", defaults)

    if mode in SERVER_SUBCOMMANDS:
        return run_server(script_file, cmdline, error_cb, options, args, full_mode, defaults)
    if mode == "run" and args and args[0].startswith(":"):
        # for local displays, run via "_proxy_run"
        # which will use plain-X11 connections if needed:
        return run_proxy_run(error_cb, options, script_file, cmdline, args)
    if mode in CLIENT_SUBCOMMANDS or mode.startswith("request-"):
        return run_client(script_file, cmdline, error_cb, options, args, mode)
    if mode in ("stop", "exit"):
        no_gtk()
        return run_stopexit(mode, error_cb, options, args, cmdline)
    if mode == "top":
        no_gtk()
        return run_top(error_cb, options, args, cmdline)
    if mode == "encode":
        no_gtk()
        return run_encode(error_cb, options, args, cmdline)
    if mode == "list":
        no_gtk()
        return run_list(error_cb, options, args)
    if mode == "list-windows":
        no_gtk()
        return run_list_windows(error_cb, options, args)
    if mode == "list-clients":
        no_gtk()
        return run_list_clients(error_cb, options, args)
    if mode == "list-mdns":
        no_gtk()
        from xpra.net.mdns.list import run_list_mdns
        return run_list_mdns(error_cb, args)
    if mode == "mdns-gui":
        check_gtk_client()
        return run_mdns_gui(options)
    if mode == "list-sessions":
        no_gtk()
        return run_list_sessions(args, options)
    if mode == "sessions":
        check_gtk_client()
        return run_sessions_gui(options)
    if mode == "displays":
        no_gtk()
        return run_displays(options, args)
    if mode == "clean-displays":
        no_gtk()
        return run_clean_displays(options, args)
    if mode == "clean-sockets":
        no_gtk()
        return run_clean_sockets(options, args)
    if mode == "clean":
        no_gtk()
        return run_clean(options, args)
    if mode == "recover":
        return run_recover(script_file, cmdline, error_cb, options, args, defaults)
    if mode == "xwait":
        no_gtk()
        return run_xwait(args)
    if mode == "xshm":
        no_gtk()
        return run_xshm(args)
    if mode == "xinfo":
        no_gtk()
        return run_xinfo(args)
    if mode == "wminfo":
        no_gtk()
        return run_wminfo(args)
    if mode == "wmname":
        no_gtk()
        return run_wmname(args)
    if mode == "desktop-greeter":
        check_gtk_client()
        return run_desktop_greeter()
    if mode == "replay":
        from xpra.gtk.dialogs.replay import do_main as replay_main
        return replay_main(options)
    if mode == "launcher":
        check_gtk_client()
        from xpra.client.gtk3.launcher import main as launcher_main
        return launcher_main(["launcher.py"] + args)
    if mode == "gui":
        try:
            check_gtk_client()
        except InitExit as e:
            # the user likely called `xpra` from a non GUI session
            from xpra.platform import is_terminal
            if is_terminal():
                stderr_print("Error: cannot show the xpra gui")
                stderr_print(f" {e}")
                stderr_print(" you must use this subcommand from a desktop environment")
                stderr_print(" from a terminal session you can try `xpra list`, `xpra showconfig`, etc")
                return 1
            raise
        try:
            from xpra.gtk.dialogs import gui
            return gui.main(cmdline)
        except ImportError as e:
            warn(f"Warning: the xpra client gui component is not installed: {e}")
            run_help(script_file)
            return ExitCode.COMPONENT_MISSING
    if mode == "start-gui":
        check_gtk_client()
        from xpra.gtk.dialogs import start_gui
        return start_gui.main(options)
    if mode == "bug-report":
        check_gtk_client()
        from xpra.gtk.dialogs import bug_report
        return bug_report.main(["bug_report.py"] + args)
    if mode == "session-info":
        return run_session_info(error_cb, options, args, cmdline)
    if mode in ("docs", "documentation"):
        return run_docs()
    if mode == "about":
        return run_about()
    if mode == "license":
        from xpra.gtk.dialogs.about import load_license
        stderr_print(load_license())
        return 0
    if mode == "html5":
        return run_html5()
    if mode == "_proxy_run":
        nox()
        return run_proxy_run(error_cb, options, script_file, cmdline, args)
    if mode == "_proxy" or mode.startswith("_proxy_"):
        nox()
        return run_proxy(error_cb, options, script_file, cmdline, args, mode, defaults)
    if mode in ("_audio_record", "_audio_play", "_audio_query"):
        if not has_audio_support():
            error_cb("no audio support!")
        from xpra.audio.wrapper import run_audio
        return run_audio(mode, error_cb, args)
    if mode == "pinentry":
        check_gtk_client()
        from xpra.scripts.pinentry import run_pinentry
        return run_pinentry(args)
    if mode == "input_pass":
        check_gtk_client()
        from xpra.scripts.pinentry import input_pass
        password = input_pass((args + ["password"])[0])
        return len(password) > 0
    if mode == "_dialog":
        check_gtk_client()
        return run_dialog(args)
    if mode == "_pass":
        check_gtk_client()
        return run_pass(args)
    if mode == "send-file":
        check_gtk("send-file")
        return run_send_file(args)
    if mode == "qrcode":
        check_gtk("qrcode")
        return run_qrcode(args)
    if mode == "splash":
        check_gtk("splash")
        return run_splash(args)
    if mode == "opengl":
        from xpra.scripts.glprobe import run_glcheck
        return run_glcheck(options)
    if mode == "opengl-probe":
        check_gtk_client()
        from xpra.scripts.glprobe import run_glprobe
        return run_glprobe(options)
    if mode == "opengl-test":
        check_gtk_client()
        from xpra.scripts.glprobe import run_glprobe
        return run_glprobe(options, True)
    if mode == "opengl-save-probe":
        check_gtk_client()
        from xpra.scripts.glprobe import run_glsaveprobe
        return run_glsaveprobe()
    if mode == "example":
        check_gtk_client()
        from xpra.gtk.examples.run import run_example
        return run_example(args)
    if mode == "autostart":
        return run_autostart(script_file, args)
    if mode == "encoding":
        from xpra.codecs import loader
        return loader.main([script_file] + args)
    if mode in ("applications-menu", "sessions-menu"):
        from xpra.server.menu_provider import MenuProvider
        if mode == "applications-menu":
            data = MenuProvider().get_menu_data(remove_icons=True)
        else:
            data = MenuProvider().get_desktop_sessions(remove_icons=True)
        if not data:
            print("no menu data available")
            return ExitCode.FAILURE
        print_nested_dict(data)
        return ExitCode.OK
    if mode == "video":
        from xpra.codecs import video
        return video.main()
    if mode == "nvinfo":
        from xpra.codecs.nvidia import util
        return util.main()
    if mode == "webcam":
        check_gtk("webcam")
        from xpra.gtk.dialogs import show_webcam
        return show_webcam.main(["show_webcam.py"] + args)
    if mode == "webcam-client":
        check_gtk("webcam-client")
        if not args:
            error_cb("webcam-client requires a server URI")
        display_desc = parse_display_name(error_cb, options, args[0], cmdline)
        from xpra.client.gtk3.webcam_window import WebcamClient
        app = WebcamClient(display_desc)
        app.init(options)
        connect_to_server(app, display_desc, options)
        return do_run_client(app)
    if mode == "keyboard":
        from xpra.platform import keyboard
        return keyboard.main()
    if mode == "root-size":
        from xpra.gtk.util import get_root_size
        sys.stdout.write("%ix%i\n" % get_root_size((0, 0)))
        return ExitCode.OK
    if mode == "gtk-info":
        check_gtk("gtk-info")
        from xpra.gtk import info
        return info.main()
    if mode == "gui-info":
        check_gtk("gui-info")
        from xpra.platform import gui as platform_gui
        return platform_gui.main()
    if mode == "network-info":
        from xpra.net import net_util
        return net_util.main()
    if mode == "crypto-info":
        from xpra.net import crypto
        return crypto.main()
    if mode == "monitor-info":
        return run_monitor_info(options, args)
    if mode == "set-monitor":
        return run_set_monitor(options, args)
    if mode == "compression":
        from xpra.net import compression
        return compression.main()
    if mode == "packet-encoding":
        from xpra.net import packet_encoding
        return packet_encoding.main()
    if mode == "path-info":
        from xpra.platform import paths
        return paths.main()
    if mode == "printing-info":
        from xpra.platform import printing
        return printing.main(args)
    if mode == "version-info":
        from xpra.scripts import version
        return version.main()
    if mode == "version-check":
        return run_version_check(args)
    if mode == "toolbox":
        check_gtk_client()
        from xpra.gtk.dialogs import toolbox
        return toolbox.main(args)
    if mode == "initenv":
        if not BACKWARDS_COMPATIBLE:
            raise InitExit(ExitCode.UNSUPPORTED, "initenv is no longer supported")
        # legacy subcommand should be removed in v7
        if not POSIX:
            raise InitExit(ExitCode.UNSUPPORTED, "initenv is not supported on this OS")
        from xpra.server.runner_script import write_runner_shell_scripts
        from xpra.server.runner_script import xpra_runner_shell_script
        script = xpra_runner_shell_script(script_file, os.getcwd())
        write_runner_shell_scripts(script, False)
        return ExitCode.OK
    if mode == "setup-ssl":
        from xpra.net.tls.common import setup_ssl
        return setup_ssl(options, args, cmdline)
    if mode == "show-ssl":
        from xpra.net.tls.common import show_ssl
        return show_ssl(options, args, cmdline)
    if mode == "auth":
        return run_auth(options, args)
    if mode == "notify":
        return run_notify(options, args)
    if mode == "dbus-system-list":
        return run_dbus_system_list()
    if mode == "dbus-session-list":
        return run_dbus_session_list()
    if mode == "u2f":
        return run_u2f(args)
    if mode == "fido2":
        return run_fido2(args)
    if mode == "otp":
        return run_otp(args)
    if mode == "configure":
        from xpra.gtk.configure.main import main
        return main(args)
    if mode == "wait-for-x11":
        from xpra.x11.wait import main
        return main(args)
    if mode == "wait-for-wayland":
        from xpra.wayland.wait import main
        return main(args)
    if mode == "xvfb-command":
        fps = get_refresh_rate_for_value(options.refresh_rate, 60) if options.refresh_rate else 0
        print(shlex.join(xvfb_command(options.xvfb, options.pixel_depth, options.dpi, fps)))
        return ExitCode.OK
    if mode == "xvfb":
        if len(args) > 1:
            raise ValueError("too many arguments")
        display = "S" + str(os.getpid())
        if args:
            display = args[0]
            if not display.startswith(":"):
                raise ValueError(f"invalid display format {display!r}")
        fps = get_refresh_rate_for_value(options.refresh_rate, 60) if options.refresh_rate else 0
        xvfb_cmd = xvfb_command(options.xvfb, options.pixel_depth, options.dpi, fps)
        from xpra.x11.vfb_util import start_xvfb_standalone
        return start_xvfb_standalone(xvfb_cmd, options.sessions_dir, options.pixel_depth, fps, display, options.daemon)
    if mode == "sbom":
        return run_sbom(args)
    if mode == "showconfig":
        from xpra.scripts.settings import run_showconfig
        return run_showconfig(options, args)
    if mode == "showsetting":
        from xpra.scripts.settings import run_showsetting
        return run_showsetting(args)
    if mode in ("set", "setting"):
        from xpra.scripts.settings import run_setting
        return run_setting(True, args)
    if mode == "unset":
        from xpra.scripts.settings import run_setting
        return run_setting(False, args)
    if mode != "help":
        print(f"Invalid subcommand {mode!r}")
        try:
            from difflib import get_close_matches
            modes = tuple(usage.split(" ")[0] for usage in get_usage())
            matches = get_close_matches(mode, modes)
            if matches and len(matches) < 3:
                print(" did you mean %s?" % " or ".join(f"`xpra {match}`" for match in matches))
        except ImportError:
            # some builds don't have difflib, ie: MS Windows
            pass
    return run_help(script_file)


def run_help(script_file: str) -> int:
    print("Usage:")
    cmd = os.path.basename(script_file)
    for x in get_usage():
        print(f"\t{cmd} {x}")
    print()
    print("see 'man xpra' or 'xpra --help' for more details")
    return 1


def run_dialog(extra_args) -> ExitValue:
    from xpra.gtk.dialogs.confirm_dialog import show_confirm_dialog
    return show_confirm_dialog(extra_args)


def run_pass(extra_args) -> ExitValue:
    from xpra.gtk.dialogs.pass_dialog import show_pass_dialog
    return show_pass_dialog(extra_args)


def run_send_file(extra_args) -> ExitValue:
    sockpath = os.environ.get("XPRA_SERVER_SOCKET")
    if not sockpath:
        display = os.environ.get("DISPLAY", "")
        if display:
            uri = display
        else:
            raise InitException("cannot find xpra server to use")
    else:
        uri = f"socket://{sockpath}"
    if extra_args:
        files = extra_args
    else:
        from xpra.gtk.widget import choose_files
        files = choose_files(None, "Select Files to Transfer", multiple=True)
        if not files:
            return ExitCode.FAILURE
    filelog = Logger("file")
    from xpra.platform.paths import get_xpra_command
    xpra_cmd = get_xpra_command()
    errors = 0
    for f in files:
        filelog(f"run_send_file({extra_args}) sending {f!r}")
        if not os.path.isabs(f):
            f = os.path.abspath(f)
        # xpra control :10 send-file /path/to/the-file-to-send open CLIENT_UUID
        cmd = xpra_cmd + ["control", uri, "send-file", f]
        filelog(f"cmd={cmd}")
        proc = Popen(cmd, stdin=None, stdout=PIPE, stderr=PIPE)
        stdout, stderr = proc.communicate()
        if proc.returncode:
            filelog.error(f"Error: failed to send file {f!r}")

            def logfdoutput(v) -> None:
                if v:
                    try:
                        v = v.decode()
                    except UnicodeDecodeError:
                        pass
                    filelog.error(f" {v!r}")

            logfdoutput(stdout)
            logfdoutput(stderr)
            errors += 1
        else:
            filelog.info(f"sent {f!r}")
    if errors:
        return ExitCode.FAILURE
    return 0


def run_client(script_file, cmdline: list[str], error_cb, opts, extra_args: list[str], mode: str) -> ExitValue:
    if mode != "attach":
        opts.reconnect = False
    if mode in ("attach", "detach") and len(extra_args) == 1 and extra_args[0] == "all":
        # run this command for each display:
        dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
        displays = dotxpra.displays(check_uid=getuid(), matching_state=SocketState.LIVE)
        if not displays:
            sys.stdout.write("No xpra sessions found\n")
            return ExitCode.FILE_NOT_FOUND
        # we have to locate the 'all' command line argument,
        # so we can replace it with each display we find,
        # but some other command line arguments can take a value of 'all',
        # so we have to make sure that the one we find does not belong to the argument before
        index = None
        for i, arg in enumerate(cmdline):
            if i == 0 or arg != "all":
                continue
            prevarg = cmdline[i - 1]
            if prevarg[0] == "-" and (prevarg.find("=") < 0 or len(prevarg) == 2):
                # ie: [.., "--csc-modules", "all"] or [.., "-d", "all"]
                continue
            index = i
            break
        if not index:
            raise InitException("'all' command line argument could not be located")
        cmd = cmdline[:index] + cmdline[index + 1:]
        for display in displays:
            dcmd = cmd + [display] + ["--splash=no"]
            Popen(dcmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, close_fds=not WIN32)
        return ExitCode.OK
    app = get_client_app(cmdline, error_cb, opts, extra_args, mode)
    r = do_run_client(app)
    if opts.reconnect is not False and r in RETRY_EXIT_CODES:
        warn("%s, reconnecting" % exit_str(r))
        return exec_reconnect(script_file, cmdline)
    return r


def exec_reconnect(script_file: str, cmdline: list[str]) -> ExitCode:
    if is_debug_enabled("client"):
        log = Logger("client")
        log.info(f"reconnecting using script file {script_file!r}")
        log.info(f" and {cmdline=}")
    try:
        if WIN32:
            return win32_reconnect(script_file, cmdline)
        else:
            abs_script_file = os.path.abspath(script_file)
            os.execv(abs_script_file, cmdline)
    except FileNotFoundError:
        warn(f"failed to re-connect using {script_file!r}")
        return ExitCode.FAILURE


def win32_reconnect(script_file: str, cmdline: list[str]) -> ExitCode:
    # the cx_Freeze wrapper changes the cwd to the directory containing the exe,
    # so we have to re-construct the actual path to the exe:
    # see issue #4026
    # we have to extract the exe name then get an abs path for it:
    # so that someone running xpra using:
    # `Xpra-x86_64_6.0-r34669M\xpra_cmd" attach ...`
    # will still end up with a valid absolute path
    # when the exe wrapper changes directory to `Xpra-x86_64_6.0-r34669M`.
    if not os.path.isabs(script_file):
        script_file = os.path.join(os.getcwd(), os.path.basename(script_file))
    if not os.path.exists(script_file):
        # perhaps the extension is missing?
        if not os.path.splitext(script_file)[1]:
            for ext in os.environ.get("PATHEXT", ".COM;.EXE").split(os.path.pathsep):
                tmp = script_file + ext
                if os.path.exists(tmp):
                    script_file = tmp
    cmdline[0] = script_file
    if is_debug_enabled("client"):
        log = Logger("client")
        log(f"Popen(args={cmdline}, executable={script_file}")
    Popen(args=cmdline, executable=script_file)
    # we can't keep re-spawning ourselves without freeing memory,
    # so exit the current process with "no error":
    return ExitCode.OK


def connect_to_server(app, display_desc: dict[str, Any], opts) -> None:
    log = Logger("network")
    backend = opts.backend or "gtk"
    log("connect_to_server(%s, %s, ..) backend=%s", app, display_desc, backend)

    def direct_call(fn: Callable, *args) -> None:
        fn(*args)
    call = direct_call

    if backend in ("qt", "pyglet", "tk", ):

        def setup_connection() -> None:
            do_setup_connection()

    else:
        # on win32, we must run the main loop
        # before we can call connect()
        # because connect() may run a subprocess,
        # and Gdk locks up the system if the main loop is not running by then!
        def setup_connection() -> None:
            log("setup_connection() starting setup-connection thread")
            from xpra.util.thread import start_thread
            start_thread(do_setup_connection, "setup-connection", True)

        GLib = gi_import("GLib")
        call = GLib.idle_add

    def do_setup_connection() -> None:
        try:
            log("do_setup_connection() display_desc=%s", display_desc)
            conn = connect_or_fail(display_desc, opts)
            if not conn:
                raise RuntimeError("not connected")
            log("do_setup_connection() conn=%s", conn)
            # UGLY warning: connect_or_fail() will parse the display string,
            # which may change the username and password..
            app.username = opts.username or os.environ.get("XPRA_USERNAME", "")
            app.password = opts.password
            app.display = opts.display
            app.display_desc = display_desc
            protocol = app.make_protocol(conn)
            protocol.start()
        except InitInfo as e:
            log("do_setup_connection() display_desc=%s", display_desc, exc_info=True)
            werr("failed to connect:", f" {e}")
            call(app.quit, ExitCode.OK)
        except InitExit as e:
            retry = display_desc.get("retry", True)
            if not retry:
                from xpra.net.tls.socket import ssl_retry
                ssllog = Logger("ssl")
                mods = ssl_retry(e, opts.ssl_ca_certs)
                ssllog("do_setup_connection() ssl_retry(%s, %s)=%s", e, opts.ssl_ca_certs, mods)
                if mods:
                    display_desc["retry"] = True
                    display_desc.setdefault("ssl-options", {}).update(mods)
                    do_setup_connection()
                    return
            werr("Warning: failed to connect:", f" {e}")
            call(app.quit, e.status)
        except InitException as e:
            log("do_setup_connection() display_desc=%s", display_desc, exc_info=True)
            werr("Warning: failed to connect:", f" {e}")
            call(app.quit, ExitCode.CONNECTION_FAILED)
        except Exception as e:
            log.error("do_setup_connection() display_desc=%s", display_desc, exc_info=True)
            werr("Error: failed to connect:", f" {e}")
            call(app.quit, ExitCode.CONNECTION_FAILED)

    call(setup_connection)


# `run` mode may have to return a fake client "App" object with two methods:
class FakeClientApp:
    @staticmethod
    def run():
        return ExitCode.OK

    @staticmethod
    def cleanup():
        """ this fake client does not need to cleanup anything """


def get_client_app(cmdline: list[str], error_cb: Callable, opts, extra_args: list[str], mode: str):
    validate_encryption(opts)
    if not find_spec("xpra.client"):
        error_cb("`xpra-client` is not installed")

    def basic():
        from xpra.client.base import features
        features.file = features.printer = features.control = features.debug = False
        return features

    request_mode = mode.replace("request-", "") if mode.startswith("request-") else ""
    run_args = []
    if mode in (
            "info", "id", "connect-test", "control", "version", "detach",
            "show-menu", "show-about", "show-session-info",
    ) and extra_args:
        opts.socket_dirs += opts.client_socket_dirs or []
    if mode == "screenshot":
        basic()
        from xpra.client.base.command import ScreenshotXpraClient
        if not extra_args:
            error_cb("invalid number of arguments for screenshot mode")
        screenshot_filename = extra_args[0]
        extra_args = extra_args[1:]
        app = ScreenshotXpraClient(opts, screenshot_filename)
    elif mode == "info":
        basic()
        from xpra.client.base.command import InfoXpraClient
        extra_args, subsystems = split_display_arg(extra_args)
        app = InfoXpraClient(opts, subsystems)
    elif mode == "id":
        basic()
        from xpra.client.base.command import IDXpraClient
        app = IDXpraClient(opts)
    elif mode in ("show-menu", "show-about", "show-session-info"):
        basic()
        from xpra.client.base.command import RequestXpraClient
        app = RequestXpraClient(request=mode, opts=opts)
    elif mode == "connect-test":
        basic()
        from xpra.client.base.command import ConnectTestXpraClient
        app = ConnectTestXpraClient(opts)
    elif mode == "record":
        from xpra.client.base.features import set_client_features
        set_client_features(opts)
        basic()
        from xpra.client.base.record import RecordClient
        app = RecordClient(opts)
        opts.encoding = handle_client_encoding_option(app, opts.encoding)
        app.init(opts)
        if opts.splash:
            from xpra import __version__
            app.progress_process = make_progress_process(opts.session_name or "Xpra Recorder v%s" % __version__)
    elif mode == "_monitor":
        basic()
        from xpra.client.base.command import MonitorXpraClient
        app = MonitorXpraClient(opts)
    elif mode == "shell":
        basic()
        from xpra.client.base.command import ShellXpraClient
        app = ShellXpraClient(opts)
    elif mode == "control":
        basic()
        from xpra.client.base.command import ControlXpraClient
        if len(extra_args) < 1:
            error_cb("not enough arguments for 'control' mode, try 'help'")
        extra_args, args = split_display_arg(extra_args)
        app = ControlXpraClient(opts, args)
    elif mode == "run":
        basic()
        from xpra.client.base.command import RunClient
        if len(extra_args) < 1:
            error_cb("not enough arguments for 'run' mode, you must specify the command to execute")
        extra_args, run_args = split_display_arg(extra_args)
        app = RunClient(opts, run_args)
    elif mode == "print":
        basic()
        from xpra.client.base.command import PrintClient
        if len(extra_args) <= 1:
            error_cb("not enough arguments for 'print' mode")
        extra_args, args = split_display_arg(extra_args)
        app = PrintClient(opts, args)
    elif mode == "qrcode":
        basic()
        check_gtk("qrcode")
        from xpra.gtk.dialogs.qrcode_client import QRCodeClient
        app = QRCodeClient(opts)
    elif mode == "version":
        basic()
        from xpra.client.base.command import VersionXpraClient
        app = VersionXpraClient(opts)
    elif mode == "detach":
        basic()
        from xpra.client.base.command import DetachXpraClient
        app = DetachXpraClient(opts)
    elif request_mode and opts.attach is not True:
        basic()
        from xpra.client.base.command import RequestStartClient
        sns = get_start_new_session_dict(opts, request_mode, extra_args)
        extra_args = [f"socket:{opts.system_proxy_socket}"]
        app = RequestStartClient(opts)
        app.hello_extra = {"connect": False}
        app.start_new_session = sns
    else:
        app = get_client_gui_app(error_cb, opts, request_mode, extra_args, mode)
    try:
        if mode != "listen":
            may_show_progress(app, 60, "connecting to server")
        if mode != "attach" and not extra_args:
            # try to guess the server intended:
            server_socket = os.environ.get("XPRA_SERVER_SOCKET", "")
            if server_socket:
                extra_args = [f"socket://{server_socket}"]
        display_desc = do_pick_display(error_cb, opts, extra_args, cmdline)
        if len(extra_args) == 1 and opts.password:
            uri = extra_args[0]
            if uri in cmdline and opts.password in uri:
                # hide the password from the URI:
                i = cmdline.index(uri)
                # cmdline[i] = uri.replace(opts.password, "*"*len(opts.password))
                obsc_cmdline = list(cmdline)
                obsc_cmdline[i] = uri.replace(opts.password, "********")
                if not OSX:
                    set_proc_title(" ".join(obsc_cmdline))
        # use a custom proxy command for run mode:
        if mode == "run" and display_desc.get("type", "") == "ssh":
            # when using the ssh transport,
            # don't try to connect to a server using the xpra protocol which may not exist,
            # the ssh command will do what is needed by calling `_proxy_run`:
            display_desc["proxy_command"] = ["_proxy_run"]
            display_desc["display_as_args"] += run_args
            connect_or_fail(display_desc, opts)
            return FakeClientApp()
        else:
            connect_to_server(app, display_desc, opts)
    except ValueError as e:
        einfo = str(e) or type(e)
        may_show_progress(app, 100, f"error: {einfo}")
        app.cleanup()
        raise InitExit(ExitCode.FAILURE, f"invalid value: {einfo}")
    except Exception as e:
        einfo = str(e) or type(e)
        may_show_progress(app, 100, f"error: {einfo}")
        app.cleanup()
        raise
    return app


def get_client_gui_app(error_cb: Callable, opts, request_mode: str, extra_args: Sequence[str], mode: str):
    try:
        app = make_client(opts)
    except RuntimeError as e:
        log = get_logger()
        log("failed to create the client", exc_info=True)
        # exceptions at this point are still initialization exceptions
        msg = (e.args[0] if e.args else str(e)) or str(type(e))
        raise InitException(msg) from None
    may_show_progress(app, 30, "client configuration")
    try:
        app.init(opts)
        opts.encoding = handle_client_encoding_option(app, opts.encoding)

        def handshake_complete(*_args) -> None:
            may_show_progress(app, 100, "connection established")
            log = get_logger()
            try:
                p = app._protocol
                conn = p._conn
                if conn:
                    log.info("Attached to %s server at %s", p.TYPE, conn.target)
                    log.info(" (press Control-C to detach)\n")
            except AttributeError:
                return

        if hasattr(app, "after_handshake"):
            app.after_handshake(handshake_complete)
        may_show_progress(app, 40, "initializing user interface")
        app.init_ui(opts)
        may_show_progress(app, 50, "loading user interface")
        app.load()
        if request_mode:
            sns = get_start_new_session_dict(opts, request_mode, extra_args)
            extra_args = [f"socket:{opts.system_proxy_socket}"]
            app.hello_extra = {
                "start-new-session": sns,
                "connect": True,
            }
            # we have consumed the start[-child] options
            app.start_child_new_commands = []
            app.start_new_commands = []

        if mode == "listen":
            if extra_args:
                raise InitException("cannot specify extra arguments with 'listen' mode")
            enable_listen_mode(app, error_cb, opts)

    except Exception as e:
        may_show_progress(app, 100, f"failure: {e}")
        from xpra.constants import NotificationID
        body = str(e)
        if body.startswith("failed to connect to"):
            lines = body.split("\n")
            summary = "Xpra client %s" % lines[0]
            body = "\n".join(lines[1:])
        else:
            summary = "Xpra client failed to connect"
        may_notify_client(app, NotificationID.FAILURE, summary, body, icon_name="disconnected")  # pylint: disable=not-callable
        app.cleanup()
        raise
    return app


def handle_client_encoding_option(app, encoding: str) -> str:
    if encoding == "auto":
        encoding = ""
    if not encoding:
        return ""
    from xpra.client.base import features
    if not features.encoding:
        return ""
    einfo = ""
    encodings = list(app.get_encodings()) + ["auto", "stream"]
    err = encoding not in encodings
    ehelp = encoding == "help"
    if err and not ehelp:
        einfo = f"invalid encoding: {encoding}\n"
    if err or ehelp:
        from xpra.codecs.loader import encodings_help
        raise InitInfo(einfo + "%s xpra client supports the following encodings:\n * %s" %
                       (app.client_toolkit(), "\n * ".join(encodings_help(encodings))))
    return encoding


def enable_listen_mode(app, error_cb: Callable, opts):
    may_show_progress(app, 80, "listening for incoming connections")
    from xpra.net.socket_util import (
        setup_local_sockets, peek_connection,
        parse_bind_options, create_sockets, add_listen_socket, accept_connection,
        SocketListener, close_sockets,
    )
    from xpra.log import Logger
    bind_options = parse_bind_options(opts)
    sockets: list[SocketListener] = create_sockets(bind_options)
    # we don't have a display,
    # so we can't automatically create sockets:
    if "auto" in opts.bind:
        opts.bind.remove("auto")
    if opts.bind:
        from xpra.platform.info import get_username
        local_sockets = setup_local_sockets(opts.bind,
                                            opts.socket_dir, opts.socket_dirs, "",
                                            "", False,
                                            opts.mmap_group, opts.socket_permissions,
                                            get_username(), getuid(), getgid())
        sockets.update(local_sockets)

    def new_connection(listener: SocketListener, handle=0) -> bool:
        from xpra.util.thread import start_thread
        netlog = Logger("network")
        netlog("new_connection%s", (listener, handle))
        conn = accept_connection(listener)
        # start a new thread so that we can sleep doing IO in `peek_connection`:
        start_thread(handle_new_connection, f"handle new connection: {conn}", daemon=True, args=(conn,))
        return True

    def handle_new_connection(conn) -> None:
        # see if this is a redirection:
        netlog = Logger("network")
        line1 = peek_connection(conn)[1]
        netlog.debug(f"handle_new_connection({conn}) line1={line1!r}")
        if line1:
            uri = bytestostr(line1)
            for socktype in SOCKET_TYPES:
                if uri.startswith(f"{socktype}://"):
                    run_socket_cleanups()
                    netlog.info(f"connecting to {uri}")
                    display_desc = pick_display(error_cb, opts, [uri, ])
                    connect_to_server(app, display_desc, opts)
                    return
        app.idle_add(do_handle_connection, conn)

    def do_handle_connection(conn) -> None:
        protocol = app.make_protocol(conn)
        protocol.start()
        # stop listening for new connections:
        run_socket_cleanups()

    def run_socket_cleanups() -> None:
        close_sockets(sockets)

    for listener in sockets:
        add_listen_socket(listener, None, new_connection)
    # listen mode is special,
    # don't fall through to connect_to_server!
    may_show_progress(app, 90, "ready")


def make_progress_process(title="Xpra") -> Popen | None:
    # start the splash subprocess
    log = Logger("splash")
    env = get_exec_env()
    env["XPRA_LOG_PREFIX"] = "splash: "
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    if POSIX:
        display = get_saved_env_var("DISPLAY")
        if display:
            env["DISPLAY"] = display
    from xpra.platform.paths import get_nodock_command
    cmd = get_nodock_command() + ["splash"]
    debug_args = get_debug_args()
    if debug_args:
        cmd.append("--debug=%s" % (",".join(debug_args)))
    try:
        progress_process = Popen(cmd, stdin=PIPE, env=env)
        log("progress_process(%s, %s)=%s", cmd, env, progress_process)
    except OSError as e:
        werr("Error launching 'splash' subprocess", " %s" % e)
        return None
    # always close stdin when terminating the splash screen process:
    progress_process.saved_terminate = progress_process.terminate

    def terminate(*args) -> None:
        stdin = progress_process.stdin
        log("terminate%s stdin=%s", args, stdin)
        if stdin:
            progress_process.stdin = None
            noerr(stdin.close)
        progress_process.saved_terminate()
        setattr(progress_process, "terminate", progress_process.saved_terminate)

    # override Popen.terminate()
    setattr(progress_process, "terminate", terminate)

    def progress(pct: int, text: str) -> None:
        poll = progress_process.poll()
        log("progress(%s, %r) poll=%s", pct, text, poll)
        if poll is not None:
            return
        stdin = progress_process.stdin
        if stdin:
            stdin.write(("%i:%s\n" % (pct, text)).encode("latin1"))
            stdin.flush()
        if pct == 100:
            # it should exit on its own, but just in case:
            glib = gi_import("GLib")
            glib.timeout_add(SPLASH_EXIT_DELAY * 1000 + 500, terminate)

    progress_process.progress = progress

    add_process(progress_process, "splash", cmd, ignore=True, forget=True)
    progress(0, title)
    progress(10, "initializing")
    return progress_process


def _monitors_args(args: list[str]) -> tuple[str, str]:
    from xpra.log import consume_verbose_argv
    consume_verbose_argv(args, "screen", "randr")
    if not args:
        raise InitExit(ExitCode.FILE_NOT_FOUND, "monitor data is missing")
    jsondata = ""
    display = ""
    for arg in args:
        if arg.startswith(":"):
            if display:
                raise InitExit(ExitCode.FAILURE, "duplicated display on command line")
            display = arg
        else:
            if jsondata:
                raise InitExit(ExitCode.FAILURE, "duplicated monitor data on command line")
            jsondata = arg
    if not jsondata:
        raise InitExit(ExitCode.FAILURE, "missing JSON monitor data argument")
    display = display or os.environ.get("DISPLAY", "")
    if not display and not (WIN32 or OSX):
        raise InitExit(ExitCode.FAILURE, "missing display argument")
    return display, jsondata


def run_monitor_info(options, args: list[str]) -> int:
    # should we honour desktop scaling here?
    # parse_scaling(options.desktop_scaling, w, h)
    display, jsondata = _monitors_args(args)
    if display:
        from xpra.gtk.util import verify_gdk_display
        verify_gdk_display(display)
    import json
    from xpra.gtk.info import get_monitors_info
    monitors = get_monitors_info()
    data = adjust_monitor_refresh_rate(options.refresh_rate, monitors)
    minfo = json.dumps(data, indent="\t")
    if jsondata == "-":
        sys.stdout.write(minfo)
    else:
        with open(jsondata, "wb") as f:
            f.write(minfo.encode("utf8"))
    return 0


def run_set_monitor(options, args: list[str]) -> int:
    display, jsondata = _monitors_args(args)
    if jsondata == "-":
        mdata = sys.stdin.read()
    elif os.path.isfile(jsondata):
        mdata = load_binary_file(jsondata)
    else:
        # assume this is the json data:
        mdata = jsondata
    import json
    monitors = json.loads(mdata)
    mdef = validated_monitor_data(monitors)
    if not mdef:
        raise InitExit(ExitCode.FAILURE, "invalid monitor data")

    from xpra.util.parsing import adjust_monitor_refresh_rate
    mdef = adjust_monitor_refresh_rate(options.refresh_rate, mdef)

    from xpra.x11.bindings.display_source import set_display_name, init_display_source
    set_display_name(display)
    init_display_source()
    from xpra.x11.bindings.randr import RandRBindings
    from xpra.x11.error import xsync
    with xsync:
        RandRBindings().set_crtc_config(mdef)
    return 0


NOGI = ("Gtk", "Gdk", "GdkX11", "GdkPixbuf", "GtkosxApplication") if not OSX else ("GdkX11", )


def no_gi_gtk_modules(mods=NOGI) -> None:
    for mod in mods:
        mod_path = f"gi.repository.{mod}"
        if sys.modules.get(mod_path):
            raise RuntimeError(f"gi module {mod!r} is already loaded!")
        # noinspection PyTypeChecker
        sys.modules[mod_path] = None


def make_client(opts):
    backend = opts.backend or "gtk"
    BACKENDS = ("qt", "gtk", "pyglet", "tk", "win32", "auto")
    if backend == "qt":
        no_gi_gtk_modules()
        try:
            from xpra.client.qt6.client import make_client as make_qt6_client
            return make_qt6_client()
        except ImportError as e:
            get_logger().debug("importing qt6 client", backtrace=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the qt6 client component is missing: {e}") from None
    if backend == "pyglet":
        no_gi_gtk_modules()
        try:
            from xpra.client.pyglet.client import make_client as make_pyglet_client
            return make_pyglet_client()
        except ImportError as e:
            get_logger().debug("importing pyglet client", backtrace=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the pyglet client component is missing: {e}") from None
    if backend == "tk":
        no_gi_gtk_modules()
        try:
            from xpra.client.tk.client import make_client as make_tk_client
            return make_tk_client()
        except ImportError as e:
            get_logger().debug("importing tk client", backtrace=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the tk client component is missing: {e}") from None
    if backend == "win32":
        no_gi_gtk_modules()
        try:
            from xpra.client.win32.client import make_client as make_win32_client
            return make_win32_client()
        except ImportError as e:
            get_logger().debug("importing win32 client", backtrace=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the tk client component is missing: {e}") from None
    if backend not in ("gtk", "auto"):
        raise ValueError(f"invalid gui backend {backend!r}, must be one of: "+csv(BACKENDS))

    progress_process = None
    if opts.splash is not False:
        from xpra import __version__
        title = opts.session_name or "Xpra Client v%s" % __version__
        progress_process = make_progress_process(title)

    try:
        check_gtk_client()

        from xpra.platform.gui import init as gui_init
        gui_init()

        from xpra.client.base.features import set_client_features
        set_client_features(opts)

        from xpra.client.gtk3.client import XpraClient
        app = XpraClient()
        app.progress_process = progress_process

        if opts.opengl in ("probe", "nowarn"):
            may_show_progress(app, 20, "validating OpenGL configuration")
            from xpra.scripts.glprobe import run_opengl_probe, save_opengl_probe
            probe, probe_info = run_opengl_probe()
            glinfo = typedict(probe_info)
            safe = glinfo.boolget("safe", False)
            SAVE_OPENGL_PROBE = envbool("XPRA_SAVE_OPENGL_PROBE", not is_admin())
            if SAVE_OPENGL_PROBE:
                save_opengl_probe(safe)
            if opts.opengl == "nowarn":
                # just on or off from here on:
                opts.opengl = ["off", "on"][safe]
            else:
                opts.opengl = f"probe-{probe}"
            r = probe  # ie: "success"
            if glinfo:
                renderer = glinfo.strget("renderer")
                if renderer:
                    # ie: "AMD Radeon RX 570 Series (polaris10, LLVM 14.0.0, DRM 3.47, 5.19.10-200.fc36.x86_64)"
                    parts = renderer.split("(")
                    if len(parts) > 1 and len(parts[0]) > 10:
                        renderer = parts[0].strip()
                    else:
                        renderer = renderer.split(";", 1)[0]
                    r += f" ({renderer})"
            may_show_progress(app, 20, f"validating OpenGL: {r}")
            message = glinfo.strget("message")
            if message:
                may_show_progress(app, 21, f" {message}")

    except Exception:
        if progress_process:
            noerr(progress_process.terminate)
        raise
    return app


def do_run_client(app) -> ExitValue:
    try:
        return app.run()
    except KeyboardInterrupt:
        return -signal.SIGINT
    finally:
        app.cleanup()


def get_start_new_session_dict(opts, mode: str, extra_args) -> dict[str, Any]:
    sns = {
        "mode": mode,  # ie: "start-desktop"
    }
    if len(extra_args) == 1:
        sns["display"] = extra_args[0]
    from xpra.scripts.config import dict_to_config
    defaults = dict_to_config(get_defaults())
    fixup_options(defaults)
    for x in PROXY_START_OVERRIDABLE_OPTIONS:
        fn = x.replace("-", "_")
        v = getattr(opts, fn)
        dv = getattr(defaults, fn, None)
        if v and v != dv:
            sns[x] = v
    # make sure the server will start in the same path we were called from:
    # (despite being started by a root owned process from a different directory)
    if not opts.chdir:
        sns["chdir"] = os.getcwd()
    return sns


def match_client_display_size(options, display_is_remote=True) -> None:
    if options.resize_display.lower() != "auto":
        return
    # if possible, use the current display size as initial vfb size
    root_w, root_h = get_current_root_size(display_is_remote)
    if 0 < root_w < 16384 and 0 < root_h < 16384:
        scaling_x, scaling_y = parse_scaling(options.desktop_scaling, root_w, root_h)
        scaled_w = round(root_w / scaling_x)
        scaled_h = round(root_h / scaling_y)
        options.resize_display = f"{scaled_w}x{scaled_h}"


def run_server(script_file, cmdline: list[str], error_cb, options, args: list[str], full_mode: str, defaults) -> ExitValue:
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
            display_desc = pick_display(error_cb, options, args, cmdline)
        except (ValueError, InitException):
            pass
        else:
            dotxpra = DotXpra(options.socket_dir, options.socket_dirs)
            display = display_desc.get("display_name")
            if display:
                state = dotxpra.get_display_state(display)
                if state == SocketState.LIVE:
                    get_logger().info(f"existing live display found on {display}, attaching")
                    # we're connecting locally, so no need for these:
                    options.csc_modules = ["none"]
                    options.video_decoders = ["none"]
                    return do_run_mode(script_file, cmdline, error_cb, options, args, "attach", defaults)
    if mode == "seamless":
        match_client_display_size(options, display_is_remote)

    if mode not in ("encoder", "runner"):
        r = start_server_via_proxy(cmdline, error_cb, options, args, full_mode)
        if isinstance(r, int):
            return r

    try:
        from xpra import server
        assert server
        from xpra.scripts.server import do_run_server
        return do_run_server(script_file, cmdline, error_cb, options, args, full_mode, defaults)
    except ImportError:
        error_cb("`xpra-server` is not installed")
        sys.exit(1)


def get_current_root_size(display_is_remote: bool) -> tuple[int, int]:
    root_w = root_h = 0
    if display_is_remote or OSX or not POSIX:
        # easy path, just load gtk early:
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


# noinspection PySimplifyBooleanCheck
def start_server_via_proxy(cmdline, error_cb, options, args, mode: str) -> ExitValue | None:
    start_via_proxy = parse_bool_or("start-via-proxy", options.start_via_proxy)
    if start_via_proxy is False:
        return None
    if not options.daemon:
        if start_via_proxy is True:
            error_cb("cannot start-via-proxy without daemonizing")
        return None
    if POSIX and getuid() == 0:
        error_cb("cannot start via proxy for root")
        return None
    try:
        from xpra import client  # pylint: disable=import-outside-toplevel
        assert client
    except ImportError:
        if start_via_proxy is True:
            error_cb("cannot start-via-proxy: `xpra-client` is not installed")
        return None
    ################################################################################
    try:
        # this will use the client "start-new-session" feature,
        # to start a new session and connect to it at the same time:
        if not args:
            from xpra.net.constants import SYSTEM_PROXY_SOCKET
            args = [SYSTEM_PROXY_SOCKET]
        app = get_client_app(cmdline, error_cb, options, args, "request-%s" % mode)
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
        error_cb(f"failed to start-via-proxy: {err}")
        return None
    # warn and fall through to regular server start:
    warn(f"Warning: cannot use the system proxy for {mode!r} subcommand,")
    warn(f" {err}")
    warn(" more information may be available in your system log")
    return None


def run_remote_server(script_file: str, cmdline, error_cb, opts, args, mode: str, defaults) -> ExitValue:
    """ Uses the regular XpraClient with patched proxy arguments to tell run_proxy to start the server """
    if not args:
        raise RuntimeError("no remote server specified")
    display_name = args[0]
    params = parse_display_name(error_cb, opts, display_name, cmdline)
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
            v = getattr(opts, fn)
            if v:
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

        while True:
            try:
                conn = connect_or_fail(params, opts)
                app.make_protocol(conn)
                may_show_progress(app, 80, "connecting to server")
                break
            except InitExit as e:
                from xpra.net.tls.socket import ssl_retry
                mods = ssl_retry(e, opts.ssl_ca_certs)
                if mods:
                    for k, v in mods.items():
                        setattr(opts, f"ssl_{k}", v)
                    continue
                raise
    except Exception as e:
        if app:
            may_show_progress(app, 100, f"failure: {e}")
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


def run_autostart(script_file, args) -> ExitValue:
    def err(msg) -> int:
        print(msg)
        print(f"Usage: {script_file!r} autostart enable|disable|status")
        return 1

    if len(args) != 1:
        return err("invalid number of arguments")
    arg = args[0].lower()
    if arg not in ("enable", "disable", "status"):
        return err(f"invalid argument {arg!r}")
    if not POSIX or OSX:
        print("autostart is not supported on this platform")
        return 1
    from xpra.platform.autostart import set_autostart, get_status
    if arg == "status":
        print(get_status())
    else:
        set_autostart(arg == "enable")
    return 0


def run_qrcode(args) -> ExitValue:
    from xpra.gtk.dialogs import qrcode_client
    return qrcode_client.main(args)


def run_splash(args) -> ExitValue:
    from xpra.gtk.dialogs import splash
    return splash.main(args)


def start_macos_shadow(cmd, env, cwd) -> None:
    # launch the shadow server via launchctl,
    # so it can have GUI access:
    LAUNCH_AGENT = "org.xpra.Agent"
    LAUNCH_AGENT_FILE = f"/Library/LaunchAgents/{LAUNCH_AGENT}.plist"
    try:
        os.stat(LAUNCH_AGENT_FILE)
    except Exception as e:
        # ignore access denied error, launchctl runs as root
        import errno
        if e.args[0] != errno.EACCES:
            warn("Error: shadow may not start,\n"
                 f" the launch agent file {LAUNCH_AGENT_FILE!r} seems to be missing:{e}.\n")
    argfile = os.path.expanduser("~/.xpra/shadow-args")
    with open(argfile, "w", encoding="utf8") as f:
        f.write('["Xpra", "--no-daemon"')
        for x in cmd[1:]:
            f.write(f', "{x}"')
        f.write(']')
    launch_commands = [
        ["launchctl", "unload", LAUNCH_AGENT_FILE],
        ["launchctl", "load", "-S", "Aqua", LAUNCH_AGENT_FILE],
        ["launchctl", "start", LAUNCH_AGENT],
    ]
    log = get_logger()
    log("start_macos_shadow: launch_commands=%s", launch_commands)
    for x in launch_commands:
        Popen(x, env=env, cwd=cwd).wait()


def proxy_start_win32_shadow(script_file, args, opts, dotxpra, display_name) -> tuple[Any, str, str]:
    log = Logger("server")
    from xpra.platform.paths import get_app_dir
    app_dir = get_app_dir()
    cwd = app_dir
    env = os.environ.copy()
    exe = script_file
    cmd = []
    if envbool("XPRA_PAEXEC", True):
        # use paexec to access the GUI session:
        paexec = os.path.join(app_dir, "paexec.exe")
        if os.path.exists(paexec) and os.path.isfile(paexec):
            from xpra.platform.win32.wtsapi import find_session
            from xpra.platform.info import get_username
            username = get_username()
            session_info = find_session(username)
            if session_info:
                cmd = [
                    "paexec.exe",
                    "-i", str(session_info["SessionID"]), "-s",
                ]
                exe = paexec
                # don't show a cmd window:
                script_file = script_file.replace("Xpra_cmd.exe", "Xpra.exe")
            else:
                log("session not found for user '%s', not using paexec", username)
    cmd += [script_file, "shadow"] + args
    cmd += get_start_server_args(opts)
    debug_args = os.environ.get("XPRA_SHADOW_DEBUG")
    if debug_args is None:
        debug_args = ",".join(get_debug_args())
    if debug_args:
        cmd.append(f"--debug={debug_args}")
    log(f"proxy shadow start command: {cmd}")
    proc = Popen(cmd, executable=exe, env=env, cwd=cwd)
    start = monotonic()
    elapsed = 0.0
    while elapsed < WAIT_SERVER_TIMEOUT:
        state = dotxpra.get_display_state(display_name)
        if state == SocketState.LIVE:
            log("found live server '%s'", display_name)
            # give it a bit of time:
            # FIXME: poll until the server is ready instead
            time.sleep(1)
            return proc, f"named-pipe://{display_name}", display_name
        log(f"get_display_state({display_name})={state} (waiting)")
        if proc.poll() not in (None, 0):
            raise RuntimeError(f"shadow subprocess command returned {proc.returncode}")
        time.sleep(0.10)
        elapsed = monotonic() - start
    stop_proc(proc, "shadow server")
    raise RuntimeError(f"timeout: failed to identify the new shadow server {display_name!r}")


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

    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs, username, uid=uid, gid=gid)
    if WIN32:
        if not mode.startswith("shadow"):
            raise ValueError(f"invalid mode {mode!r} for MS Windows")
        assert display_name
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
            if not OSX and not matching_display:
                # use "--displayfd" switch to tell us which display was chosen:
                r_pipe, w_pipe = os.pipe()
                log("subprocess displayfd pipes: %s", (r_pipe, w_pipe))
                cmd.append(f"--displayfd={w_pipe}")
                pass_fds = (w_pipe,)
        log("start_server_subprocess: command=" + csv(repr(x) for x in cmd))
        proc = Popen(cmd, env=env, cwd=cwd, preexec_fn=preexec_fn, pass_fds=pass_fds)
        log(f"proc={proc}")
        add_process(proc, "server", cmd, ignore=True, forget=True)
        if r_pipe:
            from xpra.platform.displayfd import read_displayfd, parse_displayfd
            buf = read_displayfd(r_pipe, proc=None)  # proc daemonizes!
            noerr(os.close, r_pipe)
            noerr(os.close, w_pipe)

            def displayfd_err(msg: str) -> None:
                log.error("Error: displayfd failed")
                log.error(f" {msg}")

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


def run_proxy_run(error_cb: Callable, options, script_file: str, cmdline: list[str], args: list[str]) -> ExitValue:
    display_args, cmd_args = split_display_arg(args)
    # print(f"{display_args=} {cmd_args=}")

    def is_live(display: str) -> bool:
        dotxpra = DotXpra(options.socket_dir, options.socket_dirs)
        return dotxpra.get_display_state(display) == SocketState.LIVE

    try:
        display_desc = pick_display(error_cb, options, display_args, cmdline)
        # print(f"picked display: {display_desc}")
    except InitException:
        if display_args:
            # the display was specified, so we can't continue:
            raise
        display_desc = {}

    if not display_desc and not display_args:
        # try harder, maybe there is a single display that isn't managed by an xpra session:
        displays = get_displays_info(display_names=display_args if display_args else None,
                                     sessions_dir=options.sessions_dir)
        if len(displays) == 1:
            display_desc = tuple(displays.values())[0]

    display = display_desc.get("display_name", "") or display_desc.get("display", "")
    if not display:
        error_cb("unable to locate the display to run on")

    # now let's decide how to run the command on this display:
    if is_live(display):
        # found a live xpra socket, use the `xpra run` client:
        return run_client(script_file, cmdline, error_cb, options, args, "run")

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


def run_proxy(error_cb: Callable, opts, script_file: str, cmdline: list[str], args: list[str], mode: str, defaults) -> ExitValue:
    no_gtk()
    display = None
    display_name = None
    server_mode = {
        "_proxy": "seamless",
        "_proxy_shadow_start": "shadow",
    }.get(mode, mode.replace("_proxy_", "").replace("_", "-"))
    server_mode = MODE_ALIAS.get(server_mode, server_mode)
    if mode != "_proxy" and server_mode in ("seamless", "desktop", "monitor", "shadow", "shadow-screen", "expand"):
        attach = parse_bool_or("attach", opts.attach, None)
        state = None
        if attach is not False:
            # maybe this server already exists?
            dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
            if not args and server_mode in ("shadow", "shadow-screen", "expand"):
                try:
                    display_name = pick_shadow_display(args, sessions_dir=opts.sessions_dir)
                    args = [display_name]
                except Exception:
                    # failed to guess!
                    pass
            elif args:
                display = pick_display(error_cb, opts, args, cmdline)
                display_name = display.get("display")
            if display_name:
                state = dotxpra.get_display_state(display_name)
                if state != SocketState.DEAD:
                    stderr_print(f"found existing display {display_name} : {state}")
        if state != SocketState.LIVE:
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
            display = parse_display_name(error_cb, opts, uri, cmdline)
            if proc and proc.poll() is None:
                # start a thread just to reap server startup process (yuk)
                # (as the server process will exit as it daemonizes)
                from xpra.util.thread import start_thread
                start_thread(proc.wait, "server-startup-reaper")
    if not display:
        # use display specified on command line:
        display = pick_display(error_cb, opts, args, cmdline)
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
    server_conn = connect_or_fail(display, opts)
    from xpra.scripts.fdproxy import XpraProxy
    from xpra.net.bytestreams import TwoFileConnection
    pipe = TwoFileConnection(sys.stdout, sys.stdin, socktype="stdin/stdout")
    app = XpraProxy("xpra-pipe-proxy", pipe, server_conn)
    try:
        return app.run()
    finally:
        if delpath:
            noerr(os.unlink, delpath)


def show_final_state(error_cb, display_desc: dict[str, Any]) -> int:
    # this is for local sockets only!
    display = display_desc["display"]
    sockdir = display_desc.get("socket_dir", "")
    sockdirs = display_desc.get("socket_dirs", ())
    sockdir = DotXpra(sockdir, sockdirs)
    try:
        sockfile = get_sockpath(display_desc, error_cb, 0)
    except InitException:
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


def run_stopexit(mode: str, error_cb: Callable, opts, extra_args: list[str], cmdline: list[str]) -> ExitValue:
    assert mode in ("stop", "exit")
    no_gtk()

    def multimode(displays: list[str]) -> int:
        sys.stdout.write(f"Trying to {mode} {len(displays)} displays:\n")
        sys.stdout.write(" %s\n" % csv(displays))
        procs = []
        # ["xpra", "stop", ..]
        from xpra.platform.paths import get_nodock_command
        cmd = get_nodock_command() + [mode, f"--socket-dir={opts.socket_dir}"]
        for x in opts.socket_dirs:
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
        dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
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

    display_desc = pick_display(error_cb, opts, extra_args, cmdline)
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
        connect_to_server(app, display_desc, opts)
        e = app.run()
    except ImportError:
        sys.stderr.write(f"Error: unable to use the {mode!r} subcommand:\n")
        sys.stderr.write(" the 'xpra-client' component is not installed\n")
        return ExitCode.COMPONENT_MISSING
    finally:
        if app:
            app.cleanup()
    if e == 0:
        if display_desc["local"] and display_desc.get("display"):
            show_final_state(error_cb, display_desc)
        else:
            print(f"Sent {mode} command")
    return e


def run_top(error_cb: Callable, options, args: list[str], cmdline: list[str]) -> ExitValue:
    from xpra.client.base.top import TopClient, TopSessionClient
    if args:
        # try to show a specific session
        try:
            display_desc = pick_display(error_cb, options, args, cmdline)
        except Exception:
            pass
        else:
            # show the display we picked automatically:
            top_session = TopSessionClient(options)
            try:
                connect_to_server(top_session, display_desc, options)
                return top_session.run()
            except Exception:
                pass
    return TopClient(options).run()


def run_encode(error_cb: Callable, options, args: list[str], cmdline: list[str]) -> ExitValue:
    from xpra.client.base.features import set_client_features
    set_client_features(options)
    from xpra.client.base.encode import EncodeClient
    if not args:
        raise ValueError("please specify a display and at least one filename")
    display_desc = pick_display(error_cb, options, args[:1], cmdline)
    app = EncodeClient(options, args[1:])
    app.init(options)
    connect_to_server(app, display_desc, options)
    return app.run()


def run_session_info(error_cb: Callable, options, args: list[str], cmdline: list[str]) -> ExitValue:
    check_gtk_client()
    display_desc = pick_display(error_cb, options, args, cmdline)
    from xpra.gtk.dialogs.session_info import SessionInfoClient
    app = SessionInfoClient(options)
    connect_to_server(app, display_desc, options)
    return app.run()


def show_docs() -> None:
    def show_docs_thread() -> None:
        try:
            run_docs()
        except InitExit as e:
            stderr_print("Error: cannot show documentation")
            stderr_print(f" {e}")
    from xpra.util.thread import start_thread
    start_thread(show_docs_thread, "open documentation", True)


def run_docs() -> ExitValue:
    path = find_docs_path()
    if not path:
        raise InitExit(ExitCode.FILE_NOT_FOUND, "documentation not found!")
    return _browser_open_file(path)


def run_about() -> ExitValue:
    try:
        check_gtk_client()
    except InitExit:
        from xpra.platform import is_terminal
        if is_terminal():
            from xpra.util.version import XPRA_VERSION
            from xpra.gtk.dialogs import about
            from xpra.scripts.config import get_build_info

            stderr_print(f"Xpra {XPRA_VERSION}")
            stderr_print()
            for line in get_build_info():
                stderr_print(line)
            stderr_print()
            stderr_print("Main authors:")
            for author in about.MAIN_AUTHORS:
                stderr_print(f"- {author}")
            stderr_print()
            stderr_print("License: GPL2+")
            stderr_print("run `xpra license` to see the full license")
            stderr_print()
            stderr_print("For more information, see:")
            stderr_print(f"{about.SITE_URL}")
            return 0
        raise
    from xpra.gtk.dialogs import about
    return about.main()


def run_html5(url_options: str | dict = "") -> ExitValue:
    path = find_html5_path()
    if not path:
        raise InitExit(ExitCode.FILE_NOT_FOUND, "html5 client not found!")
    if url_options:
        from urllib.parse import urlencode
        path += "#" + urlencode(url_options)
    return _browser_open_file(path)


def _browser_open_file(file_path) -> ExitValue:
    import webbrowser
    webbrowser.open_new_tab(f"file://{file_path}")
    return 0


def run_desktop_greeter() -> ExitValue:
    from xpra.gtk.dialogs import desktop_greeter
    return desktop_greeter.main()


def run_sessions_gui(options) -> ExitValue:
    mdns = options.mdns
    if mdns and not find_spec("xpra.net.mdns"):
        mdns = False
    if mdns:
        from xpra.net.mdns import get_listener_class
        listener = get_listener_class()
        if listener:
            from xpra.gtk.dialogs import mdns_gui
            return mdns_gui.do_main(options)
        else:
            warn("Warning: no mDNS support")
            warn(" only local sessions will be shown")
    from xpra.gtk.dialogs import sessions_gui
    return sessions_gui.do_main(options)


def run_mdns_gui(options) -> ExitValue:
    from xpra.net.mdns import get_listener_class
    listener = get_listener_class()
    if not listener:
        raise InitException("sorry, 'mdns-gui' is not supported on this platform yet")
    from xpra.gtk.dialogs import mdns_gui
    return mdns_gui.do_main(options)


def run_clean(opts, args: Iterable[str]) -> ExitValue:
    no_gtk()
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
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
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
    no_gtk()
    matching_display = None
    if args:
        if len(args) == 1:
            matching_display = args[0]
        else:
            raise InitInfo("too many arguments for 'clean' mode")
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs + opts.client_socket_dirs)
    results = dotxpra.socket_details(check_uid=getuid(),
                                     matching_state=SocketState.UNKNOWN,
                                     matching_display=matching_display)
    if matching_display and not results:
        raise InitInfo(f"no UNKNOWN socket for display {matching_display!r}")
    clean_sockets(dotxpra, results)
    return ExitCode.OK


def run_recover(script_file: str, cmdline: list[str], error_cb: Callable, options, args: list[str], defaults) -> ExitValue:
    if not POSIX or OSX:
        raise InitExit(ExitCode.UNSUPPORTED, "the 'xpra recover' subcommand is not supported on this platform")
    no_gtk()
    display_descr: dict = {}
    ALL = len(args) == 1 and args[0].lower() == "all"
    if not ALL and len(args) == 1:
        try:
            display_descr = pick_display(error_cb, options, args, cmdline)
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
    return run_server(script_file, cmdline, error_cb, options, args, mode, defaults)


def run_displays(options, args) -> ExitValue:
    # dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs+opts.client_socket_dirs)
    displays = get_displays_info(display_names=args if args else None, sessions_dir=options.sessions_dir)
    print(f"Found {len(displays)} displays:")
    if args:
        print(" matching " + csv(args))
    SHOW = {
        "xwayland": "XWayland",
        "xpra-server-mode": "mode",
        "uid": "uid",
        "gid": "gid",
    }
    for display, descr in displays.items():
        state = descr.pop("state", "LIVE")
        info_str = ""
        wmname = descr.get("wmname")
        if wmname:
            info_str += f"{wmname}: "

        def show(name: str, value) -> str:
            if value is True:
                return name
            return f"{name}={value}"

        info_str += csv(show(v, descr.get(k)) for k, v in SHOW.items() if k in descr)
        print("%10s    %-8s    %s" % (display, state, info_str))
    return 0


def run_clean_displays(options, args) -> ExitValue:
    if not POSIX or OSX:
        raise InitExit(ExitCode.UNSUPPORTED, "clean-displays is not supported on this platform")
    displays = get_displays_info(sessions_dir=options.sessions_dir)
    dead_displays = tuple(display for display, descr in displays.items() if descr.get("state") == "DEAD")
    if not dead_displays:
        print("No dead displays found")
        if args:
            print(" matching %s" % csv(args))
        return 0
    # now find the processes that own these dead displays:
    display_pids = get_display_pids(*dead_displays)
    if not display_pids:
        print("No pids found for dead displays " + csv(sorted_nicely(dead_displays)))
        if args:
            print(" matching %s" % csv(args))
        return ExitCode.FILE_NOT_FOUND
    print("Found %i dead display pids:" % len(display_pids))
    if args:
        print(" matching %s" % csv(args))
    for display, (pid, cmd) in sorted_nicely(display_pids.items()):
        print("%4s    %-8s    %s" % (display, pid, cmd))
    print()
    WAIT = 5
    print(f"These displays will be forcibly terminated in {WAIT} seconds")
    print("Press Control-C to abort")
    for _ in range(WAIT):
        sys.stdout.write(".")
        sys.stdout.flush()
        time.sleep(1)
    for display, (pid, cmd) in display_pids.items():
        try:
            os.kill(pid, signal.SIGINT)
        except OSError as e:
            print(f"Unable to send SIGINT to {pid}: {e}")
    print("")
    print("Done")
    return 0


def display_wm_info(args) -> dict[str, Any]:
    reqx11("wminfo")
    if not find_spec("xpra.x11") or not find_spec("xpra.x11.gtk"):
        raise InitExit(ExitCode.UNSUPPORTED, "wminfo is not supported on this platform")
    no_gtk()
    if len(args) == 1:
        os.environ["DISPLAY"] = args[0]
    elif not args and os.environ.get("DISPLAY"):
        # just use the current one
        pass
    else:
        raise InitExit(ExitCode.NO_DISPLAY, "you must specify a display")
    with OSEnvContext(GDK_BACKEND="x11"):
        from xpra.x11.gtk.display_source import init_gdk_display_source
        init_gdk_display_source()
        from xpra.x11.wm_check import get_wm_info
        info = get_wm_info()
        gdk = gi_import("Gdk")
        display = gdk.Display.get_default()
        info["display"] = display.get_name()
        return info


def run_xshm(args) -> ExitValue:
    if not find_spec("xpra.x11"):
        raise RuntimeError("xshm subcommand is not supported on this platform")
    no_gtk()
    if len(args) == 1:
        os.environ["DISPLAY"] = args[0]
    elif not args and os.environ.get("DISPLAY"):
        # just use the current one
        pass
    else:
        raise InitExit(ExitCode.NO_DISPLAY, "you must specify a display")
    with OSEnvContext(GDK_BACKEND="x11"):
        from xpra.x11.bindings.display_source import init_display_source
        init_display_source()
        from xpra.x11.bindings.core import get_root_xid
        from xpra.x11.bindings.shm import XShmBindings
        XShm = XShmBindings()
        xshm = XShm.has_XShm()
        if xshm:
            # try to use it:
            rxid = get_root_xid()
            w = XShm.get_XShmWrapper(rxid)
            if w:
                res = w.setup()
                if not res[0]:
                    warn("XShm access failed")
                    xshm = False
            else:
                warn(f"failed to create XShm wrapper for root window {rxid:x}")
                xshm = False
        else:
            warn("XShm extension is not available")
        return ExitCode.OK if xshm else ExitCode.UNSUPPORTED


def run_xwait(args) -> ExitValue:
    from xpra.x11.bindings.xwait import main as xwait_main  # pylint: disable=no-name-in-module
    xwait_main(args)
    return 0


def run_xinfo(args) -> ExitValue:
    from xpra.x11.bindings.info import main as xinfo_main  # pylint: disable=no-name-in-module
    return xinfo_main(args)


def run_wminfo(args) -> ExitValue:
    for k, v in display_wm_info(args).items():
        print(f"{k}={v}")
    return 0


def run_wmname(args) -> ExitValue:
    name = display_wm_info(args).get("wmname", "")
    if name:
        print(name)
    return 0


def run_dbus_system_list() -> ExitValue:
    import dbus
    for service in dbus.SystemBus().list_names():
        print(service)
    return 0


def run_dbus_session_list() -> ExitValue:
    import dbus
    for service in dbus.SessionBus().list_names():
        print(service)
    return 0


def run_notify(_options, args) -> ExitValue:
    if not args:
        raise InitException("specify notification text")
    title = args[0]
    body = args[1] if len(args) >= 2 else ""
    from xpra.notification.dbus_backend import DBUSNotifier, log
    log.enable_debug()
    notifier = DBUSNotifier()
    notifier.app_name_format = "%s"
    actions = ()  # ("0", "Hello", "1", "Goodbye")
    hints = {
        "image-path": "/usr/share/xpra/icons/encoding.png",
    }
    nid = int(monotonic()) % 2**16
    notifier.show_notify("dbus-id", None, nid, "xpra test app", 0, "",
                         title, body,
                         actions, hints, 60*1000, None)
    nid += 1
    from gi.repository import GLib  # @UnresolvedImport
    loop = GLib.MainLoop()
    GLib.timeout_add(5 * 1000, loop.quit)
    loop.run()
    return 0


def run_auth(_options, args) -> ExitValue:
    if not args:
        raise InitException("missing module argument")
    auth_str = args[0]
    from xpra.auth.auth_helper import get_auth_module
    auth, auth_module = get_auth_module(auth_str)[:2]
    # see if the module has a "main" entry point:
    main_fn = getattr(auth_module, "main", None)
    if not main_fn:
        raise InitExit(ExitCode.UNSUPPORTED, f"no command line utility for {auth!r} authentication module")
    argv = [auth_module.__file__] + args[1:]
    return main_fn(argv)


def run_u2f(args: list[str]) -> ExitValue:
    from xpra.gtk.dialogs.u2f_tool import main
    return main(["u2f_tool.py"] + args)


def run_fido2(args: list[str]) -> ExitValue:
    from xpra.gtk.dialogs.fido2_tool import main
    return main(["fido2_tool.py"] + args)


def run_otp(args: list[str]) -> ExitValue:
    from xpra.gtk.dialogs.otp import main
    return main(args)


def run_version_check(args) -> ExitValue:
    if gtk_init_check():
        check_display()
        from xpra.gtk.dialogs import update_status
        return update_status.main(args)
    # text version:
    from xpra.util.version import get_latest_version, get_branch
    version = get_latest_version()
    branch = get_branch()
    vstr = ".".join(str(x) for x in version)
    branch_info = f" for {branch} branch" if branch not in ("", "master") else ""
    print(f"latest version{branch_info} is v{vstr}")
    return 0


def err(*args) -> NoReturn:
    raise InitException(*args)


def run_sbom(args: list[str]) -> ExitValue:
    from xpra import build_info
    if not (WIN32 or OSX):
        print("please refer to your package manager")
        return ExitCode.UNSUPPORTED
    sbom = getattr(build_info, "sbom", {})
    if not sbom:
        raise RuntimeError("the sbom is missing!")
    print(f"# {len(sbom)} path entries:")
    if args:
        sbom = {k:v for k, v in sbom.items() if any(k.find(arg) >= 0 for arg in args)}
    for path, package_info in sbom.items():
        package = package_info["package"]
        version = package_info["version"]
        print(f"{path!r:60}: {package:48} {version}")
    print("")
    packages = getattr(build_info, "packages", {})
    if not packages:
        raise RuntimeError("the packages list is missing!")
    if args:
        packages = {k:v for k, v in packages.items() if any(k.find(arg) >= 0 for arg in args)}
    print(f"# {len(packages)} packages:")
    for package, pinfo in packages.items():
        print(f"{package}:")
        for key, value in pinfo.items():
            print(f"    {key:16}: {value}")
    return ExitCode.OK


if __name__ == "__main__":  # pragma: no cover
    code = do_main("xpra.exe", sys.argv)
    if not code:
        code = 0
    sys.exit(code)
