#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import sys
import os.path
import stat
import glob
import socket
import time
import logging
from math import ceil
from time import monotonic
from importlib import import_module
from importlib.util import find_spec

from shutil import rmtree, which
from subprocess import Popen, PIPE, TimeoutExpired, run
import signal
import shlex
import traceback
from typing import Any, NoReturn
from collections.abc import Callable, Iterable

from xpra.common import SocketState, noerr, noop
from xpra.util.objects import typedict
from xpra.util.str_fn import nonl, csv, print_nested_dict, pver, sorted_nicely, bytestostr, sort_human, is_valid_hostname
from xpra.util.env import envint, envbool, osexpand, save_env, get_exec_env, OSEnvContext
from xpra.util.parsing import parse_scaling
from xpra.util.thread import set_main_thread
from xpra.exit_codes import ExitCode, ExitValue, RETRY_EXIT_CODES, exit_str
from xpra.os_util import (
    getuid, getgid, get_username_for_uid, force_quit,
    gi_import,
    WIN32, OSX, POSIX
)
from xpra.util.io import is_socket, stderr_print, use_tty, info, warn, error
from xpra.util.system import is_Wayland, SIGNAMES, set_proc_title, is_systemd_pid1
from xpra.scripts.parsing import (
    get_usage,
    parse_display_name, parse_env,
    fixup_defaults,
    validated_encodings, validate_encryption, do_parse_cmdline, show_audio_codec_help,
    MODE_ALIAS, REVERSE_MODE_ALIAS,
)
from xpra.scripts.config import (
    XpraConfig,
    OPTION_TYPES, TRUE_OPTIONS, FALSE_OPTIONS, OFF_OPTIONS, ALL_BOOLEAN_OPTIONS,
    NON_COMMAND_LINE_OPTIONS, CLIENT_ONLY_OPTIONS, CLIENT_OPTIONS,
    START_COMMAND_OPTIONS, BIND_OPTIONS, PROXY_START_OVERRIDABLE_OPTIONS, OPTIONS_ADDED_SINCE_V5, OPTIONS_COMPAT_NAMES,
    InitException, InitInfo, InitExit,
    fixup_options,
    find_docs_path, find_html5_path,
    dict_to_validated_config, get_xpra_defaults_dirs, get_defaults, read_xpra_conf,
    make_defaults_struct, str_to_bool, parse_bool_or, has_audio_support, name_to_field,
    xvfb_command,
)
from xpra.net.common import (
    DEFAULT_PORTS, SOCKET_TYPES, AUTO_ABSTRACT_SOCKET, ABSTRACT_SOCKET_PREFIX,
    verify_hyperv_available,
)
from xpra.log import is_debug_enabled, Logger, get_debug_args

assert callable(error), "used by modules importing this function from here"

NO_ROOT_WARNING: bool = envbool("XPRA_NO_ROOT_WARNING", False)
WAIT_SERVER_TIMEOUT: int = envint("WAIT_SERVER_TIMEOUT", 90)
CONNECT_TIMEOUT: int = envint("XPRA_CONNECT_TIMEOUT", 20)
OPENGL_PROBE_TIMEOUT: int = envint("XPRA_OPENGL_PROBE_TIMEOUT", 5)
SYSTEMD_RUN: bool = envbool("XPRA_SYSTEMD_RUN", True)
VERIFY_SOCKET_TIMEOUT: int = envint("XPRA_VERIFY_SOCKET_TIMEOUT", 1)
LIST_REPROBE_TIMEOUT: int = envint("XPRA_LIST_REPROBE_TIMEOUT", 10)


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


def werr(*msg) -> None:
    for x in msg:
        stderr_print(str(x))


def error_handler(*args) -> NoReturn:
    raise InitException(*args)


def add_process(*args, **kwargs):
    from xpra.util.child_reaper import getChildReaper
    return getChildReaper().add_process(*args, **kwargs)


def get_logger() -> Logger:
    return Logger("util")


def main(script_file: str, cmdline) -> ExitValue:
    set_main_thread()
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

    def debug_exc(msg: str = "run_mode error") -> None:
        get_logger().debug(msg, exc_info=True)

    try:
        defaults: XpraConfig = make_defaults_struct()
        fixup_defaults(defaults)
        options, args = do_parse_cmdline(cmdline, defaults)
        # `set_proc_title` is set here so that we can override the cmdline later
        # (don't ask me why this works)
        if OSX:
            set_proc_title("Xpra")
        else:
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


def clean_std_pipes() -> None:
    if not envbool("XPRA_CLEAN_STD_PIPES", True):
        return

    def closestd(std) -> None:
        if std:
            try:
                std.close()
            except OSError:  # pragma: no cover
                pass
    closestd(sys.stdout)
    closestd(sys.stderr)


def configure_logging(options, mode) -> None:
    if mode in (
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
    ):
        to = sys.stdout
    else:
        to = sys.stderr
    # a bit naughty here, but it's easier to let xpra.log initialize
    # the logging system every time, and just undo things here..
    from xpra.log import (
        setloghandler, enable_color, enable_format,
        LOG_FORMAT, NOPREFIX_FORMAT,
        SIGPIPEStreamHandler,
    )
    setloghandler(SIGPIPEStreamHandler(to))
    if mode in (
            "seamless", "desktop", "monitor", "expand",
            "shadow", "shadow-screen",
            "encoder", "encode",
            "recover",
            "attach", "listen", "proxy",
            "version", "info", "id",
            "_audio_record", "_audio_play",
            "stop", "print", "showconfig", "configure", "sbom",
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
        categories = options.debug.split(",")
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


def systemd_run_command(mode, systemd_run_args=None, user: bool = True) -> list[str]:
    cmd = ["systemd-run", "--description", "xpra-%s" % mode, "--scope"]
    if user:
        cmd.append("--user")
    log_systemd_wrap = envbool("XPRA_LOG_SYSTEMD_WRAP", True)
    if not log_systemd_wrap:
        cmd.append("--quiet")
    if systemd_run_args:
        cmd += shlex.split(systemd_run_args)
    return cmd


def systemd_run_wrap(mode: str, args, systemd_run_args=None, user: bool = True, **kwargs) -> int:
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

    check_gtk()

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


def check_gtk() -> None:
    if not gtk_init_check():
        raise InitExit(ExitCode.NO_DISPLAY, "failed to initialize Gtk, no display?")
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
        try:
            proc.terminate()
        except Exception:
            pass
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


def run_mode(script_file: str, cmdline, error_cb, options, args, full_mode: str, defaults) -> ExitValue:
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
            "encoder",
    ) and not display_is_remote and options.daemon and use_systemd_run(options.systemd_run):
        # make sure we run via the same interpreter,
        # inject it into the command line if we have to:
        argv = list(cmdline)
        if argv[0].find("python") < 0:
            major, minor = sys.version_info.major, sys.version_info.minor
            python = which("python%i.%i" % (major, minor)) or which("python%i" % major) or which("python") or "python"
            argv.insert(0, python)
        return systemd_run_wrap(mode, argv, options.systemd_run_args, user=getuid() != 0)
    configure_env(options.env)
    configure_logging(options, mode)
    if mode not in (
            "sbom",
            "splash", "root-size",
            "list", "list-windows", "list-mdns", "mdns-gui",
            "list-clients",
            "list-sessions", "sessions", "displays",
            "clean-displays", "clean-sockets", "clean",
            "xwait", "wminfo", "wmname",
            "desktop-greeter", "gui", "start-gui",
            "docs", "documentation", "about", "html5",
            "pinentry", "input_pass", "_dialog", "_pass",
            "opengl", "opengl-probe", "opengl-test",
            "autostart",
            "encoding", "video",
            "nvinfo", "webcam",
            "keyboard", "gtk-info", "gui-info", "network-info",
            "compression", "packet-encoding", "path-info",
            "printing-info", "version-info", "version-check", "toolbox",
            "initenv", "setup-ssl", "show-ssl",
            "auth",
            "applications-menu", "sessions-menu",
            "_proxy",
            "configure", "showconfig", "showsetting", "setting", "set", "unset",
            "wait-for-x11", "wait-for-wayland",
            "xvfb-command", "xvfb",
    ):
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


def is_connection_arg(arg) -> bool:
    if POSIX and (arg.startswith(":") or arg.startswith("wayland-")):
        return True
    if any(arg.startswith(f"{mode}://") for mode in SOCKET_TYPES):
        return True
    if any(arg.startswith(f"{mode}:") for mode in SOCKET_TYPES):
        return True
    if any(arg.startswith(f"{mode}/") for mode in SOCKET_TYPES):
        return True
    # could be a plain TCP address, specifying a display,
    # ie: 127.0.0.1:0 or SOMEHOST:0.0
    parts = arg.split(":")
    if len(parts) == 2:
        host, display = parts
        if is_valid_hostname(host) and display.replace(".", "").isdigit():
            # this is a valid connection argument
            return True
    return False


def is_terminal() -> bool:
    from xpra.platform import is_terminal as ist
    return ist()


def DotXpra(*args, **kwargs):
    from xpra.platform import dotxpra
    return dotxpra.DotXpra(*args, **kwargs)


