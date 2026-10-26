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
from importlib.util import find_spec

from subprocess import Popen, PIPE
import signal
import traceback
from typing import NoReturn
from collections.abc import Callable

from xpra.util.env import envint, envbool, save_env
from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import getuid, gi_import, WIN32, OSX, POSIX, LINUX
from xpra.util.io import stderr_print, info, warn, error, clean_std_pipes
from xpra.util.system import is_Wayland, set_proc_title
from xpra.util.systemd import use_systemd_run, systemd_run_wrap
from xpra.scripts.parsing import (
    get_usage,
    parse_env,
    fixup_defaults,
    validated_encodings, do_parse_cmdline, show_audio_codec_help,
    MODE_ALIAS,
)
from xpra.config.types import XpraConfig
from xpra.config import InitException, InitInfo, InitExit
from xpra.config.validation import parse_landlock_option, split_landlock_option, parse_seccomp_option
from xpra.config.paths import find_docs_path, find_html5_path
from xpra.config.defaults import make_defaults_struct, has_audio_support
from xpra.log import Logger, enable_format, inject_debug_logging
from xpra.scripts.sessions import run_recover
from xpra.scripts.args import (
    isdisplaytype,
)
from xpra.scripts.common import no_gtk, nox, reqx11, no_gi_gtk_modules
from xpra.scripts.clients import run_client
from xpra.scripts.proxy import run_proxy, run_proxy_run
from xpra.scripts.start import run_server_mode

assert callable(error), "used by modules importing this function from here"

NO_ROOT_WARNING: bool = envbool("XPRA_NO_ROOT_WARNING", False)
OPENGL_PROBE_TIMEOUT: int = envint("XPRA_OPENGL_PROBE_TIMEOUT", 5)
VERIFY_SOCKET_TIMEOUT: int = envint("XPRA_VERIFY_SOCKET_TIMEOUT", 1)

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
    "opengl", "opengl-probe", "opengl-test", "opengl-save-probe",
    "autostart",
    "encoding", "video",
    "nvinfo", "webcam",
    "keyboard", "keymap", "keymap-test",
    "gtk-info", "gui-info", "network-info", "monitor-info",
    "compression", "packet-encoding", "path-info",
    "printing-info", "version-info", "version-check", "toolbox",
    "setup-ssl", "show-ssl",
    "auth",
    "notify",
    "dbus-system-list", "dbus-session-list",
    "applications-menu", "sessions-menu", "menu-cache",
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
    "monitor-info",
)
CLIENT_SUBCOMMANDS = (
    "attach", "listen", "detach",
    "screenshot", "icon", "version", "info", "id",
    "control", "run", "exec", "_monitor", "shell", "print",
    "qrcode",
    "show-menu", "show-about", "show-session-info",
    "connect-test",
    "record",
)
SERVER_SUBCOMMANDS = (
    "seamless", "desktop", "monitor", "expand", "shadow", "shadow-screen", "shadow-device",
    "upgrade", "upgrade-seamless", "upgrade-desktop",
    "proxy",
    "encoder",
    "runner",
)
# pylint: disable=import-outside-toplevel
# noinspection PyBroadException


def get_logger() -> Logger:
    return Logger("util")


def main(script_file: str, cmdline: list[str]) -> ExitValue:
    save_env()
    if envbool("XPRA_FAULTHANDLER", False):
        # same as `python -X faulthandler`, for when we can't pass interpreter flags
        # (ie: the frozen `xpra_cmd.exe` wrapper on win32):
        import faulthandler
        faulthandler.enable(all_threads=True)
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

        return run_mode(script_file, cmdline, options, args, mode, defaults)
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
            "_audio_record", "_audio_play", "_audio_meter",
            "stop", "print", "showconfig", "configure", "sbom",
            "otp",
            "menu-cache",
            "_dialog", "_pass",
            "pinentry",
            "opengl",
            "control",
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


def configure_seccomp(value: str) -> None:
    # set the seccomp environment variables that are not already set,
    # early enough for the filter threads to pick them up when they are instantiated:
    try:
        env = parse_seccomp_option(value)
    except ValueError as e:
        raise InitException(f"invalid seccomp option: {e}") from None
    for name, val in env.items():
        os.environ.setdefault(name, val)


def configure_landlock(value: str) -> str:
    value = parse_landlock_option(value)
    if split_landlock_option(value)[0] == "strict" and LINUX:
        # dconf otherwise tries to create shared desktop state in the runtime
        # directory, including during GTK theme and menu initialization.
        os.environ.setdefault("GSETTINGS_BACKEND", "memory")
    return value


