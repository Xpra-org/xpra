# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=import-outside-toplevel

import sys
import shlex
import os.path
import datetime
from dataclasses import dataclass
from typing import NoReturn, Final
from subprocess import Popen

from xpra.util.io import info, warn, wait_for_socket, which
from xpra.util.parsing import FALSE_OPTIONS, parse_str_dict, str_to_bool, parse_bool_or
from xpra.scripts.parsing import MODE_ALIAS
from xpra.scripts.main import nox, parse_env
from xpra.scripts.sessions import get_xpra_sessions
from xpra.scripts.config import (
    InitException, InitInfo, InitExit,
    OPTION_TYPES, CLIENT_OPTIONS,
    fixup_options,
)
from xpra.common import noerr
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.server import CLOBBER_UPGRADE, CLOBBER_USE_DISPLAY
from xpra.net.constants import SocketState, ConnectionMessage
from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import POSIX, WIN32, OSX, force_quit, getuid, get_hex_uuid
from xpra.util.system import SIGNAMES
from xpra.util.str_fn import nicestr, csv
from xpra.util.io import stderr_print
from xpra.util.env import envbool, envint, get_saved_env, get_saved_env_var, OSEnvContext
from xpra.util.child_reaper import get_child_reaper
from xpra.platform.dotxpra import DotXpra

DESKTOP_GREETER = envbool("XPRA_DESKTOP_GREETER", True)
SYSTEM_DBUS_SOCKET = "/run/dbus/system_bus_socket"


def deadly_signal(signum, _frame=None) -> NoReturn:
    signame = SIGNAMES.get(signum, signum)
    info(f"got deadly signal {signame}, exiting\n")
    # This works fine in tests, but for some reason if I use it here, then I
    # get bizarre behavior where the signal handler runs, and then I get a
    # KeyboardException (?!?), and the KeyboardException is handled normally
    # and exits the program (causing the cleanup handlers to be run again):
    # signal.signal(signum, signal.SIG_DFL)
    # kill(os.getpid(), signum)
    force_quit(128 + int(signum))


def display_name_check(display_name: str) -> None:
    """ displays a warning
        when a low display number is specified """
    if not display_name.startswith(":"):
        return
    n = display_name[1:].split(".")[0]  # ie: ":0.0" -> "0"
    try:
        dno = int(n)
    except (ValueError, TypeError):
        raise InitExit(ExitCode.NO_DISPLAY, f"invalid display number {n}") from None
    else:
        if 0 <= dno < 10:
            warn(f"WARNING: low display number: {dno}")
            warn(" You are attempting to run the xpra server")
            warn(f" against a low X11 display number: {display_name!r}")
            warn(" This is generally not what you want.")
            warn(" You should probably use a higher display number")
            warn(" just to avoid any confusion and this warning message.")


def print_DE_warnings() -> None:
    de = os.environ.get("XDG_SESSION_DESKTOP", "") or os.environ.get("SESSION_DESKTOP", "")
    if not de:
        return
    from xpra.log import Logger
    log = Logger("server")
    log.warn(f"Warning: xpra start from an existing {de!r} desktop session")
    log.warn(" without using dbus-launch,")
    log.warn(" notifications forwarding may not work")
    log.warn(" try using a clean environment, a dedicated user,")
    log.warn(" or disable xpra's notifications option")


def guess_xpra_display(socket_dir, socket_dirs) -> str:
    dotxpra = DotXpra(socket_dir, socket_dirs)
    results = dotxpra.sockets()
    live = [display for state, display in results if state == SocketState.LIVE]
    if not live:
        raise InitExit(ExitCode.SERVER_NOT_FOUND, "no existing xpra servers found")
    if len(live) > 1:
        raise InitExit(ExitCode.SERVER_NOT_FOUND, "too many existing xpra servers found, cannot guess which one to use")
    return live[0]