def do_run_mode(script_file: str, cmdline, error_cb, options, args, full_mode: str, defaults) -> ExitValue:
    mode_parts = full_mode.split(",", 1)
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])
    display_is_remote = isdisplaytype(args, "ssh", "tcp", "ssl", "vsock", "hyperv", "quic")
    if args and mode in ("seamless", "desktop", "monitor"):
        # all args that aren't specifying a connection will be interpreted as a start-child command:
        # ie: "xpra" "start" "xterm"
        # ie: "xpra" "start-desktop" "ssh://host/" "fluxbox"
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

    if mode in (
            "seamless", "desktop", "monitor", "expand", "shadow", "shadow-screen",
            "upgrade", "upgrade-seamless", "upgrade-desktop",
            "proxy",
            "encoder",
    ):
        return run_server(script_file, cmdline, error_cb, options, args, full_mode, defaults)
    if mode in (
            "attach", "listen", "detach",
            "screenshot", "version", "info", "id",
            "control", "_monitor", "shell", "print",
            "qrcode",
            "show-menu", "show-about", "show-session-info",
            "connect-test",
    ) or mode.startswith("request-"):
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
    if mode == "wminfo":
        no_gtk()
        return run_wminfo(args)
    if mode == "wmname":
        no_gtk()
        return run_wmname(args)
    if mode == "desktop-greeter":
        check_gtk_client()
        return run_desktop_greeter()
    if mode == "launcher":
        check_gtk_client()
        from xpra.client.gtk3.launcher import main as launcher_main
        return launcher_main(["xpra"] + args)
    if mode == "gui":
        try:
            check_gtk_client()
        except InitExit as e:
            # the user likely called `xpra` from a non GUI session
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
            return ExitCode.COMPONENT_MISSING
    if mode == "start-gui":
        check_gtk_client()
        from xpra.gtk.dialogs import start_gui
        return start_gui.main(options)
    if mode == "bug-report":
        check_gtk_client()
        from xpra.gtk.dialogs import bug_report
        return bug_report.main(["xpra"] + args)
    if mode == "session-info":
        return run_session_info(error_cb, options, args, cmdline)
    if mode in ("docs", "documentation"):
        return run_docs()
    if mode == "about":
        try:
            check_gtk_client()
        except InitExit:
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
    if mode == "license":
        from xpra.gtk.dialogs.about import load_license
        stderr_print(load_license())
        return 0
    if mode == "html5":
        return run_html5()
    if mode == "_proxy" or mode.startswith("_proxy_"):
        nox()
        return run_proxy(error_cb, options, script_file, cmdline, args, mode, defaults)
    if mode in ("_audio_record", "_audio_play", "_audio_query"):
        if not has_audio_support():
            error_cb("no audio support!")
        from xpra.audio.wrapper import run_audio
        return run_audio(mode, error_cb, options, args)
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
        check_gtk()
        return run_send_file(args)
    if mode == "splash":
        check_gtk()
        return run_splash(args)
    if mode == "opengl":
        return run_glcheck(options)
    if mode == "opengl-probe":
        check_gtk_client()
        return run_glprobe(options)
    if mode == "opengl-test":
        check_gtk_client()
        return run_glprobe(options, True)
    if mode == "example":
        check_gtk_client()
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
        check_gtk()
        from xpra.gtk.dialogs import show_webcam
        return show_webcam.main()
    if mode == "keyboard":
        from xpra.platform import keyboard
        return keyboard.main()
    if mode == "root-size":
        from xpra.gtk.util import get_root_size
        sys.stdout.write("%ix%i\n" % get_root_size((0, 0)))
        return ExitCode.OK
    if mode == "gtk-info":
        check_gtk()
        from xpra.gtk import info
        return info.main()
    if mode == "gui-info":
        check_gtk()
        from xpra.platform import gui as platform_gui
        return platform_gui.main()
    if mode == "network-info":
        from xpra.net import net_util
        return net_util.main()
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
        if not POSIX:
            raise InitExit(ExitCode.UNSUPPORTED, "initenv is not supported on this OS")
        from xpra.server.util import xpra_runner_shell_script, write_runner_shell_scripts
        script = xpra_runner_shell_script(script_file, os.getcwd())
        write_runner_shell_scripts(script, False)
        return ExitCode.OK
    if mode == "setup-ssl":
        return setup_ssl(options, args, cmdline)
    if mode == "show-ssl":
        return show_ssl(options, args, cmdline)
    if mode == "auth":
        return run_auth(options, args)
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
        print(shlex.join(xvfb_command(options.xvfb, options.pixel_depth, options.dpi)))
        return ExitCode.OK
    if mode == "xvfb":
        if len(args) > 1:
            raise ValueError("too many arguments")
        display = "S" + str(os.getpid())
        if args:
            display = args[0]
            if not display.startswith(":"):
                raise ValueError(f"invalid display format {display!r}")
        xvfb_cmd = xvfb_command(options.xvfb, options.pixel_depth, options.dpi)
        from xpra.x11.vfb_util import start_xvfb_standalone
        return start_xvfb_standalone(xvfb_cmd, options.sessions_dir, options.pixel_depth, display)
    if mode == "sbom":
        return run_sbom(args)
    if mode == "showconfig":
        return run_showconfig(options, args)
    if mode == "showsetting":
        return run_showsetting(args)
    if mode in ("set", "setting"):
        return run_setting(True, args)
    if mode == "unset":
        return run_setting(False, args)
    # unknown subcommand:
    if mode != "help":
        print(f"Invalid subcommand {mode!r}")
    print("Usage:")
    if not POSIX or OSX:
        print("(this xpra installation does not support starting local servers)")
    cmd = os.path.basename(script_file)
    for x in get_usage():
        print(f"\t{cmd} {x}")
    print()
    print("see 'man xpra' or 'xpra --help' for more details")
    return 1


def find_session_by_name(opts, session_name: str) -> str:
    from xpra.platform.paths import get_nodock_command
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
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


def display_desc_to_uri(display_desc: dict[str, Any]) -> str:
    dtype = display_desc.get("type")
    if not dtype:
        raise InitException("missing display type")
    uri = f"{dtype}://"
    username = display_desc.get("username")
    if username is not None:
        uri += username
    password = display_desc.get("password")
    if password is not None:
        uri += ":" + password
    if username is not None or password is not None:
        uri += "@"
    if dtype in ("ssh", "tcp", "ssl", "ws", "wss", "quic"):
        # TODO: re-add 'proxy_host' arguments here
        host = display_desc.get("host")
        if not host:
            raise InitException("missing host from display parameters")
        uri += host
        port = display_desc.get("port")
        if port and port != DEFAULT_PORTS.get(dtype):
            uri += f":{port:d}"
        elif dtype == "vsock":
            cid, iport = display_desc["vsock"]
            uri += f"{cid}:{iport}"
        elif dtype == "hyperv":
            vmid, service = display_desc["hyperv"]
            uri += f"{vmid}:{service}"
    else:
        raise NotImplementedError(f"{dtype} is not implemented yet")
    uri += "/" + display_desc_to_display_path(display_desc)
    return uri


def display_desc_to_display_path(display_desc: dict[str, Any]) -> str:
    uri = ""
    path = display_desc.get("path")
    if path:
        uri += path
    display = display_desc.get("display")
    if display:
        if path:
            uri += "#"
        uri += display.lstrip(":")
    options_str = display_desc.get("options_str")
    if options_str:
        uri += f"?{options_str}"
    return uri


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


def pick_display(error_cb, opts, extra_args, cmdline=()) -> dict[str, Any]:
    if len(extra_args) == 1 and extra_args[0].startswith("vnc"):
        vnc_display = pick_vnc_display(error_cb, extra_args[0])
        if vnc_display:
            return vnc_display
        # if not, then fall through and hope that the xpra server supports vnc:
    return do_pick_display(error_cb, opts, extra_args, cmdline)


def do_pick_display(error_cb, opts, extra_args, cmdline=()) -> dict[str, Any]:
    dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
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


# noinspection PyPackageRequirements
def proxy_connect(options: dict):
    # if is_debug_enabled("proxy"):
    # log = logging.getLogger(__name__)
    try:
        # noinspection PyPackageRequirements
        import socks
    except ImportError as e:
        raise ValueError(f"cannot connect via a proxy: {e}") from None
    to = typedict(options)
    ptype = to.strget("proxy-type")
    proxy_type = {
        "SOCKS5": socks.SOCKS5,
        "SOCKS4": socks.SOCKS4,
        "HTTP": socks.HTTP,
    }.get(ptype, socks.SOCKS5)
    if not proxy_type:
        raise InitExit(ExitCode.UNSUPPORTED, f"unsupported proxy type {ptype!r}")
    host = to.strget("proxy-host")
    port = to.intget("proxy-port", 1080)
    rdns = to.boolget("proxy-rdns", True)
    username = to.strget("proxy-username")
    password = to.strget("proxy-password")
    timeout = to.intget("timeout", CONNECT_TIMEOUT)
    sock = socks.socksocket()
    sock.set_proxy(proxy_type, host, port, rdns, username, password)
    sock.settimeout(timeout)
    sock.connect((host, port))
    return sock


def retry_socket_connect(options: dict):
    host = options["host"]
    port = options["port"]
    dtype = options["type"]
    if "proxy-host" in options:
        return proxy_connect(options)
    from xpra.net.socket_util import socket_connect
    start = monotonic()
    retry = options.get("retry", True) in TRUE_OPTIONS
    quiet = options.get("quiet", False)
    retry_count = 0
    timeout = options.get("timeout", CONNECT_TIMEOUT)
    while True:
        sock = socket_connect(host, port, timeout=timeout)
        if sock:
            return sock
        if not retry:
            break
        if monotonic() - start >= timeout:
            break
        if not quiet and retry_count == 0:
            log = Logger("network")
            log.info("")
            log.info(f"failed to connect to {dtype}://{host}:{port}/")
            log.info(f" retrying for {timeout} seconds")
            log.info("")
        retry_count += 1
        time.sleep(1)
    raise InitExit(ExitCode.CONNECTION_FAILED, f"failed to connect to {dtype} socket {host}:{port}")


def get_host_target_string(display_desc: dict, port_key="port", prefix="") -> str:
    dtype = display_desc["type"]
    username = display_desc.get(prefix + "username", "")
    host = display_desc[prefix + "host"]
    try:
        port = int(display_desc.get(prefix + port_key))
        if not 0 < port < 2 ** 16:
            port = 0
    except (ValueError, TypeError):
        port = 0
    display = display_desc.get(prefix + "display", "")
    return host_target_string(dtype, username, host, port, display)


def host_target_string(dtype: str, username: str, host: str, port: int, display: str = "") -> str:
    target = f"{dtype}://"
    if username:
        target += f"{username}@"
    target += host
    default_port = DEFAULT_PORTS.get(dtype, 0)
    if port and port != default_port:
        target += f":{port}"
    if display and display.startswith(":"):
        display = display[1:]
    target += "/%s" % (display or "")
    return target