def configure_env(env_str) -> None:
    if env_str:
        env = parse_env(env_str)
        if POSIX and getuid() == 0:
            # running as root!
            # sanitize: only allow "safe" environment variables
            # as these may have been specified by a non-root user
            env = {k: v for k, v in env.items() if k.startswith("XPRA_")}
        os.environ.update(env)


def set_gdk_backend() -> None:
    if os.environ.get("GDK_BACKEND"):
        return
    if is_Wayland(os.environ):
        os.environ["GDK_BACKEND"] = "wayland"
        return
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


def set_pyopengl_platform() -> None:
    gdk_backend = os.environ.get("GDK_BACKEND", "")
    if gdk_backend == "x11":
        os.environ["PYOPENGL_PLATFORM"] = "x11"
    elif gdk_backend == "wayland":
        os.environ["PYOPENGL_PLATFORM"] = "egl"


def check_gtk_client() -> None:
    no_gtk()
    check_gtk("client")

    # `find_spec` only raises when a parent package is missing,
    # it returns `None` when the module itself is:
    for mod in ("xpra.client.gui", "xpra.client.gtk3"):
        try:
            spec = find_spec(mod)
        except ImportError as e:
            raise InitExit(ExitCode.FILE_NOT_FOUND, f"`xpra-client-gtk3` is not installed: {e}") from None
        if not spec:
            raise InitExit(ExitCode.FILE_NOT_FOUND, f"`xpra-client-gtk3` is not installed: {mod!r} not found")


def gtk_init_check() -> bool:
    Gtk = gi_import("Gtk")
    if Gtk._version[0] > "3":
        r = Gtk.init_check()
    else:
        r = Gtk.init_check(argv=None)[0]
    if OSX:
        # `Gtk.init_check()` resets the macOS application activation policy
        # (it would show a dock icon): re-apply the `XPRA_HIDE_DOCK` preference
        from xpra.platform.darwin import hide_dock
        hide_dock()
    return bool(r)


def check_gtk(mode: str) -> None:
    # Clients and GTK helper subprocesses must select their backend before GTK is initialized.
    if POSIX and not OSX:
        set_gdk_backend()
    if not os.environ.get("PYOPENGL_PLATFORM"):
        set_pyopengl_platform()
    if not gtk_init_check():
        raise InitExit(ExitCode.NO_DISPLAY, f"{mode!r} failed to initialize Gtk, no display?")
    check_display()


def check_display() -> None:
    from xpra.platform.gui import can_access_display
    if not can_access_display():  # pragma: no cover
        raise InitExit(ExitCode.NO_DISPLAY, "cannot access display")


def verify_gir() -> None:
    try:
        from gi import repository
        if not repository:
            # cythonized code can bind None for missing imports
            raise ImportError("gi.repository")
    except ImportError as e:
        raise InitExit(ExitCode.FAILURE, f"the python gobject introspection bindings are missing: \n{e}")