def show_encoding_help(opts) -> int:
    # avoid errors and warnings:
    opts.pidfile = None
    opts.encoding = ""
    opts.clipboard = False
    opts.notifications = False
    print("xpra server supports the following encodings:")
    print("(please wait, encoder initialization may take a few seconds)")
    # disable info logging which would be confusing here
    from xpra.log import get_all_loggers, set_default_level
    import logging
    set_default_level(logging.WARN)
    logging.root.setLevel(logging.WARN)
    for x in get_all_loggers():
        if x.getEffectiveLevel() == logging.INFO:
            x.setLevel(logging.WARN)
    from xpra.server import features as sf
    sf.pulseaudio = sf.audio = sf.av_sync = False
    sf.clipboard = sf.command = sf.control = sf.dbus = sf.file = sf.printer = sf.debug = False
    sf.keyboard = sf.mouse = False
    sf.mmap = sf.logging = sf.ping = sf.bandwidth = sf.notification = sf.rfb = sf.shell = sf.webcam = False
    from xpra.server.base import ServerBase
    sb = ServerBase()
    sb.init(opts)
    from xpra.codecs.constants import PREFERRED_ENCODING_ORDER, HELP_ORDER
    if "help" in opts.encodings:
        sb.allowed_encodings = PREFERRED_ENCODING_ORDER
    from xpra.server.subsystem.encoding import EncodingServer
    assert isinstance(sb, EncodingServer)
    EncodingServer.setup(sb)
    from xpra.codecs.loader import encoding_help
    for e in (x for x in HELP_ORDER if x in sb.encodings):
        print(" * " + encoding_help(e))
    return 0


def make_server_app(mode_attrs: dict[str, str], opts, clobber: int, mode: str,
                    display_name: str):
    if "backend" not in mode_attrs:
        mode_attrs["backend"] = opts.backend
    if mode.startswith("shadow"):
        # "shadow" -> multi-window=True, "shadow-screen" -> multi-window=False
        mode_attrs["multi-window"] = str(mode == "shadow")
        from xpra.platform.shadow_server import ShadowServer
        return ShadowServer(display_name, mode_attrs)
    if mode == "proxy":
        from xpra.platform.proxy_server import ProxyServer
        return ProxyServer()
    if mode == "expand":
        from xpra.x11.server.expand import ExpandServer
        return ExpandServer(mode_attrs)
    if mode == "encoder":
        from xpra.server.encoder.server import EncoderServer
        return EncoderServer()
    if mode == "runner":
        with OSEnvContext():
            # unit test env var would inject SignalEmitter class twice:
            os.environ.pop("XPRA_UNIT_TEST", None)
            from xpra.server.runner.server import RunnerServer
            return RunnerServer()
    if mode in ("seamless", "upgrade"):
        if opts.backend == "wayland":
            from xpra.wayland.server import WaylandSeamlessServer
            return WaylandSeamlessServer()
        from xpra.x11.server.seamless import SeamlessServer
        return SeamlessServer(clobber)
    if mode == "desktop":
        from xpra.x11.desktop.desktop_server import XpraDesktopServer
        return XpraDesktopServer()
    assert mode == "monitor"
    from xpra.x11.desktop.monitor_server import XpraMonitorServer
    return XpraMonitorServer()


def verify_display(xvfb=None, display_name=None, shadowing=False, log_errors=True, timeout=None) -> bool:
    # check that we can access the X11 display:
    from xpra.log import Logger
    log = Logger("screen", "x11")
    log("verify_display%s", (xvfb, display_name, shadowing, log_errors, timeout))
    from xpra.x11.vfb_util import verify_display_ready, VFB_WAIT
    if timeout is None:
        timeout = VFB_WAIT
    if not verify_display_ready(xvfb, display_name, shadowing, log_errors, timeout):
        return False
    log(f"X11 display {display_name!r} is ready")
    return True


def is_splash_enabled(mode: str, daemon: bool, splash: bool, display: str) -> bool:
    from xpra.server.subsystem.splash import is_splash_enabled as splash_enabled
    return splash_enabled(mode, daemon, splash, display)