def connect_to(display_desc: dict[str, Any], opts, debug_cb=noop, ssh_fail_cb=noop):
    from xpra.net.bytestreams import SOCKET_TIMEOUT, VSOCK_TIMEOUT, SocketConnection
    display_name = display_desc["display_name"]
    timeout = display_desc.get("timeout", SOCKET_TIMEOUT)
    dtype = display_desc["type"]
    if dtype in ("ssh", "vnc+ssh"):
        if display_desc.get("is_paramiko", False):
            from xpra.net.ssh import paramiko_client
            conn = paramiko_client.connect_to(display_desc)
        else:
            from xpra.net.ssh import exec_client
            conn = exec_client.connect_to(display_desc, opts, debug_cb, ssh_fail_cb)
        if dtype == "vnc+ssh":
            conn.socktype = "vnc"
            conn.socktype_wrapped = "ssh"
        return conn

    if dtype == "socket":
        if not hasattr(socket, "AF_UNIX"):  # pragma: no cover
            raise InitExit(ExitCode.UNSUPPORTED, "unix domain sockets are not available on this operating system")

        def sockpathfail_cb(msg) -> NoReturn:
            raise InitException(msg)

        sockpath = ""
        sock = None
        if display_name and not display_desc.get("socket_path") and AUTO_ABSTRACT_SOCKET:
            # see if we can just connect to the abstract socket if one exists:
            from xpra.platform.dotxpra import strip_display_prefix
            sockpath = "@" + ABSTRACT_SOCKET_PREFIX + strip_display_prefix(display_name)
            actual_path = "\0" + sockpath[1:] if sockpath.startswith("@") else sockpath
            sock = socket.socket(socket.AF_UNIX)
            sock.settimeout(1.0)
            try:
                sock.connect(actual_path)
            except OSError:
                get_logger().debug(f"failed to connect to abstract socket {sockpath}")
                noerr(sock.close)
                sock = None
        if not sock:
            sockpath = get_sockpath(display_desc, sockpathfail_cb)
            display_desc["socket_path"] = sockpath
            actual_path = "\0" + ABSTRACT_SOCKET_PREFIX + sockpath[1:] if sockpath.startswith("@") else sockpath
            sock = socket.socket(socket.AF_UNIX)
            sock.settimeout(timeout)
            start = monotonic()
            while monotonic() - start < timeout:
                try:
                    sock.connect(actual_path)
                    break
                except ConnectionRefusedError as e:
                    elapsed = monotonic() - start
                    get_logger().debug("%s, retrying %i < %i", e, elapsed, timeout)
                    time.sleep(0.5)
                    continue
                except Exception as e:
                    get_logger().debug(f"failed to connect using {sock.connect}({sockpath})", exc_info=True)
                    noerr(sock.close)
                    raise InitExit(ExitCode.CONNECTION_FAILED, f"failed to connect to {sockpath!r}:\n {e}") from None
        try:
            sock.settimeout(None)
            conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), display_name, dtype)
            conn.timeout = timeout
            target = "socket://"
            username = display_desc.get("username")
            if username:
                target += f"{username}@"
            target += sockpath
            conn.target = target
            return conn
        except OSError:
            noerr(sock.close)
            raise

    if dtype == "named-pipe":  # pragma: no cover
        pipe_name = display_desc["named-pipe"]
        if not WIN32:
            raise InitException("named pipes are only supported on MS Windows")
        import errno
        from xpra.platform.win32.dotxpra import PIPE_PATH, PIPE_ROOT
        from xpra.platform.win32.namedpipes.connection import NamedPipeConnection, connect_to_namedpipe
        if pipe_name.startswith(PIPE_ROOT):
            # absolute pipe path already specified
            path = pipe_name
        else:
            path = PIPE_PATH + pipe_name
        try:
            pipe_handle = connect_to_namedpipe(path)
        except Exception as e:
            try:
                if e.args[0] == errno.ENOENT:
                    raise InitException(f"the named pipe {pipe_name!r} does not exist: {e}") from None
            except AttributeError:
                pass
            raise InitException(f"failed to connect to the named pipe {pipe_name!r}:\n {e}") from None
        conn = NamedPipeConnection(pipe_name, pipe_handle, {})
        conn.timeout = timeout
        conn.target = f"namedpipe://{pipe_name}/"
        return conn

    if dtype == "vsock":
        cid, iport = display_desc["vsock"]
        from xpra.net.vsock.vsock import (  # pylint: disable=no-name-in-module
            connect_vsocket,
            CID_TYPES, CID_ANY, PORT_ANY,
        )
        sock = connect_vsocket(cid=cid, port=iport)
        sock.settimeout(None)
        conn = SocketConnection(sock, "local", "host", (CID_TYPES.get(cid, cid), iport), dtype)
        conn.timeout = VSOCK_TIMEOUT
        conn.target = "vsock://%s:%s" % (
            "any" if cid == CID_ANY else cid,
            "any" if iport == PORT_ANY else iport,
        )
        return conn

    if dtype == "hyperv":
        vmid, service = display_desc["hyperv"]
        verify_hyperv_available()
        sock = socket.socket(socket.AF_HYPERV, socket.SOCK_STREAM, socket.HV_PROTOCOL_RAW)
        sock.connect((vmid, service))
        sock.settimeout(None)
        conn = SocketConnection(sock, "local", "host", (vmid, service), dtype)
        conn.timeout = VSOCK_TIMEOUT
        conn.target = f"hyperv://{vmid}.{service}"
        return conn

    if dtype == "quic":
        host = display_desc["host"]
        port = display_desc["port"]
        path = "/" + display_desc.get("display", "")
        ssl_options = display_desc.get("ssl-options", {})
        ssl_server_verify_mode = ssl_options.get("server-verify-mode", opts.ssl_server_verify_mode)
        ssl_ca_certs = ssl_options.get("ca-certs", opts.ssl_ca_certs)
        ssl_cert = ssl_options.get("cert", opts.ssl_cert)
        ssl_key = ssl_options.get("key", opts.ssl_key)
        ssl_key_password = ssl_options.get("key-password", opts.ssl_key_password)
        ssl_server_name = ssl_options.get("server-hostname")
        try:
            from xpra.net.quic.client import quic_connect
            import aioquic
            assert aioquic
        except ImportError as e:
            raise InitExit(ExitCode.SOCKET_CREATION_ERROR, f"cannot use quic sockets: {e}") from None
        conn = quic_connect(host, port, path,
                            ssl_cert, ssl_key, ssl_key_password,
                            ssl_ca_certs, ssl_server_verify_mode, ssl_server_name)
        return conn

    if dtype in ("tcp", "ssl", "ws", "wss", "vnc"):
        sock = retry_socket_connect(display_desc)
        # use non-blocking until the connection is finalized
        sock.settimeout(0.1)
        conn = SocketConnection(sock, sock.getsockname(), sock.getpeername(), display_name,
                                dtype, socket_options=display_desc)

        if dtype in ("ssl", "wss"):
            raw_sock = sock
            from xpra.net.ssl_util import ssl_handshake, ssl_wrap_socket
            # convert option names to function arguments:
            ssl_options = {k.replace("-", "_"): v for k, v in display_desc.get("ssl-options", {}).items()}
            try:
                sock = ssl_wrap_socket(sock, **ssl_options)
            except ValueError as e:
                raise InitExit(ExitCode.SSL_FAILURE, f"ssl setup failed: {e}")
            if not sock:
                raise RuntimeError(f"failed to wrap socket {raw_sock} as {dtype!r}")
            ssl_handshake(sock)
            conn._socket = sock
            conn.timeout = timeout

        # wrap in a websocket:
        if dtype in ("ws", "wss"):
            host = display_desc["host"]
            port = display_desc.get("port", 0)
            # do the websocket upgrade and switch to binary
            try:
                from xpra.net.websockets.common import client_upgrade
            except ImportError as e:  # pragma: no cover
                raise InitExit(ExitCode.UNSUPPORTED, f"cannot handle websocket connection: {e}") from None
            else:
                display_path = display_desc_to_display_path(display_desc)
                client_upgrade(conn.read, conn.write, host, port, display_path)
        conn.target = get_host_target_string(display_desc)
        return conn
    raise InitException(f"unsupported display type: {dtype}")


def run_dialog(extra_args) -> ExitValue:
    from xpra.gtk.dialogs.confirm_dialog import show_confirm_dialog
    return show_confirm_dialog(extra_args)


def run_pass(extra_args) -> ExitValue:
    from xpra.gtk.dialogs.pass_dialog import show_pass_dialog
    return show_pass_dialog(extra_args)