def run_mode(script_file: str, cmdline: list[str], options, args: list[str], full_mode: str, defaults) -> ExitValue:
    mode_parts = full_mode.split(",")
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])

    # configure default logging handler:
    if POSIX and getuid() == options.uid == 0 and mode not in (
            "proxy", "autostart", "showconfig", "setup-ssl", "show-ssl", "menu-cache", "sbom",
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
    configure_seccomp(options.seccomp)
    options.landlock = configure_landlock(options.landlock)
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
        return do_run_mode(script_file, cmdline, options, args, full_mode, defaults)
    except ValueError as e:
        info(f"{e}")
        return ExitCode.UNSUPPORTED
    except KeyboardInterrupt as e:
        info(f"\ncaught {e!r}, exiting")
        return 128 + signal.SIGINT


def mode_argument_error(mode: str, message: str) -> InitExit:
    usage = tuple(f"xpra {line}" for line in get_usage() if line.split(" ")[0] == mode)
    if usage:
        message += ", usage: " + " or ".join(usage)
    return InitExit(ExitCode.ARGUMENT_MISMATCH, message)


def check_mode_flags(mode: str, flags: str, args: list[str]) -> None:
    for flag in flags.split(","):
        if flag == "no_extra_args":
            if args:
                raise mode_argument_error(mode, f"too many arguments for {mode!r}")
        elif flag == "max_one_arg":
            if len(args) > 1:
                raise mode_argument_error(mode, f"too many arguments for {mode!r}")
        elif flag == "requires_args":
            if not args:
                raise mode_argument_error(mode, f"{mode!r} requires an argument")
        elif flag == "posix":
            if not POSIX or OSX:
                raise InitExit(ExitCode.UNSUPPORTED, f"{mode!r} is not supported on this platform")
        elif flag == "audio":
            if not has_audio_support():
                raise InitExit(ExitCode.COMPONENT_MISSING, "no audio support!")
        elif flag == "x11":
            reqx11(mode)
        elif flag == "no_gtk":
            no_gtk()
        elif flag == "gtk_client":
            check_gtk_client()
        elif flag == "gtk":
            check_gtk(mode)
        elif flag:
            raise ValueError(f"invalid flag {flag!r} for {mode!r}")


def get_mode_handler(mode: str, args: list[str], flags: str, handler: Callable | str) -> Callable:
    """
    validates the arguments and runs the guards in `flags`,
    then returns the handler, importing it if it is specified as "module:function"
    """
    check_mode_flags(mode, flags, args)
    if callable(handler):
        return handler
    module_name, function_name = handler.split(":")
    from importlib import import_module
    return getattr(import_module(module_name), function_name)


def do_run_mode(script_file: str, cmdline: list[str], options, args: list[str], full_mode: str, defaults) -> ExitValue:
    mode_parts = full_mode.split(",", 1)
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])
    # keep the (normalized) mode on the options so that subsystems which only get `opts`
    # (ie: `parse_display_name`) can adjust their behaviour, ie: ssh agent forwarding:
    options.mode = mode
    if mode in SERVER_SUBCOMMANDS:
        return run_server_mode(script_file, cmdline, options, args, mode, full_mode, defaults)
    if mode in ("run", "exec") and args and args[0].startswith(":"):
        # for local displays, run via "_proxy_run"
        # which will use plain-X11 connections if needed:
        return run_proxy_run(options, script_file, cmdline, args, mode)
    if mode in CLIENT_SUBCOMMANDS or mode.startswith("request-"):
        return run_client(script_file, cmdline, options, args, mode)
    if entry := NO_ARGS_MODES.get(mode):
        return get_mode_handler(mode, args, *entry)()
    if entry := OPTIONS_MODES.get(mode):
        return get_mode_handler(mode, args, *entry)(options)
    if entry := ARGS_MODES.get(mode):
        return get_mode_handler(mode, args, *entry)(args)
    if entry := CMDLINE_MODES.get(mode):
        return get_mode_handler(mode, args, *entry)(cmdline)
    if entry := OPTIONS_ARGS_MODES.get(mode):
        return get_mode_handler(mode, args, *entry)(options, args)
    if entry := OPTIONS_ARGS_CMDLINE_MODES.get(mode):
        return get_mode_handler(mode, args, *entry)(options, args, cmdline)
    if mode == "recover":
        return run_recover(script_file, cmdline, options, args, defaults)
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
    if mode in ("_proxy_run", "_proxy_exec"):
        nox()
        return run_proxy_run(options, script_file, cmdline, args, "exec" if mode == "_proxy_exec" else "run")
    if mode == "_proxy" or mode.startswith("_proxy_"):
        nox()
        return run_proxy(options, script_file, cmdline, args, mode, defaults)
    if mode in ("keymap", "keymap-test"):
        # dumping the keymap of this system requires gtk,
        # `keymap-test` only needs it if no keymap file is specified:
        if mode == "keymap" or not any(os.path.isfile(arg) for arg in args):
            check_gtk(mode)
        from xpra.scripts import keymap_tool
        return keymap_tool.main(mode, args, cmdline)
    if mode == "gui-info":
        if (options.backend or "gtk") == "win32":
            no_gi_gtk_modules()
        else:
            check_gtk("gui-info")
        from xpra.platform import gui as platform_gui
        return platform_gui.main(cmdline)
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


def run_send_file(extra_args) -> ExitValue:
    sockpath = os.environ.get("XPRA_SERVER_SOCKET")
    if not sockpath:
        if display := os.environ.get("DISPLAY", ""):
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


def run_autostart(args) -> ExitValue:
    def err(msg) -> int:
        print(msg)
        print("Usage: xpra autostart enable|disable|status")
        return 1

    # no CLI argument: show the GUI
    if not args or WIN32 or gtk_init_check():
        check_display()
        from xpra.gtk.dialogs.autostart import main as autostart_main
        return autostart_main(args)

    if len(args) != 1:
        return err("invalid number of arguments")
    arg = args[0].lower()
    if arg not in ("enable", "disable", "status"):
        return err(f"invalid argument {arg!r}")
    if OSX:
        print("autostart is not supported on this platform")
        return 1
    from xpra.platform.autostart import set_autostart, get_status
    if arg == "status":
        print(get_status())
    else:
        set_autostart(arg == "enable")
    return 0


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
            from xpra.config.info import get_build_info

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