def request_exit(uri: str) -> bool:
    from xpra.platform.paths import get_xpra_command
    cmd = get_xpra_command() + ["exit", uri]
    env = os.environ.copy()
    # don't wait too long:
    env["XPRA_CONNECT_TIMEOUT"] = "5"
    # don't log disconnect message
    env["XPRA_LOG_DISCONNECT"] = "0"
    env["XPRA_EXIT_MESSAGE"] = nicestr(ConnectionMessage.SERVER_UPGRADE)
    try:
        p = Popen(cmd, env=env)
        p.wait()
    except OSError as e:
        stderr_print("Error: failed to 'exit' the server to upgrade")
        stderr_print(f" {e}\n")
        return False
    return p.poll() in (ExitCode.OK, ExitCode.UPGRADE)


def trymkdir(path: str, mode=0o755) -> None:
    if not os.path.exists(path):
        try:
            os.mkdir(path, mode)
        except OSError as e:
            warn(f"Warning: failed to create {path!r} {e}")


def start_dbus() -> None:
    ROOT: bool = POSIX and getuid() == 0
    SYSTEM_DBUS = envbool("XPRA_SYSTEM_DBUS", ROOT)
    SYSTEM_DBUS_TIMEOUT = envint("XPRA_SYSTEM_DBUS_TIMEOUT", 5)
    MACHINE_ID: Final[str] = "/var/lib/dbus/machine-id"
    if SYSTEM_DBUS and not wait_for_socket(SYSTEM_DBUS_SOCKET, SYSTEM_DBUS_TIMEOUT):
        if not os.path.exists(MACHINE_ID):
            try:
                trymkdir("/var/lib")
                trymkdir("/var/lib/dbus")
                import uuid
                machine_id = uuid.uuid4().hex
                with open(MACHINE_ID, "w") as f:
                    f.write(machine_id)
                warn(f"initialized dbus machine_id {machine_id}\n")
            except OSError as e:
                warn(f"unable to create machine_id: {e}\n")
        trymkdir("/run/dbus")
        Popen(["dbus-daemon", "--system", "--fork"]).wait()
        if not wait_for_socket(SYSTEM_DBUS_SOCKET, SYSTEM_DBUS_TIMEOUT):
            warn("dbus-daemon failed to start\n")
        else:
            warn("started system dbus daemon\n")


def start_cupsd() -> None:
    ROOT: bool = POSIX and getuid() == 0
    SYSTEM_CUPS = envbool("XPRA_SYSTEM_CUPS", ROOT)
    SYSTEM_CUPS_TIMEOUT = envint("XPRA_SYSTEM_CUPS_TIMEOUT", 5)
    SYSTEM_CUPS_SOCKET = "/run/cups/cups.sock"
    if SYSTEM_CUPS and not wait_for_socket(SYSTEM_CUPS_SOCKET, SYSTEM_CUPS_TIMEOUT):
        trymkdir("/run/cups")
        cupsd = which("cupsd")
        if not cupsd:
            warn("Warning: unable to launch `cupsd`, command not found")
        else:
            Popen([cupsd]).wait()
            if not wait_for_socket(SYSTEM_CUPS_SOCKET, SYSTEM_CUPS_TIMEOUT):
                warn("cupsd failed to start\n")
            else:
                warn("started system cupsd daemon\n")


@dataclass
class VFBStartResult:
    xvfb: Popen | None
    xvfb_pid: int
    devices: dict
    display_name: str
    xvfb_cmd: tuple[str, ...] = ()
    displayfd: int = 0