def run_send_file(extra_args) -> ExitValue:
    sockpath = os.environ.get("XPRA_SERVER_SOCKET")
    if not sockpath:
        display = os.environ.get("DISPLAY")
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
    dotxpra = DotXpra(
        display_desc.get("socket_dir"),
        display_desc.get("socket_dirs"),
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
                werr(f"server socket for display {display} is in {SocketState.UNKNOWN} state")
            else:
                werr(f"server socket for display {display} not found")
            werr(f" waiting up to {timeout} seconds")
            start = monotonic()
            log = Logger("network")
            while monotonic() - start < timeout:
                state = dotxpra.get_display_state(display)
                log(f"get_display_state({display})={state}")
                if state in (SocketState.LIVE, SocketState.INACCESSIBLE):
                    # found a final state
                    break
                time.sleep(0.1)
            dir_servers = socket_details()
    return single_display_match(dir_servers, error_cb,
                                nomatch=f"cannot find live server for display {display}")[-1]


def run_client(script_file, cmdline, error_cb, opts, extra_args, mode: str) -> ExitValue:
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


def exec_reconnect(script_file: str, cmdline) -> ExitCode:
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


def win32_reconnect(script_file: str, cmdline) -> ExitCode:
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
            app.username = opts.username
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
                from xpra.net.ssl_util import ssl_retry
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


def get_client_app(cmdline, error_cb, opts, extra_args, mode: str):
    validate_encryption(opts)

    request_mode = None
    if mode.startswith("request-"):
        request_mode = mode.replace("request-", "")

    if not find_spec("xpra.client"):
        error_cb("`xpra-client` is not installed")

    if opts.compression_level < 0 or opts.compression_level > 9:
        error_cb("Compression level must be between 0 and 9 inclusive.")
    if opts.quality != -1 and (opts.quality < 0 or opts.quality > 100):
        error_cb("Quality must be between 0 and 100 inclusive. (or -1 to disable)")

    if mode in (
            "info", "id", "connect-test", "control", "version", "detach",
            "show-menu", "show-about", "show-session-info",
    ) and extra_args:
        opts.socket_dirs += opts.client_socket_dirs or []
    if mode == "screenshot":
        from xpra.client.base.command import ScreenshotXpraClient
        if not extra_args:
            error_cb("invalid number of arguments for screenshot mode")
        screenshot_filename = extra_args[0]
        extra_args = extra_args[1:]
        app = ScreenshotXpraClient(opts, screenshot_filename)
    elif mode == "info":
        from xpra.client.base.command import InfoXpraClient
        app = InfoXpraClient(opts)
    elif mode == "id":
        from xpra.client.base.command import IDXpraClient
        app = IDXpraClient(opts)
    elif mode in ("show-menu", "show-about", "show-session-info"):
        from xpra.client.base.command import RequestXpraClient
        app = RequestXpraClient(request=mode, opts=opts)
    elif mode == "connect-test":
        from xpra.client.base.command import ConnectTestXpraClient
        app = ConnectTestXpraClient(opts)
    elif mode == "_monitor":
        from xpra.client.base.command import MonitorXpraClient
        app = MonitorXpraClient(opts)
    elif mode == "shell":
        from xpra.client.base.command import ShellXpraClient
        app = ShellXpraClient(opts)
    elif mode == "control":
        from xpra.client.base.command import ControlXpraClient
        if len(extra_args) <= 1:
            error_cb("not enough arguments for 'control' mode, try 'help'")
        args = extra_args[1:]
        extra_args = extra_args[:1]
        app = ControlXpraClient(opts)
        app.set_command_args(args)
    elif mode == "print":
        from xpra.client.base.command import PrintClient
        if len(extra_args) <= 1:
            error_cb("not enough arguments for 'print' mode")
        args = extra_args[1:]
        extra_args = extra_args[:1]
        app = PrintClient(opts)
        app.set_command_args(args)
    elif mode == "qrcode":
        check_gtk()
        from xpra.gtk.dialogs.qrcode_client import QRCodeClient
        app = QRCodeClient(opts)
    elif mode == "version":
        from xpra.client.base.command import VersionXpraClient
        app = VersionXpraClient(opts)
    elif mode == "detach":
        from xpra.client.base.command import DetachXpraClient
        app = DetachXpraClient(opts)
    elif request_mode and opts.attach is not True:
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
            app.show_progress(60, "connecting to server")
        if mode != "attach" and not extra_args:
            # try to guess the server intended:
            server_socket = os.environ.get("XPRA_SERVER_SOCKET")
            if server_socket:
                extra_args = [f"socket://{server_socket}"]
        display_desc = do_pick_display(error_cb, opts, extra_args, cmdline)
        if len(extra_args) == 1 and opts.password:
            uri = extra_args[0]
            if uri in cmdline and opts.password in uri:
                # hide the password from the URI:
                i = cmdline.index(uri)
                obsc_cmdline = list(cmdline)
                obsc_cmdline[i] = uri.replace(opts.password, "********")
                if not OSX:
                    set_proc_title(" ".join(obsc_cmdline))
        connect_to_server(app, display_desc, opts)
    except ValueError as e:
        einfo = str(e) or type(e)
        app.show_progress(100, f"error: {einfo}")
        app.cleanup()
        raise InitExit(ExitCode.FAILURE, f"invalid value: {einfo}")
    except Exception as e:
        einfo = str(e) or type(e)
        app.show_progress(100, f"error: {einfo}")
        app.cleanup()
        raise
    return app


def get_client_gui_app(error_cb, opts, request_mode, extra_args, mode: str):
    try:
        app = make_client(opts)
    except RuntimeError as e:
        log = get_logger()
        log("failed to create the client", exc_info=True)
        # exceptions at this point are still initialization exceptions
        raise InitException(e.args[0]) from None
    app.show_progress(30, "client configuration")
    try:
        app.init(opts)
        if opts.encoding == "auto":
            opts.encoding = ""
        if opts.encoding:
            from xpra.client.base import features
            if features.encoding:
                einfo = ""
                encodings = list(app.get_encodings()) + ["auto", "stream"]
                err = opts.encoding not in encodings
                ehelp = opts.encoding == "help"
                if err and not ehelp:
                    einfo = f"invalid encoding: {opts.encoding}\n"
                if err or ehelp:
                    from xpra.codecs.loader import encodings_help
                    raise InitInfo(einfo + "%s xpra client supports the following encodings:\n * %s" %
                                   (app.client_toolkit(), "\n * ".join(encodings_help(encodings))))

        def handshake_complete(*_args) -> None:
            app.show_progress(100, "connection established")
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
        app.show_progress(40, "loading user interface")
        app.init_ui(opts)
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
            app.show_progress(80, "listening for incoming connections")
            from xpra.platform.info import get_username
            from xpra.net.socket_util import (
                setup_local_sockets, peek_connection,
                create_sockets, add_listen_socket, accept_connection,
            )
            from xpra.log import Logger
            sockets = create_sockets(opts, error_cb, sd_listen=False, ssh_upgrades=False)
            # we don't have a display,
            # so we can't automatically create sockets:
            if "auto" in opts.bind:
                opts.bind.remove("auto")
            local_sockets = setup_local_sockets(opts.bind,
                                                opts.socket_dir, opts.socket_dirs, "",
                                                "", False,
                                                opts.mmap_group, opts.socket_permissions,
                                                get_username(), getuid(), getgid())
            sockets.update(local_sockets)
            listen_cleanup: list[Callable] = []
            socket_cleanup: list[Callable] = []

            def new_connection(socktype, sock, handle=0) -> bool:
                from xpra.util.thread import start_thread
                netlog = Logger("network")
                netlog("new_connection%s", (socktype, sock, handle))
                conn = accept_connection(socktype, sock)
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
                            extra_args[:] = [uri, ]
                            display_desc = pick_display(error_cb, opts, [uri, ])
                            connect_to_server(app, display_desc, opts)
                            # app._protocol.start()
                            return
                app.idle_add(do_handle_connection, conn)

            def do_handle_connection(conn) -> None:
                protocol = app.make_protocol(conn)
                protocol.start()
                # stop listening for new connections:
                run_socket_cleanups()

            def run_socket_cleanups() -> None:
                for cleanup in listen_cleanup:
                    cleanup()
                listen_cleanup[:] = []
                # close the sockets:
                for cleanup in socket_cleanup:
                    cleanup()
                socket_cleanup[:] = []

            for socktype, sock, sinfo, cleanup_socket in sockets:
                socket_cleanup.append(cleanup_socket)
                cleanup = add_listen_socket(socktype, sock, sinfo, None, new_connection, {})
                if cleanup is not None:
                    listen_cleanup.append(cleanup)
            # listen mode is special,
            # don't fall through to connect_to_server!
            app.show_progress(90, "ready")
            return app
    except Exception as e:
        app.show_progress(100, f"failure: {e}")
        may_notify = getattr(app, "may_notify", None)
        if callable(may_notify):
            from xpra.common import NotificationID
            body = str(e)
            if body.startswith("failed to connect to"):
                lines = body.split("\n")
                summary = "Xpra client %s" % lines[0]
                body = "\n".join(lines[1:])
            else:
                summary = "Xpra client failed to connect"
            may_notify(NotificationID.FAILURE, summary, body, icon_name="disconnected")  # pylint: disable=not-callable
        app.cleanup()
        raise
    return app


def make_progress_process(title="Xpra") -> Popen | None:
    # start the splash subprocess
    env = os.environ.copy()
    env["XPRA_LOG_PREFIX"] = "splash: "
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    from xpra.platform.paths import get_nodock_command
    cmd = get_nodock_command() + ["splash"]
    debug_args = get_debug_args()
    if debug_args:
        cmd.append("--debug=%s" % (",".join(debug_args)))
    try:
        progress_process = Popen(cmd, stdin=PIPE, env=env)
    except OSError as e:
        werr("Error launching 'splash' subprocess", " %s" % e)
        return None
    # always close stdin when terminating the splash screen process:
    progress_process.saved_terminate = progress_process.terminate

    def terminate(*_args) -> None:
        stdin = progress_process.stdin
        if stdin:
            progress_process.stdin = None
            noerr(stdin.close)
        progress_process.saved_terminate()
        setattr(progress_process, "terminate", progress_process.saved_terminate)

    # override Popen.terminate()
    setattr(progress_process, "terminate", terminate)

    def progress(pct: int, text: str) -> None:
        if progress_process.poll() is not None:
            return
        stdin = progress_process.stdin
        if stdin:
            stdin.write(("%i:%s\n" % (pct, text)).encode("latin1"))
            stdin.flush()
        if pct == 100:
            # it should exit on its own, but just in case:
            from xpra.common import SPLASH_EXIT_DELAY
            glib = gi_import("GLib")
            glib.timeout_add(SPLASH_EXIT_DELAY * 1000 + 500, terminate)

    progress_process.progress = progress

    add_process(progress_process, "splash", cmd, ignore=True, forget=True)
    progress(0, title)
    progress(10, "initializing")
    return progress_process


def run_opengl_probe() -> tuple[str, dict]:
    log = Logger("opengl")
    if not find_spec("OpenGL"):
        log("OpenGL module not found!")
        error = "missing OpenGL module"
        return f"error:{error}", {
            "error": error,
            "success": False,
        }
    from xpra.platform.paths import get_nodock_command
    from xpra.net.subprocess_wrapper import exec_kwargs
    cmd = get_nodock_command() + ["opengl"]
    env = get_exec_env()
    if is_debug_enabled("opengl"):
        cmd += ["-d", "opengl"]
    else:
        env["NOTTY"] = "1"
    env["XPRA_HIDE_DOCK"] = "1"
    env["XPRA_REDIRECT_OUTPUT"] = "0"
    start = monotonic()
    kwargs = exec_kwargs(stderr=PIPE)
    log(f"run_opengl_probe() using cmd={cmd} with env={env=} and {kwargs=}")
    try:
        proc = Popen(cmd, stdout=PIPE, env=env, universal_newlines=True, **kwargs)
    except Exception as e:
        log.warn("Warning: failed to execute OpenGL probe command")
        log.warn(" %s", e)
        return "failed", {"message": str(e).replace("\n", " ")}
    try:
        stdout, stderr = proc.communicate(timeout=OPENGL_PROBE_TIMEOUT)
        r = proc.returncode
    except TimeoutExpired:
        log("opengl probe command timed out")
        proc.kill()
        stdout, stderr = proc.communicate()
        r = None
    log("xpra opengl stdout:")
    for line in stdout.splitlines():
        log(" %s", line)
    log("xpra opengl stderr:")
    for line in stderr.splitlines():
        log(" %s", line)
    log("OpenGL probe command returned %s for command=%s", r, cmd)
    end = monotonic()
    log("probe took %ims", 1000 * (end - start))
    props = {}
    for line in stdout.splitlines():
        parts = line.split("=", 1)
        if len(parts) == 2:
            key = parts[0]
            value = parts[1]
            if key.find("-size") > 0:
                try:
                    value = int(value)
                except ValueError:
                    pass
            if key.endswith("-dims"):
                try:
                    value = tuple(int(item.strip(" ")) for item in value.split(","))
                except ValueError:
                    pass
            elif value in ("True", "False"):
                value = value == "True"
            props[key] = value
    log("parsed OpenGL properties=%s", props)

    def probe_message() -> str:
        tdprops = typedict(props)
        err = tdprops.strget("error")
        msg = tdprops.strget("message")
        warning = tdprops.strget("warning").split(":")[0]
        if err:
            return f"error:{err}"
        if r == 1:
            return "crash"
        if r is None:
            return "timeout"
        if r > 128:
            return "failed:%s" % SIGNAMES.get(r - 128)
        if r != 0:
            return "failed:%s" % SIGNAMES.get(0 - r, 0 - r)
        if not tdprops.boolget("success", False):
            return "error:%s" % (err or msg or warning)
        if not tdprops.boolget("safe", False):
            return "warning:%s" % (err or msg)
        if not tdprops.boolget("enable", True):
            return f"disabled:{msg}"
        return "success"

    # log.warn("Warning: OpenGL probe failed: %s", msg)
    message = probe_message()
    log(f"probe_message()={message!r}")
    return message, props


def set_client_features(opts) -> None:
    def b(v) -> bool:
        return str(v).lower() not in FALSE_OPTIONS

    def bo(v) -> bool:
        return str(v).lower() not in FALSE_OPTIONS or str(v).lower() in OFF_OPTIONS

    impwarned: set[str] = set()

    def impcheck(*modules) -> bool:
        for mod in modules:
            if find_spec(mod):
                continue
            if mod not in impwarned:
                impwarned.add(mod)
                log = get_logger()
                log("impcheck%s", modules, exc_info=True)
                log.warn(f"Warning: missing {mod!r} module")
                log.warn(f" for Python {sys.version}")
            return False
        return True

    from xpra.client.base import features
    features.display = opts.windows
    features.windows = opts.windows
    features.cursors = opts.windows and opts.cursors
    features.gstreamer = opts.gstreamer
    features.x11 = opts.x11 and impcheck("xpra.x11")
    features.audio = features.gstreamer and b(opts.audio) and (bo(opts.speaker) or bo(opts.microphone)) and impcheck("xpra.audio")
    features.webcam = bo(opts.webcam) and impcheck("xpra.codecs")
    features.clipboard = b(opts.clipboard) and impcheck("xpra.clipboard")
    features.notifications = opts.notifications and impcheck("xpra.notifications")
    features.dbus = b(opts.dbus) and impcheck("dbus", "xpra.dbus")
    features.mmap = b(opts.mmap)
    features.ssl = b(opts.ssl) and impcheck("ssl")
    features.ssh = b(opts.ssh)
    features.logging = b(opts.remote_logging)
    features.tray = b(opts.tray)
    features.network_state = True
    features.network_listener = envbool("XPRA_CLIENT_BIND_SOCKETS", True) and opts.bind != "none"
    features.encoding = opts.windows


def enforce_client_features() -> None:
    from xpra.util.pysystem import enforce_features
    from xpra.client.base import features
    enforce_features(features, {
        "display": "xpra.client.mixins.display",
        "windows": "xpra.client.mixins.windows",
        "cursors": "xpra.client.mixins.cursors",
        "gstreamer": "gi.repository.Gst,xpra.gstreamer,xpra.codecs.gstreamer",
        "x11": "xpra.x11,gi.repository.GdkX11",
        "webcam": "xpra.client.mixins.webcam",
        "audio": "xpra.audio,xpra.client.mixins.audio",
        "clipboard": "xpra.clipboard,xpra.client.mixins.clipboard",
        "notifications": "xpra.notifications,xpra.client.mixins.notification",
        "dbus": "dbus,xpra.dbus",
        "mmap": "mmap,xpra.net.mmap,xpra.client.mixins.mmap",
        "ssl": "ssl,xpra.net.ssl_util",
        "ssh": "paramiko,xpra.net.ssh",
        "logging": "xpra.client.mixins.logging",
        "tray": "xpra.client.mixins.tray",
        "network_state": "xpra.client.mixins.network_state",
        "network_listener": "xpra.client.mixins.network_listener",
        "encoding": "xpra.client.mixins.encodings",
    })
    may_block_numpy()


def may_block_numpy() -> None:
    if envbool("XPRA_MAY_BLOCK_NUMPY", True) and "numpy" not in sys.modules:
        reason = ""
        try:
            from xpra.codecs.nvidia.util import has_nvidia_hardware
            if not has_nvidia_hardware():
                reason = "no nvidia hardware"
        except ImportError:
            reason = "no nvidia codecs"
        if reason:
            get_logger().debug(f"{reason}, blocking `numpy` import")
            # noinspection PyTypeChecker
            sys.modules["numpy"] = None


def no_gi_gtk_modules() -> None:
    for mod in ("Gtk", "Gdk", "GdkX11", "GdkPixbuf", "GtkosxApplication"):
        mod_path = f"gi.repository.{mod}"
        if sys.modules.get(mod_path):
            raise RuntimeError(f"Gtk module {mod!r} is already loaded!")
        # noinspection PyTypeChecker
        sys.modules[mod_path] = None


def make_client(opts):
    backend = opts.backend or "gtk"
    BACKENDS = ("qt", "gtk", "pyglet", "tk", "auto")
    if backend == "qt":
        no_gi_gtk_modules()
        try:
            from xpra.client.qt6.client import make_client as make_qt6_client
            return make_qt6_client()
        except ImportError as e:
            get_logger().debug("importing qt6 client", exc_info=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the qt6 client component is missing: {e}") from None
    if backend == "pyglet":
        no_gi_gtk_modules()
        try:
            from xpra.client.pyglet.client import make_client as make_pyglet_client
            return make_pyglet_client()
        except ImportError as e:
            get_logger().debug("importing qt6 client", exc_info=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the pyglet client component is missing: {e}") from None
    if backend == "tk":
        no_gi_gtk_modules()
        try:
            from xpra.client.tk.client import make_client as make_tk_client
            return make_tk_client()
        except ImportError as e:
            get_logger().debug("importing qt6 client", exc_info=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the tk client component is missing: {e}") from None
    if backend not in ("gtk", "auto"):
        raise ValueError(f"invalid gui backend {backend!r}, must be one of: "+csv(BACKENDS))

    progress_process = None
    if opts.splash is not False:
        from xpra import __version__
        progress_process = make_progress_process("Xpra Client v%s" % __version__)

    try:
        check_gtk_client()

        from xpra.platform.gui import init as gui_init
        gui_init()

        set_client_features(opts)
        if envbool("XPRA_ENFORCE_FEATURES", True):
            enforce_client_features()

        from xpra.client.gtk3.client import XpraClient
        app = XpraClient()
        app.progress_process = progress_process

        if opts.opengl in ("probe", "nowarn"):
            app.show_progress(20, "validating OpenGL configuration")
            probe, probe_info = run_opengl_probe()
            glinfo = typedict(probe_info)
            if opts.opengl == "nowarn":
                # just on or off from here on:
                safe = glinfo.boolget("safe", False)
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
            app.show_progress(20, f"validating OpenGL: {r}")
            message = glinfo.strget("message")
            if message:
                app.show_progress(21, f" {message}")
    except Exception:
        if progress_process:
            try:
                progress_process.terminate()
            except Exception:
                pass
        raise
    return app


def do_run_client(app) -> ExitValue:
    try:
        return app.run()
    except KeyboardInterrupt:
        return -signal.SIGINT
    finally:
        app.cleanup()


def get_start_new_session_dict(opts, mode, extra_args) -> dict[str, Any]:
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


def shellquote(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


def strip_defaults_start_child(start_child, defaults_start_child):
    if start_child and defaults_start_child:
        # ensure we don't pass start / start-child commands
        # which came from defaults (the configuration files)
        # only the ones specified on the command line:
        # (and only remove them once so the command line can re-add the same ones!)
        for x in defaults_start_child:
            if x in start_child:
                start_child.remove(x)
    return start_child


def match_client_display_size(options, display_is_remote=True) -> None:
    if options.resize_display.lower() not in TRUE_OPTIONS:
        return
    # if possible, use the current display size as initial vfb size
    root_w, root_h = get_current_root_size(display_is_remote)
    if 0 < root_w < 16384 and 0 < root_h < 16384:
        scaling_x, scaling_y = parse_scaling(options.desktop_scaling, root_w, root_h)
        scaled_w = round(root_w / scaling_x)
        scaled_h = round(root_h / scaling_y)
        options.resize_display = f"{scaled_w}x{scaled_h}"


def run_server(script_file, cmdline, error_cb, options, args, full_mode: str, defaults) -> ExitValue:
    mode_parts = full_mode.split(",", 1)
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])
    if mode in (
            "seamless", "desktop", "monitor", "expand",
            "upgrade", "upgrade-seamless", "upgrade-desktop", "upgrade-monitor",
    ):
        if OSX or WIN32:
            raise InitException(f"{mode} is not supported on this platform")
        if mode != "expand" and not find_spec("xpra.x11"):
            raise InitExit(ExitCode.UNSUPPORTED, f"you must install `xpra-x11` to use {mode!r}")
    display_name = ""
    display_is_remote = isdisplaytype(args, "ssh", "tcp", "ssl", "ws", "wss", "vsock")
    with_display = mode in ("seamless", "desktop", "monitor", "expand")
    if with_display and str_to_bool(options.attach, False) and args and not display_is_remote:
        # maybe the server is already running for the display specified
        # then we don't even need to bother trying to start it:
        try:
            display = pick_display(error_cb, options, args, cmdline)
        except (ValueError, InitException):
            pass
        else:
            dotxpra = DotXpra(options.socket_dir, options.socket_dirs)
            display_name = display.get("display_name", "")
            if display_name:
                state = dotxpra.get_display_state(display_name)
                if state == SocketState.LIVE:
                    get_logger().info(f"existing live display found on {display_name}, attaching")
                    # we're connecting locally, so no need for these:
                    options.csc_modules = ["none"]
                    options.video_decoders = ["none"]
                    return do_run_mode(script_file, cmdline, error_cb, options, args, "attach", defaults)
    if mode == "seamless":
        match_client_display_size(options, display_is_remote)

    if mode != "encoder":
        r = start_server_via_proxy(cmdline, error_cb, options, args, full_mode)
        if isinstance(r, int):
            return r

    try:
        from xpra import server
        assert server
        from xpra.scripts.server import do_run_server
    except ImportError:
        error_cb("`xpra-server` is not installed")
        sys.exit(1)
    return do_run_server(script_file, cmdline, error_cb, options, args, full_mode, display_name, defaults)


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


def start_server_via_proxy(cmdline, error_cb, options, args, mode: str) -> int | ExitCode | None:
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
            from xpra.platform.features import SYSTEM_PROXY_SOCKET
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


def find_mode_pos(args, mode: str) -> int:
    rmode = REVERSE_MODE_ALIAS.get(mode, str(mode))
    mode_strs = [rmode]
    if rmode.find("-") > 0:
        mode_strs.append(rmode.split("-", 1)[1])  # ie: "start-desktop" -> "desktop"
    if mode == "seamless":  # ie: "seamless" -> "start"
        mode_strs.append("start")
    for mstr in mode_strs:
        try:
            return args.index(mstr)
        except ValueError:
            pass
    raise InitException(f"mode {mode!r} not found in command line arguments {args}")


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
            app.show_progress(30, "client configuration")
            app.init(opts)
            app.show_progress(40, "loading user interface")
            app.init_ui(opts)
            app.hello_extra = hello_extra

            def handshake_complete(*_args) -> None:
                app.show_progress(100, "connection established")

            app.after_handshake(handshake_complete)
        app.show_progress(60, "starting server")

        while True:
            try:
                conn = connect_or_fail(params, opts)
                app.make_protocol(conn)
                app.show_progress(80, "connecting to server")
                break
            except InitExit as e:
                from xpra.net.ssl_util import ssl_retry
                mods = ssl_retry(e, opts.ssl_ca_certs)
                if mods:
                    for k, v in mods.items():
                        setattr(opts, f"ssl_{k}", v)
                    continue
                raise
    except Exception as e:
        if app:
            app.show_progress(100, f"failure: {e}")
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
        return exec_reconnect(script_file, attach_args)
    return r


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
    wd = os.environ.get("WAYLAND_DISPLAY")
    if wd:
        addwaylandsock(wd, wd)
        addwaylandsock(wd, os.path.join(xrd, wd))
    # now try a file glob:
    for x in glob.glob(os.path.join(xrd, "wayland-*")):
        wd = os.path.basename(x)
        addwaylandsock(wd, x)
    return displays


X11_SOCKET_DIR = "/tmp/.X11-unix"


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
        if timeout > 0:
            sock: socket.socket | None = None
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                sock.connect(socket_path)
            except OSError:
                # warn(f"Error trying to connect to {socket_path!r}: {e}")
                return {}
            finally:
                if sock:
                    sock.close()
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
            return displays[0]
        if current_display in displays:
            log(f"using {current_display=}")
            return current_display
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
    # print(f"find_displays unfiltered displays={displays}")
    display_info = {}
    for display, sockpath in displays.items():
        stat = stat_display_socket(sockpath)
        if not stat:
            # print(f"cannot stat {sockpath}")
            continue
        # print(f"stat({sockpath}={stat}")
        sock_uid = stat.get("uid", -1)
        sock_gid = stat.get("gid", -1)
        if uid is not None and uid != sock_uid:
            # print(f"display socket {sockpath} does not match uid {uid} (uid={sock_uid})")
            continue
        if gid is not None and gid != sock_gid:
            # print(f"display socket {sockpath} does not match gid {gid} (gid={sock_gid})")
            continue
        display_info[display] = {"uid": sock_uid, "gid": sock_gid, "socket": sockpath}
    return display_info


no_gtk_bypass = False


def bypass_no_gtk(v=True) -> None:
    global no_gtk_bypass
    no_gtk_bypass = v


def no_gtk() -> None:
    if no_gtk_bypass:
        return
    if OSX:
        # we can't verify on macos because importing GtkosxApplication
        # will import Gtk, and we need GtkosxApplication early to find the paths
        return
    Gtk = sys.modules.get("gi.repository.Gtk")
    if Gtk is None:
        # all good, not loaded
        return
    raise InitException("the Gtk module is already loaded: %s" % Gtk)


def run_example(args) -> ExitValue:
    all_examples = (
        "bell", "clicks",
        "colors-gradient", "colors-plain", "colors",
        "cursors",
        "file-chooser",
        "fontrendering",
        "grabs",
        "header-bar",
        "initiate-moveresize",
        "text-entry",
        "transparent-colors",
        "transparent-window",
        "tray",
        "window-focus", "window-geometry-hints",
        "window-opacity", "window-overrideredirect",
        "window-states", "window-title",
        "window-transient",
        "opengl",
        "view-keyboard", "view-clipboard",
    )
    if not args or args[0] not in all_examples:
        raise InitInfo(f"usage: xpra example testname\nvalid names: {csv(sorted(all_examples))}")
    example = args[0]
    classname = example.replace("-", "_")
    modpath = f"xpra.gtk.dialogs.{classname}" if example in ("view-keyboard", "view-clipboard")\
        else f"xpra.gtk.examples.{classname}"
    try:
        module = import_module(modpath)
    except ImportError as e:
        raise InitException(f"failed to import example {classname}: {e}") from None
    return module.main()


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
    from xpra.platform.features import AUTOSTART
    if not AUTOSTART:
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


def run_glprobe(opts, show=False) -> ExitValue:
    if show:
        from xpra.platform.gui import init, set_default_icon
        set_default_icon("opengl.png")
        init()
    import signal

    def signal_handler(signum, _frame) -> NoReturn:
        force_quit(128 - signum)

    for name in ("ABRT", "BUS", "FPE", "HUP", "ILL", "INT", "PIPE", "SEGV", "TERM"):
        value = getattr(signal, f"SIG{name}", 0)
        if value:
            signal.signal(value, signal_handler)

    props = do_run_glcheck(opts, show)
    if not props.get("success", False):
        return ExitCode.FAILURE
    if not props.get("safe", False):
        return ExitCode.OPENGL_UNSAFE
    return ExitCode.OK


def do_run_glcheck(opts, show=False) -> dict[str, Any]:
    # suspend all logging:
    saved_level = None
    log = Logger("opengl")
    log(f"do_run_glcheck(.., {show})")
    if not is_debug_enabled("opengl") or not use_tty():
        saved_level = logging.root.getEffectiveLevel()
        logging.root.setLevel(logging.WARN)
    try:
        from xpra.opengl.window import get_gl_client_window_module, test_gl_client_window
        opengl_str = (opts.opengl or "").lower()
        opengl_props, gl_client_window_module = get_gl_client_window_module(opengl_str)
        log("do_run_glcheck() opengl_props=%s, gl_client_window_module=%s", opengl_props, gl_client_window_module)
        if gl_client_window_module and (opengl_props.get("safe", False) or opengl_str.startswith("force")):
            gl_client_window_class = gl_client_window_module.GLClientWindow
            pixel_depth = int(opts.pixel_depth)
            log("do_run_glcheck() gl_client_window_class=%s, pixel_depth=%s", gl_client_window_class, pixel_depth)
            if pixel_depth not in (0, 16, 24, 30) and pixel_depth < 32:
                pixel_depth = 0
            draw_result = test_gl_client_window(gl_client_window_class, pixel_depth=pixel_depth, show=show)
            log(f"draw result={draw_result}")
            opengl_props.update(draw_result)
            if not draw_result.get("success", False):
                opengl_props["safe"] = False
        log("do_run_glcheck(.., %s)=%s", show, opengl_props)
        return opengl_props
    except Exception as e:
        if is_debug_enabled("opengl"):
            log("do_run_glcheck(..)", exc_info=True)
        if use_tty():
            stderr_print(f"error={e!r}")
        return {
            "success": False,
            "message": str(e).replace("\n", " "),
        }
    finally:
        if saved_level is not None:
            logging.root.setLevel(saved_level)


def run_glcheck(opts) -> ExitValue:
    # cheap easy check first:
    log = Logger("opengl")
    if not find_spec("OpenGL"):
        log("OpenGL module not found!")
        props = {
            "error": "missing OpenGL module",
            "success": False,
        }
    else:
        check_gtk_client()
        if POSIX and not OSX and not is_Wayland():
            log("forcing x11 Gdk backend")
            with OSEnvContext(GDK_BACKEND="x11", PYOPENGL_BACKEND="x11"):
                try:
                    from xpra.x11.gtk.display_source import init_gdk_display_source
                    init_gdk_display_source()
                except ImportError as e:
                    log(f"no bindings x11 bindings: {e}")
                except Exception:
                    log("error initializing gdk display source", exc_info=True)
        try:
            props = do_run_glcheck(opts)
        except Exception as e:
            props = {
                "error": str(e).replace("\n", " "),
                "success": False,
            }
    log("run_glcheck(..) props=%s", props)
    for k in sorted(props.keys()):
        v = props[k]
        # skip not human readable:
        if k not in ("extensions", "glconfig", "GLU.extensions",):
            vstr = str(v)
            try:
                if k.endswith("dims"):
                    vstr = csv(v)
                else:
                    vstr = pver(v)
            except ValueError:
                pass
            sys.stdout.write("%s=%s\n" % (k, vstr))
    sys.stdout.flush()
    return 0


def pick_shadow_display(args, uid=getuid(), gid=getgid(), sessions_dir="") -> str:
    if len(args) == 1 and args[0]:
        if OSX or WIN32:
            return args[0]
        if args[0][0] == ":":
            # display_name was provided:
            return args[0]
    if OSX or WIN32:
        # no need for a specific display
        return "Main"
    return guess_display(None, uid, gid, sessions_dir)


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
    proc.terminate()
    raise RuntimeError(f"timeout: failed to identify the new shadow server {display_name!r}")


def start_server_subprocess(script_file, args, mode, opts,
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
        matching_display = None
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
    existing_sockets = set(dotxpra.socket_paths(check_uid=uid,
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


def get_start_server_args(opts, uid=getuid(), gid=getgid(), compat=False, cmdline=()) -> list[str]:
    option_types = {}
    for x, ftype in OPTION_TYPES.items():
        if x not in CLIENT_ONLY_OPTIONS:
            option_types[x] = ftype
    return get_command_args(opts, uid, gid, option_types, compat, cmdline)


def get_command_args(opts, uid: int, gid: int, option_types: dict[str, Any],
                     compat=False, cmdline=()) -> list[str]:
    defaults = make_defaults_struct(uid=uid, gid=gid)
    fdefaults = defaults.clone()
    fixup_options(fdefaults)
    args = []
    for x, ftype in option_types.items():
        if x in NON_COMMAND_LINE_OPTIONS:
            continue
        if compat and x in OPTIONS_ADDED_SINCE_V5:
            continue
        fn = x.replace("-", "_")
        ov = getattr(opts, fn)
        dv = getattr(defaults, fn)
        fv = getattr(fdefaults, fn)
        incmdline = (f"--{x}" in cmdline or f"--no-{x}" in cmdline or any(c.startswith(f"--{x}=") for c in cmdline))
        if not incmdline:
            # we may skip this option if the value is the same as the default:
            if ftype is list:
                # compare lists using their csv representation:
                if csv(ov) == csv(dv) or csv(ov) == csv(fv):
                    continue
            if ov in (dv, fv):
                continue  # same as the default
        argname = f"--{x}="
        if compat:
            argname = OPTIONS_COMPAT_NAMES.get(argname, argname)
        # lists are special cased depending on how OptionParse will be parsing them:
        if ftype is list:
            # warn("%s: %s vs %s\n" % (x, ov, dv))
            if x in START_COMMAND_OPTIONS + BIND_OPTIONS + [
                "pulseaudio-configure-commands",
                "speaker-codec", "microphone-codec",
                "key-shortcut", "start-env", "env",
                "socket-dirs",
            ]:
                # individual arguments (ie: "--start=xterm" "--start=gedit" ..)
                for e in ov:
                    args.append(f"{argname}{e}")
            else:
                # those can be specified as CSV: (ie: "--encodings=png,jpeg,rgb")
                args.append(f"{argname}" + ",".join(str(v) for v in ov))
        elif ftype is bool:
            args.append(f"{argname}" + ["no", "yes"][int(ov)])
        elif ftype in (int, float, str):
            args.append(f"{argname}{ov}")
        else:
            raise InitException(f"unknown option type {ftype!r} for {x!r}")
    return args


def identify_new_socket(proc, dotxpra, existing_sockets, matching_display, new_server_uuid: str,
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
                if p.returncode == 0:
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
                    if found:
                        assert display, "display value not found in id output"
                        log(f"identify_new_socket found match: path={socket_path!r}, display={display}")
                        return socket_path, display
            except Exception as e:
                warn(f"error during server process detection: {e}")
        time.sleep(0.10)
    raise InitException("failed to identify the new server display!")


def run_proxy(error_cb, opts, script_file, cmdline, args, mode, defaults) -> ExitValue:
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


def run_stopexit(mode: str, error_cb, opts, extra_args, cmdline) -> ExitValue:
    assert mode in ("stop", "exit")
    no_gtk()

    def show_final_state(display_desc: dict[str, Any]) -> int:
        # this is for local sockets only!
        display = display_desc["display"]
        sockdir = display_desc.get("socket_dir", "")
        sockdirs = display_desc.get("socket_dirs", [])
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
            show_final_state(display_desc)
        else:
            print(f"Sent {mode} command")
    return e


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


def run_top(error_cb, options, args, cmdline) -> ExitValue:
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


def run_encode(error_cb, options, args, cmdline) -> ExitValue:
    set_client_features(options)
    enforce_client_features()
    from xpra.client.base.encode import EncodeClient
    if not args:
        raise ValueError("please specify a display and at least one filename")
    display_desc = pick_display(error_cb, options, args[:1], cmdline)
    app = EncodeClient(options, args[1:])
    app.init(options)
    connect_to_server(app, display_desc, options)
    return app.run()


def run_session_info(error_cb, options, args, cmdline) -> ExitValue:
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


def run_list_mdns(error_cb, extra_args) -> ExitValue:
    no_gtk()
    mdns_wait = 5
    if len(extra_args) <= 1:
        try:
            mdns_wait = int(extra_args[0])
        except (IndexError, ValueError):
            pass
    else:
        error_cb("too many arguments for `list-mdns` mode")
    from xpra.net.mdns import XPRA_TCP_MDNS_TYPE, XPRA_UDP_MDNS_TYPE
    try:
        from xpra.net.mdns.avahi_listener import Avahilistener
        listener_class: type = Avahilistener
    except ImportError:
        try:
            from xpra.net.mdns.zeroconf_listener import Zeroconflistener
            listener_class = Zeroconflistener
        except ImportError:
            error_cb("sorry, 'list-mdns' requires an mdns module")
    from xpra.dbus.common import loop_init
    GLib = gi_import("GLib")
    loop_init()
    found: dict[tuple[str, str, str], list] = {}
    shown = set()

    def show_new_found() -> None:
        new_found = [x for x in found.keys() if x not in shown]
        for uq in new_found:
            recs = found[uq]
            for i, rec in enumerate(recs):
                iface, _, _, host, address, port, text = rec
                uuid = text.strget("uuid")
                display = text.strget("display")
                mode = text.strget("mode")
                username = text.strget("username")
                session = text.strget("session")
                dtype = text.strget("type")
                if i == 0:
                    print(f"* user {username!r} on {host!r}")
                    if session:
                        print(f" {dtype} session {session!r}, uuid={uuid}")
                    elif uuid:
                        print(f" uuid={uuid}")
                iinfo = ""
                if iface:
                    iinfo = f", interface {iface}"
                print(f" + {mode} endpoint on host {address}, port {port}{iinfo}")
                dstr = ""
                if display.startswith(":"):
                    dstr = display[1:]
                uri = f"{mode}://{username}@{address}:{port}/{dstr}"
                print("   \"%s\"" % uri)
            shown.add(uq)

    def mdns_add(interface, _protocol, name, _stype, domain, host, address, port, text) -> None:
        text = typedict((bytestostr(k), bytestostr(v)) for k,v in (text or {}).items())
        iface = interface
        if iface is not None:
            try:
                iface = socket.if_indextoname(interface)
            except OSError:
                pass
        username = text.strget("username")
        uq = text.strget("uuid", str(len(found))), username, host
        found.setdefault(uq, []).append((iface or "", name, domain, host, address, port, text))
        GLib.timeout_add(1000, show_new_found)

    listeners = []

    def add(service_type: str) -> None:
        listener = listener_class(service_type, mdns_add=mdns_add)
        listeners.append(listener)

        def start() -> None:
            listener.start()

        GLib.idle_add(start)

    add(XPRA_TCP_MDNS_TYPE)
    add(XPRA_UDP_MDNS_TYPE)
    print("Looking for xpra services via mdns")
    try:
        loop = GLib.MainLoop()
        GLib.timeout_add(mdns_wait * 1000, loop.quit)
        loop.run()
    finally:
        for listener in listeners:
            listener.stop()
    if not found:
        print("no services found")
    else:
        print(f"{len(found)} services found")
    return 0


def kill_pid(pid: int, procname: str) -> None:
    if pid:
        try:
            if pid and pid > 1 and pid != os.getpid():
                os.kill(pid, signal.SIGTERM)
        except OSError as e:
            error("Error sending SIGTERM signal to %r pid %i %s" % (procname, pid, e))


def load_pid(session_dir: str, pid_filename: str) -> int:
    if not session_dir or not pid_filename:
        return 0
    pid_file = os.path.join(session_dir, pid_filename)  # ie: "/run/user/1000/xpra/7/dbus.pid"
    if not os.path.exists(pid_file):
        return 0
    try:
        with open(pid_file, "rb") as f:
            return int(f.read().rstrip(b"\n\r"))
    except (ValueError, OSError) as e:
        error(f"failed to read {pid_file!r}: {e}")
        return 0


def run_clean(opts, args: Iterable[str]) -> ExitValue:
    no_gtk()
    try:
        uid = int(opts.uid)
    except (ValueError, TypeError):
        uid = getuid()
    from xpra.scripts.session import get_session_dir
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
        server_pid = load_pid(session_dir, "server.pid")
        if server_pid and POSIX and not OSX and os.path.exists(f"/proc/{server_pid}"):
            print(f"server process for session {display} is still running with pid {server_pid}")
            print(f" the session directory {session_dir!r} has not been removed")
            continue
        try:
            dno = int(display.lstrip(":"))
        except (ValueError, TypeError):
            dno = 0
        else:
            x11_socket_path = os.path.join(X11_SOCKET_DIR, f"X{dno}")
            r = stat_display_socket(x11_socket_path)
            if r:
                # so the X11 server may still be running
                xvfb_pid = load_pid(session_dir, "xvfb.pid")
                if xvfb_pid and kill_displays:
                    kill_pid(xvfb_pid, "xvfb")
                else:
                    print(f"X11 server :{dno} is still running ")
                    if xvfb_pid:
                        print(" run clean-displays to terminate it")
                    else:
                        print(" cowardly refusing to clean the session")
                    continue
        # print("session_dir: %s : %s" % (session_dir, state))
        for pid_filename in ("dbus.pid", "pulseaudio.pid",):
            pid = load_pid(session_dir, pid_filename)  # ie: "/run/user/1000/xpra/7/dbus.pid"
            kill_pid(pid, pid_filename.split(".")[0])
        try:
            session_files = os.listdir(session_dir)
        except OSError as e:
            error(f"Error listing session files in {session_dir}: {e}")
            continue
        # files we can remove safely:
        KNOWN_SERVER_FILES = [
            "cmdline", "config",
            "dbus.env", "dbus.pid",
            "server.env", "server.pid", "server.log",
            "socket", "xauthority", "Xorg.log", "xvfb.pid",
            "pulseaudio.pid",
        ]
        KNOWN_SERVER_DIRS = [
            "pulse",
            "ssh",
        ]
        ALL_KNOWN = KNOWN_SERVER_FILES + KNOWN_SERVER_DIRS
        unknown_files = [x for x in session_files if x not in ALL_KNOWN]
        if unknown_files:
            error("Error: found some unexpected session files:")
            error(" " + csv(unknown_files))
            error(f" the session directory {session_dir!r} has not been removed")
            continue
        for x in session_files:
            pathname = os.path.join(session_dir, x)
            try:
                if x in KNOWN_SERVER_FILES:
                    os.unlink(pathname)
                else:
                    assert x in KNOWN_SERVER_DIRS
                    rmtree(pathname)
            except OSError as e:
                error(f"Error removing {pathname!r}: {e}")
        try:
            os.rmdir(session_dir)
        except OSError as rme:
            error(f"Error session directory {session_dir!r}: {rme}")
            continue
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


def run_recover(script_file, cmdline, error_cb, options, args, defaults) -> ExitValue:
    if not POSIX or OSX:
        raise InitExit(ExitCode.UNSUPPORTED, "the 'xpra recover' subcommand is not supported on this platform")
    assert POSIX and not OSX
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
    inodes_display = {}
    for display in sorted_nicely(dead_displays):
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
    # now find the processes that own these inodes
    display_pids = {}
    if inodes_display:
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
                            cmdline = os.path.join(procpath, "cmdline")
                            cmd = open(cmdline, encoding="utf8").read()
                            cmd = shlex.join(cmd.split("\0"))
                        except Exception:
                            pass
                        display_pids[display] = (pid, cmd)
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
    if OSX or not POSIX:
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
            from xpra.scripts.session import load_session_file
            from xpra.scripts.session import session_file_path
            from xpra.scripts.session import get_session_dir
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
                        xvfb_pid = load_pid(session_dir, "xvfb.pid")
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
    log = get_logger()
    # add ":" prefix to display name,
    # and remove xpra sessions
    xpra_sessions = {}
    if dotxpra:
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


def run_list_sessions(args, options) -> ExitValue:
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


def display_wm_info(args) -> dict[str, Any]:
    assert POSIX and not OSX, "wminfo is not supported on this platform"
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
        from xpra.x11.gtk.wm_check import get_wm_info
        info = get_wm_info()
        gdk = gi_import("Gdk")
        display = gdk.Display.get_default()
        info["display"] = display.get_name()
        return info


def run_xwait(args) -> ExitValue:
    from xpra.x11.bindings.xwait import main as xwait_main  # pylint: disable=no-name-in-module
    xwait_main(args)
    return 0


def run_wminfo(args) -> ExitValue:
    for k, v in display_wm_info(args).items():
        print(f"{k}={v}")
    return 0


def run_wmname(args) -> ExitValue:
    name = display_wm_info(args).get("wmname", "")
    if name:
        print(name)
    return 0


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


def get_xpra_sessions(dotxpra: DotXpra, ignore_state=(SocketState.UNKNOWN,), matching_display=None,
                      query: bool = True) -> dict[str, Any]:
    results = dotxpra.socket_details(matching_display=matching_display)
    log = get_logger()
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


def run_list(error_cb: Callable, opts, extra_args, clean: bool = True) -> ExitValue:
    no_gtk()
    if extra_args:
        error_cb("too many arguments for `list` mode")
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


def run_list_windows(error_cb, opts, extra_args) -> ExitValue:
    no_gtk()
    if extra_args:
        error_cb("too many arguments for `list-windows` mode")
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
                # print("winfo=%s" % (winfo,))
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


def run_list_clients(error_cb, opts, extra_args) -> ExitValue:
    no_gtk()
    if extra_args:
        error_cb("too many arguments for `list-windows` mode")
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


def get_remote_proxy_command_output(options, args, cmdline, subcommand="setup-ssl") -> tuple[dict, bytes]:
    if len(args) != 1:
        raise InitExit(ExitCode.FAILURE, "a single optional argument may be specified")
    arg = args[0]
    disp = parse_display_name(error_handler, options, arg, cmdline)
    if disp.get("type", "") != "ssh":
        raise InitExit(ExitCode.FAILURE, "argument must be an ssh URL")
    disp["display_as_args"] = []
    disp["proxy_command"] = [subcommand, ]

    from xpra.net.ssh import util
    util.LOG_EOF = False

    def ssh_fail(*_args) -> NoReturn:
        sys.exit(int(ExitCode.SSH_FAILURE))

    def ssh_log(*args) -> None:
        log = Logger("ssh")
        log.debug(*args)

    conn = connect_to(disp, options, debug_cb=ssh_log, ssh_fail_cb=ssh_fail)
    data = b""
    until = monotonic() + 30
    while monotonic() < until:
        bdata = conn.read(4096)
        if not bdata:
            break
        data += bdata
    noerr(conn.close)
    return disp, data


def setup_ssl(options, args, cmdline) -> ExitValue:
    from xpra.net.ssl_util import gen_ssl_cert, save_ssl_config_file, strip_cert
    if args:
        disp, data = get_remote_proxy_command_output(options, args, cmdline, "setup-ssl")
        if not data:
            raise InitExit(ExitCode.FAILURE, "no certificate data received, check the command output")
        data = strip_cert(data)
        host = disp["host"]
        save_ssl_config_file(host, port=0, filename="cert.pem", fileinfo="certificate", filedata=data)
        return ExitCode.OK
    from xpra.util.io import load_binary_file
    _keyfile, certfile = gen_ssl_cert()
    cert = load_binary_file(certfile)
    sys.stdout.write(cert.decode("latin1"))
    return 0


def show_ssl(options, args, cmdline) -> ExitValue:
    from xpra.net.ssl_util import find_ssl_cert, strip_cert, KEY_FILENAME, CERT_FILENAME
    if args:
        _disp, data = get_remote_proxy_command_output(options, args, cmdline, "show-ssl")
        if not data:
            raise InitExit(ExitCode.FAILURE, "no certificate data received, check the command output")
        cert = strip_cert(data)
    else:
        log = Logger("ssl")
        keypath = find_ssl_cert(KEY_FILENAME)
        certpath = find_ssl_cert(CERT_FILENAME)
        if not keypath or not certpath:
            log.info("no certificate found")
            return ExitCode.NO_DATA
        log.info("found an existing SSL certificate:")
        log.info(f" {keypath!r}")
        log.info(f" {certpath!r}")
        from xpra.util.io import load_binary_file
        cert = load_binary_file(certpath)
    sys.stdout.write(cert.decode("latin1"))
    return ExitCode.OK


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


def run_showconfig(options, args) -> ExitValue:
    log = get_logger()
    d = dict_to_validated_config({})
    fixup_options(d)
    # this one is normally only probed at build time:
    # (so probe it here again)
    if POSIX:
        try:
            from xpra.platform.pycups_printing import get_printer_definition
            for mimetype in ("pdf", "postscript"):
                pdef = get_printer_definition(mimetype)
                if pdef:
                    # ie: d.pdf_printer = "/usr/share/ppd/cupsfilters/Generic-PDF_Printer-PDF.ppd"
                    setattr(d, f"{mimetype}_printer", pdef)
        except Exception:
            pass
    VIRTUAL = ["mode"]  # no such option! (it's a virtual one for the launch by config files)
    # hide irrelevant options:
    HIDDEN = []
    if "all" not in args:
        # this logic probably belongs somewhere else:
        if OSX or WIN32:
            # these options don't make sense on win32 or osx:
            HIDDEN += ["socket-dirs", "socket-dir",
                       "wm-name", "pulseaudio-command", "pulseaudio", "xvfb", "input-method",
                       "socket-permissions", "xsettings",
                       "exit-with-children", "start-new-commands",
                       "start", "start-child",
                       "start-after-connect", "start-child-after-connect",
                       "start-on-connect", "start-child-on-connect",
                       "start-on-last-client-exit", "start-child-on-last-client-exit",
                       "use-display",
                       ]
        if WIN32:
            # "exit-ssh"?
            HIDDEN += ["lpadmin", "daemon", "mmap-group", "mdns"]
        if not OSX:
            HIDDEN += ["dock-icon", "swap-keys"]
    for opt, otype in sorted(OPTION_TYPES.items()):
        if opt in VIRTUAL:
            continue
        i = log.info
        w = log.warn
        if args:
            if ("all" not in args) and (opt not in args):
                continue
        elif opt in HIDDEN:
            i = log.debug
            w = log.debug
        k = name_to_field(opt)
        dv = getattr(d, k)
        cv = getattr(options, k, dv)
        cmpv = [dv]
        if isinstance(dv, tuple) and isinstance(cv, list):
            # defaults may have a tuple,
            # but command line parsing will create a list:
            cmpv.append(list(dv))
        if isinstance(dv, str) and dv.find("\n") > 0:
            # newline is written with a "\" continuation character,
            # so we don't read the newline back when loading the config files
            cmpv.append(re.sub("\\\\\n *", " ", dv))
        if cv not in cmpv:
            w("%-20s  (used)   = %-32s  %s", opt, vstr(otype, cv), type(cv))
            w("%-20s (default) = %-32s  %s", opt, vstr(otype, dv), type(dv))
        else:
            i("%-20s           = %s", opt, vstr(otype, cv))
    return 0


def vstr(otype: type, v) -> str:
    # just used to quote all string values
    if v is None:
        if otype is bool:
            return "auto"
        return ""
    if isinstance(v, str):
        return "'%s'" % nonl(v)
    if isinstance(v, (tuple, list)):
        return csv(vstr(otype, x) for x in v)
    return str(v)


def run_showsetting(args) -> ExitValue:
    if not args:
        raise InitException("specify a setting to display")

    log = get_logger()

    settings = []
    for arg in args:
        otype = OPTION_TYPES.get(arg)
        if not otype:
            log.warn(f"{arg!r} is not a valid setting")
        else:
            settings.append(arg)

    if not settings:
        return 0

    from xpra.platform.info import get_username
    dirs = get_xpra_defaults_dirs(username=get_username(), uid=getuid(), gid=getgid())

    # default config:
    config = get_defaults()

    def show_settings() -> None:
        for setting in settings:
            value = config.get(setting)
            otype = OPTION_TYPES.get(setting, str)
            log.info("%-20s: %-40s (%s)", setting, vstr(otype, value), type(value))

    log.info("* default config:")
    show_settings()
    for d in dirs:
        config.clear()
        config.update(read_xpra_conf(d))
        log.info(f"* {d!r}:")
        show_settings()
    return 0


def run_setting(setunset: bool, args) -> ExitValue:
    from xpra.util.config import update_config_attribute, unset_config_attribute
    if not args:
        raise ValueError("missing setting argument")
    setting = args[0]
    otype = OPTION_TYPES.get(setting)
    if not otype:
        raise ValueError(f"{setting!r} is not a valid setting, see `xpra showconfig`")
    if not setunset:
        if len(args) != 1:
            raise InitException("too many arguments")
        unset_config_attribute(setting)
        return ExitCode.OK

    if len(args) < 2:
        raise InitException("specify a setting to modify and its value")
    if otype is list:
        value = args[1:]
    else:
        if len(args) > 2:
            raise ValueError(f"too many values for {setting!r} which is a {otype!r}")

        def parse_bool(value: str) -> bool:
            v = value.lower()
            if v in TRUE_OPTIONS:
                return True
            if v in FALSE_OPTIONS:
                return False
            raise ValueError("not a boolean")
        parse_fn = {
            bool: parse_bool,
        }.get(otype, otype)
        try:
            value = parse_fn(args[1])
        except (ValueError, TypeError):
            raise ValueError(f"{setting} not modified: unable to convert value {args[1]!r} to {otype!r}")
    update_config_attribute(setting, value)
    return ExitCode.OK


if __name__ == "__main__":  # pragma: no cover
    code = main("xpra.exe", sys.argv)
    if not code:
        code = 0
    sys.exit(code)