# the subcommands that only need to call a single function, grouped by the arguments it takes,
# the flags are the guards to run and the argument checks to make before calling it:
NO_ARGS_MODES: dict[str, tuple[str, Callable | str]] = {
    "desktop-greeter": ("no_extra_args,gtk_client", "xpra.gtk.dialogs.desktop_greeter:main"),
    "docs": ("no_extra_args", run_docs),
    "documentation": ("no_extra_args", run_docs),
    "about": ("no_extra_args", run_about),
    "license": ("no_extra_args", "xpra.gtk.dialogs.about:run_license"),
    "html5": ("no_extra_args", run_html5),
    "opengl-save-probe": ("no_extra_args,gtk_client", "xpra.scripts.glprobe:run_glsaveprobe"),
    "video": ("no_extra_args", "xpra.codecs.video:main"),
    "nvinfo": ("no_extra_args", "xpra.codecs.nvidia.util:main"),
    "crypto-info": ("no_extra_args", "xpra.net.crypto:main"),
    "compression": ("no_extra_args", "xpra.net.compression:main"),
    "packet-encoding": ("no_extra_args", "xpra.net.packet_encoding:main"),
    "dbus-system-list": ("no_extra_args", "xpra.dbus.common:run_dbus_system_list"),
    "dbus-session-list": ("no_extra_args", "xpra.dbus.common:run_dbus_session_list"),
    "applications-menu": ("no_extra_args", "xpra.server.menu_provider:run_applications_menu"),
    "sessions-menu": ("no_extra_args", "xpra.server.menu_provider:run_sessions_menu"),
    "menu-cache": ("no_extra_args", "xpra.platform.menu_helper:run_menu_cache"),
}
OPTIONS_MODES: dict[str, tuple[str, Callable | str]] = {
    "mdns-gui": ("no_extra_args,gtk_client", "xpra.gtk.dialogs.mdns_gui:run_mdns_gui"),
    "sessions": ("no_extra_args,gtk_client", "xpra.gtk.dialogs.sessions_gui:run_sessions_gui"),
    "replay": ("no_extra_args", "xpra.gtk.dialogs.replay:do_main"),
    "opengl-test": ("no_extra_args,gtk_client", "xpra.scripts.glprobe:run_gltest"),
    "start-gui": ("no_extra_args,gtk_client", "xpra.gtk.dialogs.start_gui:main"),
    "opengl": ("no_extra_args", "xpra.scripts.glprobe:run_glcheck"),
    "opengl-probe": ("no_extra_args,gtk_client", "xpra.scripts.glprobe:run_glprobe"),
    "root-size": ("no_extra_args", "xpra.scripts.display:run_root_size"),
    "xvfb-command": ("no_extra_args", "xpra.config.vfb:run_xvfb_command"),
}
ARGS_MODES: dict[str, tuple[str, Callable | str]] = {
    "list-mdns": ("max_one_arg,no_gtk", "xpra.net.mdns.list:run_list_mdns"),
    "xwait": ("no_gtk", "xpra.scripts.display:run_xwait"),
    "xshm": ("x11,no_gtk", "xpra.scripts.display:run_xshm"),
    "xinfo": ("no_gtk", "xpra.scripts.display:run_xinfo"),
    "wminfo": ("x11,no_gtk", "xpra.scripts.display:run_wminfo"),
    "wmname": ("x11,no_gtk", "xpra.scripts.display:run_wmname"),
    "pinentry": ("gtk_client", "xpra.scripts.pinentry:run_pinentry"),
    "_dialog": ("gtk_client", "xpra.gtk.dialogs.confirm_dialog:show_confirm_dialog"),
    "_pass": ("gtk_client", "xpra.gtk.dialogs.pass_dialog:show_pass_dialog"),
    "send-file": ("gtk", run_send_file),
    "splash": ("gtk", "xpra.gtk.dialogs.splash:main"),
    "example": ("gtk_client", "xpra.gtk.examples.run:run_example"),
    "printing-info": ("", "xpra.platform.printing:main"),
    "version-check": ("", run_version_check),
    "toolbox": ("gtk_client", "xpra.gtk.dialogs.toolbox:main"),
    "auth": ("requires_args", "xpra.auth.auth_helper:run_auth"),
    "notify": ("requires_args", "xpra.notification.dbus_backend:run_notify"),
    "u2f": ("", "xpra.gtk.dialogs.u2f_tool:run_u2f"),
    "fido2": ("", "xpra.gtk.dialogs.fido2_tool:run_fido2"),
    "otp": ("", "xpra.gtk.dialogs.otp:main"),
    "configure": ("", "xpra.gtk.configure.main:do_main"),
    "wait-for-x11": ("max_one_arg", "xpra.x11.wait:main"),
    "wait-for-wayland": ("max_one_arg", "xpra.wayland.client.wait:main"),
    "sbom": ("", run_sbom),
    "showsetting": ("requires_args", "xpra.scripts.settings:run_showsetting"),
    "autostart": ("", run_autostart),
    "_audio_record": ("audio", "xpra.audio.wrapper:run_audio_record"),
    "_audio_play": ("audio", "xpra.audio.wrapper:run_audio_play"),
    "_audio_meter": ("audio", "xpra.audio.wrapper:run_audio_meter"),
    "_audio_query": ("audio", "xpra.audio.wrapper:run_audio_query"),
    "set": ("requires_args", "xpra.scripts.settings:run_set"),
    "setting": ("requires_args", "xpra.scripts.settings:run_set"),
    "unset": ("requires_args", "xpra.scripts.settings:run_unset"),
    "launcher": ("gtk_client", "xpra.client.gtk3.launcher:run_launcher"),
    "bug-report": ("gtk_client", "xpra.gtk.dialogs.bug_report:run_bug_report"),
    "input_pass": ("max_one_arg,gtk_client", "xpra.scripts.pinentry:run_input_pass"),
    "webcam": ("max_one_arg,gtk", "xpra.gtk.dialogs.show_webcam:run_webcam"),
    "encoding": ("", "xpra.codecs.loader:run_encoding"),
    "rdp": ("requires_args,max_one_arg", "xpra.net.rdp.probe:run_rdp_probe"),
}
CMDLINE_MODES: dict[str, tuple[str, Callable | str]] = {
    "keyboard": ("", "xpra.platform.keyboard:main"),
    "gtk-info": ("gtk", "xpra.gtk.info:main"),
    "network-info": ("", "xpra.net.net_util:main"),
    "path-info": ("", "xpra.platform.paths:main"),
    "version-info": ("", "xpra.scripts.version:main"),
}
OPTIONS_ARGS_MODES: dict[str, tuple[str, Callable | str]] = {
    "list": ("no_extra_args,no_gtk", "xpra.scripts.sessions:run_list"),
    "list-windows": ("no_extra_args,no_gtk", "xpra.scripts.sessions:run_list_windows"),
    "list-clients": ("no_extra_args,no_gtk", "xpra.scripts.sessions:run_list_clients"),
    "list-sessions": ("no_extra_args,no_gtk", "xpra.scripts.sessions:run_list_sessions"),
    "displays": ("no_gtk", "xpra.scripts.display:run_displays"),
    "clean-displays": ("posix,no_gtk", "xpra.scripts.display:run_clean_displays"),
    "clean-sockets": ("max_one_arg,no_gtk", "xpra.scripts.sessions:run_clean_sockets"),
    "clean": ("no_gtk", "xpra.scripts.sessions:run_clean"),
    "monitor-info": ("", "xpra.scripts.display:run_monitor_info"),
    "set-monitor": ("", "xpra.scripts.display:run_set_monitor"),
    "showconfig": ("", "xpra.scripts.settings:run_showconfig"),
    "xvfb": ("max_one_arg,x11", "xpra.x11.vfb_util:run_xvfb"),
}
OPTIONS_ARGS_CMDLINE_MODES: dict[str, tuple[str, Callable | str]] = {
    "top": ("no_gtk", "xpra.scripts.clients:run_top"),
    "stop": ("no_gtk", "xpra.scripts.sessions:run_stop"),
    "exit": ("no_gtk", "xpra.scripts.sessions:run_exit"),
    "encode": ("requires_args,no_gtk", "xpra.scripts.clients:run_encode"),
    "session-info": ("gtk_client", "xpra.scripts.clients:run_session_info"),
    "setup-ssl": ("max_one_arg", "xpra.net.tls.common:setup_ssl"),
    "show-ssl": ("max_one_arg", "xpra.net.tls.common:show_ssl"),
    "webcam-client": ("requires_args,gtk", "xpra.client.gtk3.webcam_window:run_webcam_client"),
}


if __name__ == "__main__":  # pragma: no cover
    code = main("xpra.exe", sys.argv)
    if not code:
        code = 0
    sys.exit(code)