def add_desktop_greeter(opts, starting: str, use_display: bool | None) -> None:
    if not POSIX or starting != "desktop" or use_display or not DESKTOP_GREETER:
        return
    # if there are no start commands, auto-add a greeter:
    commands = []
    for start_prop in (
            "start", "start-late",
            "start-child", "start-child-late",
            "start-after-connect", "start-child-after-connect",
            "start-on-connect", "start-child-on-connect",
            "start-on-disconnect", "start-child-on-disconnect",
            "start-on-last-client-exit", "start-child-on-last-client-exit",
    ):
        commands += list(getattr(opts, start_prop.replace("-", "_")))
    if not commands:
        opts.start.append("xpra desktop-greeter")


def has_child_arg(opts) -> bool:
    return any((
        opts.start_child,
        opts.start_child_late,
        opts.start_child_on_connect,
        opts.start_child_after_connect,
        opts.start_child_on_last_client_exit,
    ))


def sanitize_dbus_env(dbus: str) -> None:
    if str(dbus).lower() == "keep":
        return
    # remove anything pointing to dbus from the current env
    # (so we only detect a dbus instance started by pam,
    # and override everything else)
    for k in tuple(os.environ.keys()):
        if k.startswith("DBUS_"):
            del os.environ[k]


def resolve_server_display_name(opts, extra_args: list[str], desktop_display: str,
                                shadowing: bool, expanding: bool, runner: bool,
                                upgrading: bool, proxying: bool, encoder: bool,
                                use_display: bool | None) -> tuple[str, str]:
    display_options = ""
    if (shadowing or expanding or runner) and not extra_args:
        if runner:
            display_name = "runner-%i" % os.getpid()
        elif WIN32 or OSX:
            # just a virtual name for the only display available:
            display_name = "Main"
        else:
            from xpra.scripts.display import guess_display
            display_name = guess_display(desktop_display, sessions_dir=opts.sessions_dir)
    elif upgrading and not extra_args:
        display_name = guess_xpra_display(opts.socket_dir, opts.socket_dirs)
    else:
        if len(extra_args) > 1:
            raise InitException(f"too many extra arguments ({len(extra_args)}): only expected a display number")
        if len(extra_args) == 1:
            display_name = extra_args[0]
            # look for display options:
            # ie: ":1,DP-2" -> ":1" "DP-2"
            if display_name and display_name.find(",") > 0:
                display_name, display_options = display_name.split(",", 1)
            if not shadowing and not upgrading and not use_display:
                display_name_check(display_name)
        else:
            if proxying or encoder or runner:
                # find a free display number:
                dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
                all_displays = dotxpra.sockets()
                # ie: [("LIVE", ":100"), ("LIVE", ":200"), ...]
                displays = [v[1] for v in all_displays]
                display_name = ""
                for x in range(1000, 20000):
                    v = f":{x}"
                    if v not in displays:
                        display_name = v
                        break
                if not display_name:
                    raise InitException("you must specify a free virtual display name to use with the proxy server")
            elif use_display:
                # only use automatic guess for xpra displays and not X11 displays:
                display_name = guess_xpra_display(opts.socket_dir, opts.socket_dirs)
            else:
                # We will try to find one automatically
                # Use the temporary magic value "S" as marker:
                display_name = "S" + str(os.getpid())
    return display_name, display_options


def request_upgrade_display(display_name: str, session: dict) -> bool:
    if not session:
        return False
    socket_path = session.get("socket-path")
    uri = f"socket://{socket_path}" if socket_path else display_name
    if request_exit(uri):
        # the server has terminated as we had requested,
        # but it may need a second to disconnect the clients
        # and then close the sockets cleanly
        # (so we can re-create them safely)
        import time
        time.sleep(1)
        return True
    warn(f"server for {display_name} is not exiting")
    return False


def set_vfb_startup_state(app, state: VFBStartResult) -> None:
    display = app.get_subsystem("display")
    if not display:
        return
    if hasattr(display, "set_vfb_startup_state"):
        display.set_vfb_startup_state(state)
    if hasattr(display, "publish_displayfd"):
        display.publish_displayfd(state.display_name, state.displayfd)


def init_virtual_devices(app, devices: dict) -> None:
    if not devices:
        return
    pointer = app.get_subsystem("pointer")
    if pointer and hasattr(pointer, "init_virtual_devices"):
        pointer.init_virtual_devices(devices)


def do_run_server(script_file: str, cmdline: list[str], opts,
                  extra_args: list[str], full_mode: str, defaults) -> ExitValue:
    if opts.encoding == "help" or "help" in opts.encodings:
        return show_encoding_help(opts)

    mode_parts = full_mode.split(",", 1)
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])
    if mode not in (
        "seamless", "desktop", "monitor", "expand", "shadow", "shadow-screen",
        "upgrade", "upgrade-seamless", "upgrade-desktop", "upgrade-monitor",
        "proxy",
        "encoder",
        "runner"
    ):
        raise ValueError(f"unsupported server mode {mode}")
    mode_parts = full_mode.split(",", 1)
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])
    opts.mode = mode
    mode_attrs: dict[str, str] = {}
    if len(mode_parts) > 1:
        mode_attrs = parse_str_dict(mode_parts[1])
    starting = mode if mode in ("seamless", "desktop", "monitor") else ""
    expanding = mode == "expand"
    upgrading = mode.startswith("upgrade")
    shadowing = mode.startswith("shadow")
    proxying = mode == "proxy"
    encoder = mode == "encoder"
    runner = mode == "runner"
    use_display = shadowing or expanding or parse_bool_or("use-display", opts.use_display)

    desktop_display = nox()
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = os.path.expanduser("~")
        warn(f"current working directory does not exist, using {cwd!r}\n")
    # Generate the script text now, because os.getcwd() will
    # change if/when we daemonize:
    from xpra.server.runner_script import xpra_runner_shell_script, xpra_env_shell_script
    save_env = os.environ.copy()
    save_env.update(parse_env(opts.env))
    env_script = xpra_env_shell_script(opts.socket_dir, save_env)
    run_xpra_script = ""
    if POSIX and getuid() != 0 and BACKWARDS_COMPATIBLE:
        run_xpra_script = env_script + xpra_runner_shell_script(script_file, cwd)

    sanitize_dbus_env(opts.dbus)
    if (upgrading or shadowing) and opts.pulseaudio is None:
        # there should already be one running
        # so change None ('auto') to False
        opts.pulseaudio = False
    # daemonize will chdir to "/", so try to use an absolute path:
    if opts.password_file:
        opts.password_file = tuple(os.path.abspath(x) for x in opts.password_file)

    # resolve `forward_xdg_open` to a boolean:
    if opts.forward_xdg_open is None:
        opts.forward_xdg_open = mode == "seamless"

    if not proxying and not shadowing and POSIX and not OSX:
        SERVER_BACKENDS = ("auto", "gtk", "x11", "wayland")
        if opts.backend.lower() not in SERVER_BACKENDS:
            raise InitExit(ExitCode.UNSUPPORTED, f"{mode!r} does not support the {opts.backend!r} backend, only %s" % csv(SERVER_BACKENDS))
        if opts.backend.lower() in ("auto", "gtk"):
            os.environ["GDK_BACKEND"] = "x11"

    if proxying or upgrading:
        # when proxying or upgrading, don't exec any plain start commands:
        opts.start = opts.start_child = opts.start_late = opts.start_child_late = ()
    elif opts.exit_with_children:
        if not has_child_arg(opts):
            msg = "exit-with-children was specified but start-child* is missing!"
            warn(msg)
            warn(" command line is: %r" % shlex.join(cmdline))
            raise InitException(msg)
    elif opts.start_child:
        warn("Warning: the 'start-child' option is used,")
        warn(" but 'exit-with-children' is not enabled,")
        warn(" you should just use 'start' instead")

    # get the display name:
    display_name, display_options = resolve_server_display_name(opts, extra_args, desktop_display,
                                                                shadowing, expanding, runner, upgrading,
                                                                proxying, encoder, use_display)

    if upgrading:
        if not display_name:
            noerr(sys.stderr.write, "no display found to upgrade\n")
            return ExitCode.NO_DISPLAY
        if POSIX and not OSX and get_saved_env_var("DISPLAY", "") == display_name:
            warn("Warning: upgrading from an environment connected to the same display")
        # try to stop the existing server if it exists:
        dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
        sessions = get_xpra_sessions(dotxpra, ignore_state=(SocketState.UNKNOWN, SocketState.DEAD),
                                     matching_display=display_name, query=True)
        session = sessions.get(display_name, {})
        use_display = request_upgrade_display(display_name, session) or use_display

    protected_env = {}

    if str_to_bool(opts.dbus):
        start_dbus()
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = f"unix:path={SYSTEM_DBUS_SOCKET}"
        protected_env["DBUS_SYSTEM_BUS_ADDRESS"] = f"unix:path={SYSTEM_DBUS_SOCKET}"

    if str_to_bool(opts.printing):
        start_cupsd()

    # Daemonize:
    if POSIX and opts.daemon:
        from xpra.util.daemon import daemonize
        daemonize()

    clobber = int(upgrading) * CLOBBER_UPGRADE | int(use_display or 0) * CLOBBER_USE_DISPLAY
    start_vfb: bool = not (shadowing or proxying or clobber or expanding or encoder or runner) and opts.xvfb.lower() not in FALSE_OPTIONS and opts.backend != "wayland"
    xauth_data: str = get_hex_uuid() if start_vfb else ""
    if start_vfb and opts.sync_xvfb is None and any(x in opts.xvfb for x in ("Xephyr", "Xnest")):
        # automatically enable sync-xvfb for Xephyr and Xnest:
        opts.sync_xvfb = 50

    # warn early about this:
    if starting in ("seamless", "desktop", "monitor") and desktop_display and opts.notifications and not opts.dbus_launch:
        print_DE_warnings()
    add_desktop_greeter(opts, starting, use_display)
    # make sure we don't start ibus in these modes:
    if POSIX and not OSX and (upgrading or shadowing):
        opts.input_method = "keep"

    from xpra.server.features import set_server_features
    set_server_features(opts, mode)

    from xpra.log import Logger
    log = Logger("server")
    try:
        app = make_server_app(mode_attrs, opts, clobber, mode, display_name)
    except ImportError as e:
        log("failed to make server class", exc_info=True)
        log.error("Error: the server cannot be started,")
        log.error(" some critical component is missing:")
        log.estr(e)
        return ExitCode.COMPONENT_MISSING

    # do this early - because we want to prepare the runtime environment early,
    # but only change uid after VFB setup:
    process = app.get_subsystem("process")
    assert process
    process.init(opts)
    process.prepare_environment(display_name, xauth_data, start_vfb, shadowing, starting, protected_env)
    pam = process.pam
    protected_env = process.protected_env

    session_files = app.get_subsystem("session-files")
    assert session_files
    session_files.init(opts)
    session_files.setup_session_dir(mode, opts.sessions_dir, display_name)
    if upgrading:
        # if we had saved the start / start-desktop config, reload it:
        session_files.apply_config(opts, cmdline)
        opts.mode = mode = opts.mode.removeprefix("upgrade-").removeprefix("start-")

    if splash := app.get_subsystem("splash"):
        splash.init(opts)
        splash.setup_splash(display_name)

    def progress(pct: int, msg: str) -> None:
        if splash := app.get_subsystem("splash"):
            splash.progress(pct, msg)

    progress(30, "initializing server")

    session_files.write_config(opts)
    session_files.write_session_file("cmdline", "\n".join(cmdline) + "\n")
    session_files.write_session_file("server.env", env_script)
    if run_xpra_script:
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        assert BACKWARDS_COMPATIBLE
        from xpra.server.runner_script import write_runner_shell_scripts
        write_runner_shell_scripts(run_xpra_script)

    log_to_file = opts.daemon or envbool("XPRA_LOG_TO_FILE")
    if daemon := app.get_subsystem("daemon"):
        extra_expand = {"TIMESTAMP": datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}
        daemon.setup_log(start_vfb, log_to_file, display_name, extra_expand)
    else:
        from xpra.server.subsystem.daemon import DaemonServer
        DaemonServer.get_server_log_dir(start_vfb, log_to_file, opts.log_dir or "")
    log("env=%s", os.environ)

    progress(30, "creating network sockets")
    app.parse_socket_options(opts)
    app.init_sockets(retry=10 * int(upgrading))

    from xpra.server.subsystem.xvfb import XvfbManager
    xvfb = app.add_subsystem(XvfbManager)
    xvfb.init(opts)
    xvfb.connect("display-name", session_files.display_name_changed)
    vfb_result = xvfb.setup_vfb(display_name, start_vfb, xauth_data,
                                protected_env, pam, shadowing, proxying, encoder, runner, starting,
                                clobber, use_display, upgrading,
                                progress)
    use_display = xvfb.use_display
    display_name = vfb_result.display_name

    app.protected_env = protected_env
    # Change uid as early as possible, but after VFB setup:
    process.setup()
    app.init_subsystems()

    def server_not_started(msg="server not started") -> None:
        progress(100, msg)
        # check the initial 'mode' value instead of "upgrading" or "upgrading_desktop"
        # as we may have switched to "starting=True"
        # if the existing server has exited as we requested
        if mode.startswith("upgrade") or use_display:
            # something abnormal occurred,
            # don't kill the vfb on exit:
            from xpra.server import ServerExitMode
            app._exit_mode = ServerExitMode.EXIT
        app.cleanup()

    try:
        set_vfb_startup_state(app, vfb_result)
        app.display_options = display_options
        app.original_desktop_display = desktop_display
        app.init(opts)
        progress(60, "creating local sockets")
        app.init_local_sockets(opts, display_name, clobber)
        progress(90, "finalizing")
        app.setup()
        init_virtual_devices(app, vfb_result.devices)
    except InitInfo as e:
        for m in str(e).split("\n"):
            log.info("%s", m)
        server_not_started(str(e))
        return ExitCode.OK
    except InitExit as e:
        log_fn = log.error if int(e.status) else log.info
        for m in str(e).split("\n"):
            log_fn("%s", m)
        server_not_started(str(e))
        return e.status
    except InitException as e:
        log("%s failed to start", app, exc_info=True)
        log.error("xpra server initialization error:")
        for m in str(e).split("\n"):
            log.error(" %s", m)
        server_not_started(str(e))
        return ExitCode.FAILURE
    except Exception as e:
        log.error("Error: cannot start the %s server", app.session_type, exc_info=True)
        log.error(str(e))
        log.info("")
        server_not_started(str(e))
        return ExitCode.FAILURE

    ##############
    if opts.attach is True:
        attach_client(opts, defaults)

    progress(100, "running")
    log("%s()", app.run)
    r = app.run()
    log("%s()=%s", app.run, r)
    return r or 0


def attach_client(options, defaults) -> None:
    from xpra.platform.paths import get_xpra_command
    cmd = get_xpra_command() + ["attach"]
    display_name = os.environ.get("DISPLAY", "")
    if display_name:
        cmd += [display_name]
    # options has been "fixed up", make sure this has too:
    fixup_options(defaults)
    for x in CLIENT_OPTIONS:
        f = x.replace("-", "_")
        try:
            d = getattr(defaults, f)
            c = getattr(options, f)
        except Exception as e:
            warn(f"error on {f}: {e}")
            continue
        if c != d:
            if OPTION_TYPES.get(x) is list:
                v = ",".join(str(i) for i in c)
            else:
                v = str(c)
            cmd.append(f"--{x}={v}")
    env = get_saved_env()
    proc = Popen(cmd, env=env, start_new_session=POSIX and not OSX)
    get_child_reaper().add_process(proc, "client-attach", cmd, ignore=True, forget=False)
