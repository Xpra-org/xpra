# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=import-outside-toplevel

import sys
import glob
import shlex
import os.path
import datetime
from dataclasses import dataclass
from typing import Any, NoReturn, Final
from subprocess import Popen
from collections.abc import Sequence, Callable

from xpra import __version__
from xpra.scripts.session import (
    get_session_dir, make_session_dir, session_file_path,
    load_session_file, save_session_file
)
from xpra.util.io import info, warn, wait_for_socket, which
from xpra.util.parsing import (
    FALSE_OPTIONS, ALL_BOOLEAN_OPTIONS,
    parse_str_dict, str_to_bool, parse_bool_or, parse_resolutions, get_refresh_rate_for_value,
)
from xpra.scripts.parsing import fixup_defaults, MODE_ALIAS
from xpra.scripts.common import no_gtk
from xpra.scripts.main import (
    nox,
    validate_encryption, parse_env,
    make_progress_process,
)
from xpra.scripts.display import stat_display_socket, X11_SOCKET_DIR
from xpra.scripts.sessions import get_xpra_sessions
from xpra.scripts.config import (
    InitException, InitInfo, InitExit,
    OPTION_TYPES, CLIENT_ONLY_OPTIONS, CLIENT_OPTIONS,
    fixup_options, make_defaults_struct, read_config, dict_to_validated_config,
    xvfb_command,
)
from xpra.common import noerr, noop
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.server import CLOBBER_UPGRADE, CLOBBER_USE_DISPLAY
from xpra.net.constants import SocketState, ConnectionMessage
from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import (
    POSIX, WIN32, OSX,
    force_quit,
    get_username_for_uid, getuid, find_group,
    get_hex_uuid,
)
from xpra.util.system import SIGNAMES
from xpra.util.str_fn import nicestr, csv
from xpra.util.io import is_writable, stderr_print
from xpra.util.env import unsetenv, envbool, envint, osexpand, get_saved_env, get_saved_env_var, source_env, \
    OSEnvContext
from xpra.util.child_reaper import get_child_reaper
from xpra.platform.dotxpra import DotXpra

DESKTOP_GREETER = envbool("XPRA_DESKTOP_GREETER", True)
SHARED_XAUTHORITY = envbool("XPRA_SHARED_XAUTHORITY", True)
PROGRESS_TO_STDERR = envbool("XPRA_PROGRESS_TO_STDERR", False)
SYSTEM_DBUS_SOCKET = "/run/dbus/system_bus_socket"


def get_logger():
    from xpra.log import Logger
    return Logger("util")


def get_rand_chars(length=16, chars=b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ") -> bytes:
    import random
    return b"".join(chars[random.randint(0, len(chars) - 1):][:1] for _ in range(length))


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


def validate_pixel_depth(pixel_depth, desktop_or_monitor=False) -> int:
    try:
        pixel_depth = int(pixel_depth)
    except ValueError:
        raise InitException(f"invalid value {pixel_depth} for pixel depth, must be a number") from None
    if pixel_depth == 0:
        pixel_depth = 24
    if pixel_depth not in (8, 16, 24, 30):
        raise InitException(f"invalid pixel depth: {pixel_depth}")
    if not desktop_or_monitor and pixel_depth == 8:
        raise InitException("pixel depth 8 is only supported in 'desktop' mode")
    return pixel_depth


def display_name_check(display_name: str) -> None:
    """ displays a warning
        when a low display number is specified """
    if not display_name.startswith(":"):
        return
    n = display_name[1:].split(".")[0]  # ie: ":0.0" -> "0"
    try:
        dno = int(n)
    except (ValueError, TypeError):
        raise InitException(f"invalid display number {n}") from None
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
    log = get_logger()
    log.warn(f"Warning: xpra start from an existing {de!r} desktop session")
    log.warn(" without using dbus-launch,")
    log.warn(" notifications forwarding may not work")
    log.warn(" try using a clean environment, a dedicated user,")
    log.warn(" or disable xpra's notifications option")


def sanitize_env() -> None:
    # we don't want client apps to think these mean anything:
    # (if set, they belong to the desktop the server was started from)
    # TODO: simply whitelisting the env would be safer/better
    unsetenv("DESKTOP_SESSION",
             "GDMSESSION",
             "GNOME_DESKTOP_SESSION_ID",
             "SESSION_MANAGER",
             "XDG_VTNR",
             "XDG_MENU_PREFIX",
             "XDG_CURRENT_DESKTOP",
             "XDG_SESSION_DESKTOP",
             "XDG_SESSION_TYPE",
             "XDG_SESSION_ID",
             "XDG_SEAT",
             "XDG_VTNR",
             "QT_GRAPHICSSYSTEM_CHECKED",
             "CKCON_TTY",
             "CKCON_X11_DISPLAY",
             "CKCON_X11_DISPLAY_DEVICE",
             "WINDOWPATH",
             "VTE_VERSION",
             "LS_COLORS",
             )


def create_runtime_dir(xrd: str, uid: int, gid: int) -> str:
    if not POSIX or OSX or getuid() != 0:
        return ""
    # workarounds:
    # * some distros don't set a correct value,
    # * or they don't create the directory for us,
    # * or pam_open is going to create the directory but needs time to do so..
    if xrd and xrd.endswith("/user/0") and uid > 0:
        # don't keep root's directory, as this would not work:
        xrd = ""
    if not xrd:
        # find the "/run/user" directory:
        run_user = "/run/user"
        if not os.path.exists(run_user):
            run_user = "/var/run/user"
        if os.path.exists(run_user):
            xrd = os.path.join(run_user, str(uid))
    if not xrd:
        return ""
    if not os.path.exists(xrd):
        os.mkdir(xrd, 0o700)
        if POSIX:
            os.lchown(xrd, uid, gid)
    xpra_dir = os.path.join(xrd, "xpra")
    if not os.path.exists(xpra_dir):
        os.mkdir(xpra_dir, 0o700)
        if POSIX:
            os.lchown(xpra_dir, uid, gid)
    return xrd


def guess_xpra_display(socket_dir, socket_dirs) -> str:
    dotxpra = DotXpra(socket_dir, socket_dirs)
    results = dotxpra.sockets()
    live = [display for state, display in results if state == SocketState.LIVE]
    if not live:
        raise InitException("no existing xpra servers found")
    if len(live) > 1:
        raise InitException("too many existing xpra servers found, cannot guess which one to use")
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


def make_monitor_server():
    from xpra.x11.desktop.monitor_server import XpraMonitorServer
    return XpraMonitorServer()


def make_desktop_server():
    from xpra.x11.desktop.desktop_server import XpraDesktopServer
    return XpraDesktopServer()


def make_seamless_server(backend: str, clobber):
    if backend == "wayland":
        from xpra.wayland.server import WaylandSeamlessServer
        return WaylandSeamlessServer()
    from xpra.x11.server.seamless import SeamlessServer
    return SeamlessServer(clobber)


def make_shadow_server(display, attrs: dict[str, str]):
    from xpra.platform.shadow_server import ShadowServer
    return ShadowServer(display, attrs)


def make_proxy_server():
    from xpra.platform.proxy_server import ProxyServer
    return ProxyServer()


def make_expand_server(attrs: dict[str, str]):
    from xpra.x11.server.expand import ExpandServer
    return ExpandServer(attrs)


def make_encoder_server():
    from xpra.server.encoder.server import EncoderServer
    return EncoderServer()


def make_runner_server():
    with OSEnvContext():
        # unit test env var would inject SignalEmitter class twice:
        os.environ.pop("XPRA_UNIT_TEST", None)
        from xpra.server.runner.server import RunnerServer
        return RunnerServer()


def make_server_app(mode_attrs: dict[str, str], opts, clobber: int, mode: str,
                    display_name: str):
    if "backend" not in mode_attrs:
        mode_attrs["backend"] = opts.backend
    if mode.startswith("shadow"):
        # "shadow" -> multi-window=True, "shadow-screen" -> multi-window=False
        mode_attrs["multi-window"] = str(mode == "shadow")
        return make_shadow_server(display_name, mode_attrs)
    if mode == "proxy":
        return make_proxy_server()
    if mode == "expand":
        return make_expand_server(mode_attrs)
    if mode == "encoder":
        return make_encoder_server()
    if mode == "runner":
        return make_runner_server()
    if mode in ("seamless", "upgrade"):
        return make_seamless_server(opts.backend, clobber)
    if mode == "desktop":
        return make_desktop_server()
    assert mode == "monitor"
    return make_monitor_server()


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


SERVER_SAVE_SKIP_OPTIONS: Sequence[str] = (
    "systemd-run",
    "daemon",
)

SERVER_LOAD_SKIP_OPTIONS: Sequence[str] = (
    "systemd-run",
    "daemon",
    "start",
    "start-child",
    "start-after-connect",
    "start-child-after-connect",
    "start-on-connect",
    "start-child-on-connect",
    "start-on-disconnect",
    "start-child-on-disconnect",
    "start-on-last-client-exit",
    "start-child-on-last-client-exit",
)


def get_options_file_contents(opts, mode: str = "seamless") -> str:
    defaults = make_defaults_struct()
    fixup_defaults(defaults)
    fixup_options(defaults)
    diff_contents = [
        f"# xpra server {__version__}",
        "",
        f"mode={mode}",
    ]
    for attr, dtype in OPTION_TYPES.items():
        if attr in CLIENT_ONLY_OPTIONS:
            continue
        if attr in SERVER_SAVE_SKIP_OPTIONS:
            continue
        aname = attr.replace("-", "_")
        dval = getattr(defaults, aname, None)
        cval = getattr(opts, aname, None)
        if dval != cval:
            if dtype is bool:
                BOOL_STR = {True: "yes", False: "no"}
                diff_contents.append(f"{attr}=" + BOOL_STR.get(cval, "auto"))
            elif dtype in (tuple, list):
                for x in cval or ():
                    diff_contents.append(f"{attr}={x}")
            else:
                diff_contents.append(f"{attr}={cval}")
    diff_contents.append("")
    return "\n".join(diff_contents)


def load_options() -> dict[str, Any]:
    config_file = session_file_path("config")
    return read_config(config_file)


def apply_config(opts, mode: str, cmdline: list[str]) -> str:
    # if we had saved the start / start-desktop config, reload it:
    options = load_options()
    if not options:
        return mode
    if mode.find("upgrade") >= 0:
        # unspecified upgrade, try to find the original mode used:
        mode = options.pop("mode") or mode
    upgrade_config = dict_to_validated_config(options)
    # apply the previous session options:
    for k in options:
        if k in CLIENT_ONLY_OPTIONS:
            continue
        if k in SERVER_LOAD_SKIP_OPTIONS:
            continue
        incmdline = f"--{k}" in cmdline or f"--no-{k}" in cmdline or any(c.startswith(f"--{k}=") for c in cmdline)
        if incmdline:
            continue
        dtype = OPTION_TYPES.get(k)
        if not dtype:
            continue
        fn = k.replace("-", "_")
        if not hasattr(upgrade_config, fn):
            warn(f"{k!r} not found in saved config")
            continue
        if not hasattr(opts, fn):
            warn(f"{k!r} not found in config")
            continue
        value = getattr(upgrade_config, fn)
        setattr(opts, fn, value)
    return mode


def is_splash_enabled(mode: str, daemon: bool, splash: bool, display: str) -> bool:
    if daemon:
        # daemon mode would have problems with the pipes
        return False
    if splash in (True, False):
        return splash
    # auto mode, figure out if we should show it:
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        # don't show the splash screen over SSH forwarding
        return False
    xdisplay = os.environ.get("DISPLAY", "")
    if xdisplay:
        # make sure that the display isn't the one we're running against,
        # unless we're shadowing it
        return xdisplay != display or mode.startswith("shadow")
    if mode in ("proxy", "encoder", "runner"):
        return False
    if os.environ.get("XDG_SESSION_DESKTOP"):
        return True
    if not POSIX:
        return True
    return False


MODE_TO_NAME: dict[str, str] = {
    "seamless": "Seamless",
    "desktop": "Desktop",
    "monitor": "Monitor",
    "expand": "Expand",
    "upgrade": "Upgrade",
    "upgrade-seamless": "Seamless Upgrade",
    "upgrade-desktop": "Desktop Upgrade",
    "upgrade-monitor": "Monitor Upgrade",
    "shadow": "Shadow",
    "shadow-screen": "Shadow Screen",
    "proxy": "Proxy",
}


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


def get_splash_progress(mode: str, daemon: bool, splash: bool, display: str) -> tuple[Popen | None, Callable]:
    # this should be moved to the SplashServer class,
    # once we initialize servers earlier
    progress: Callable[[int, str], None] = noop
    splash_process = None
    use_stderr = PROGRESS_TO_STDERR
    if is_splash_enabled(mode, daemon, splash, display):
        # use splash screen to show server startup progress:
        mode_str = MODE_TO_NAME.get(mode, "").split(" Upgrade")[0]
        title = f"Xpra {mode_str} Server {__version__}"
        splash_process = make_progress_process(title)
        if splash_process:
            progress = splash_process.progress
            from atexit import register

            def progress_exit() -> None:
                progress(100, "exiting")
            register(progress_exit)
        else:
            use_stderr = True
    if progress == noop and use_stderr:
        def progress_to_stderr(*args) -> None:
            stderr_print(" ".join(str(x) for x in args))

        progress = progress_to_stderr
    progress(10, "initializing environment")
    return splash_process, progress


def setup_session_dir(mode: str, sessions_dir: str, display_name: str, uid: int, gid: int) -> str:
    session_dir = make_session_dir(mode, sessions_dir, display_name, uid, gid)
    os.environ["XPRA_SESSION_DIR"] = session_dir
    return session_dir


def write_initial_session_files(uid: int, gid: int, run_xpra_script: str,
                                env_script: str, cmdline: Sequence[str]) -> None:
    if run_xpra_script:
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        assert BACKWARDS_COMPATIBLE
        from xpra.server.runner_script import write_runner_shell_scripts
        write_runner_shell_scripts(run_xpra_script)
    if env_script:
        save_session_file("server.env", env_script, uid, gid)
    save_session_file("cmdline", "\n".join(cmdline) + "\n", uid, gid)


def get_server_log_dir(start_vfb: bool, log_to_file: bool, log_dir: str, session_dir: str) -> str:
    from xpra.server.subsystem.daemon import DaemonServer
    assert session_dir
    return DaemonServer.get_server_log_dir(start_vfb, log_to_file, log_dir)


def setup_xauthority(display_name: str, username: str, uid: int, gid: int,
                     shadowing: bool, write_session_file: Callable[[str, str], str], log) -> str:
    from xpra.x11.vfb_util import get_xauthority_path, valid_xauth
    root = POSIX and getuid() == 0
    xauthority = valid_xauth((load_session_file("xauthority")).decode(), uid, gid)
    if xauthority:
        os.environ["XAUTHORITY"] = xauthority
        return xauthority

    if SHARED_XAUTHORITY:
        # Re-using this value is not always safe, but users expect commands
        # such as `DISPLAY=:10 xterm` to work in most cases.
        xauthority = os.environ.get("XAUTHORITY", "")
    if shadowing and not valid_xauth(xauthority, uid, gid):
        # Look for xauth files in magic directories, see ticket #3917.
        xauth_time = 0.0
        candidates = (
            "/tmp/xauth*",
            "/tmp/.Xauth*",
            "/var/run/*dm/xauth*",
            "/var/run/lightdm/$USER/xauthority",
            "$XDG_RUNTIME_DIR/xauthority",
            "$XDG_RUNTIME_DIR/Xauthority",
            "$XDG_RUNTIME_DIR/gdm/xauthority",
            "$XDG_RUNTIME_DIR/gdm/Xauthority",
        )
        for globstr in candidates:
            for filename in glob.glob(osexpand(globstr, actual_username=username, uid=uid, gid=gid)):
                if not os.path.isfile(filename):
                    continue
                try:
                    stat_info = os.stat(filename)
                except OSError:
                    continue
                if not root and stat_info.st_uid != uid:
                    continue
                if xauth_time == 0.0 or stat_info.st_mtime > xauth_time:
                    xauthority = filename
                    xauth_time = stat_info.st_mtime
    if not valid_xauth(xauthority, uid, gid):
        xauthority = get_xauthority_path(display_name)
        xauthority = osexpand(xauthority, actual_username=username, uid=uid, gid=gid)
    assert xauthority
    if not os.path.exists(xauthority):
        if os.path.islink(xauthority):
            # broken symlink
            os.unlink(xauthority)
        log(f"creating XAUTHORITY file {xauthority!r}")
        with open(xauthority, "ab") as xauth_file:
            os.fchmod(xauth_file.fileno(), 0o640)
            if root and (uid != 0 or gid != 0):
                os.fchown(xauth_file.fileno(), uid, gid)
    elif not is_writable(xauthority, uid, gid) and not root:
        log(f"chmoding XAUTHORITY file {xauthority!r}")
        os.chmod(xauthority, 0o640)
    write_session_file("xauthority", xauthority)
    log(f"using XAUTHORITY file {xauthority!r}")
    os.environ["XAUTHORITY"] = xauthority
    return xauthority


@dataclass
class VFBStartResult:
    xvfb: Popen | None
    xvfb_pid: int
    devices: dict
    display_name: str
    xvfb_cmd: tuple[str, ...] = ()
    displayfd: int = 0


@dataclass
class X11DisplayResolution:
    start_vfb: bool
    xauth_data: str
    use_display: bool | None


@dataclass
class PamStartupResult:
    pam: Any
    protected_env: dict


@dataclass
class RuntimeDirResult:
    xrd: str
    protected_env: dict


@dataclass
class DisplayNameResult:
    display_name: str
    display_options: str = ""


def setup_pam_session(username: str, display_name: str, xauth_data: str, uid: int) -> PamStartupResult:
    # if pam is present, try to create a new session:
    pam = None
    root = POSIX and getuid() == 0
    pam_open = POSIX and envbool("XPRA_PAM_OPEN", root and uid != 0)
    if pam_open:
        try:
            from xpra.platform.pam import pam_session
        except ImportError as e:
            noerr(sys.stderr.write, "Error: failed to import pam module\n")
            noerr(sys.stderr.write, f" {e}\n")
            del e
        else:
            pam = pam_session(username)
    if pam:
        env = {
            # "XDG_SEAT"               : "seat1",
            # "XDG_VTNR"               : "0",
            "XDG_SESSION_TYPE": "x11",
            # "XDG_SESSION_CLASS"      : "user",
            "XDG_SESSION_DESKTOP": "xpra",
        }
        # maybe we should just bail out instead?
        if pam.start():
            pam.set_env(env)
            items = {}
            if display_name.startswith(":"):
                items["XDISPLAY"] = display_name
            if xauth_data:
                items["XAUTHDATA"] = xauth_data
            pam.set_items(items)
            if pam.open():
                # we can't close it, because we're not going to be root anymore,
                # but since we're the process leader for the session,
                # terminating will also close the session
                # atexit.register(pam.close)
                protected_env = pam.get_envlist()
                os.environ.update(protected_env)
                return PamStartupResult(pam, protected_env)
    return PamStartupResult(pam, {})


def setup_runtime_dir(opts_env: Sequence[str], uid: int, gid: int, protected_env: dict) -> RuntimeDirResult:
    # get XDG_RUNTIME_DIR from env options,
    # which may not have updated os.environ yet when running as root with "--uid="
    root = POSIX and getuid() == 0
    xrd = parse_env(opts_env).get("XDG_RUNTIME_DIR", "")
    if OSX and not xrd:
        xrd = osexpand("~/.xpra", uid=uid, gid=gid)
        os.environ["XDG_RUNTIME_DIR"] = xrd
    xrd = os.path.abspath(xrd) if xrd else ""
    if root and (uid > 0 or gid > 0):
        # we're going to chown the directory if we create it,
        # ensure this cannot be abused, only use "safe" paths:
        if xrd == f"/run/user/{uid}":
            pass  # OK!
        elif not any(True for x in ("/tmp", "/var/tmp") if xrd.startswith(x)):
            xrd = ""
        # these paths could cause problems if we were to create and chown them:
        elif xrd.startswith(X11_SOCKET_DIR) or xrd.startswith("/tmp/.XIM-unix"):
            xrd = ""
    if not xrd:
        xrd = os.environ.get("XDG_RUNTIME_DIR", "")
    xrd = create_runtime_dir(xrd, uid, gid)
    if xrd:
        # this may override the value we get from pam
        # with the value supplied by the user:
        protected_env["XDG_RUNTIME_DIR"] = xrd
    return RuntimeDirResult(xrd, protected_env)


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
                                use_display: bool | None, error_cb: Callable) -> DisplayNameResult:
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
            error_cb(f"too many extra arguments ({len(extra_args)}): only expected a display number")
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
                    error_cb("you must specify a free virtual display name to use with the proxy server")
            elif use_display:
                # only use automatic guess for xpra displays and not X11 displays:
                display_name = guess_xpra_display(opts.socket_dir, opts.socket_dirs)
            else:
                # We will try to find one automatically
                # Use the temporary magic value "S" as marker:
                display_name = "S" + str(os.getpid())
    return DisplayNameResult(display_name, display_options)


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


def resolve_x11_display(display_name: str, xauthority: str, xauth_data: str,
                        start_vfb: bool, use_display: bool | None, upgrading: bool,
                        shadowing: bool, proxying: bool, encoder: bool, pam,
                        uid: int, gid: int, error_cb: Callable, progress: Callable, log) -> X11DisplayResolution:
    if (use_display is not None and not upgrading) or proxying or encoder:
        return X11DisplayResolution(start_vfb, xauth_data, use_display)

    # Figure out if we have to start the vfb or not.
    # Bail out if we need a display that is not running.
    if not display_name:
        if upgrading:
            error_cb("no displays found to upgrade")
        return X11DisplayResolution(start_vfb, xauth_data, False)

    progress(40, "connecting to the display")
    no_gtk()
    if verify_display(None, display_name, log_errors=False, timeout=1):
        progress(40, "connected to the display")
        return X11DisplayResolution(False, xauth_data, use_display)

    stat = {}
    if display_name.startswith(":"):
        x11_socket_path = os.path.join(X11_SOCKET_DIR, "X" + display_name[1:])
        stat = stat_display_socket(x11_socket_path)
        log(f"stat_display_socket({x11_socket_path})={stat}")
        if not stat and (upgrading or shadowing):
            error_cb(f"cannot access display {display_name!r}")
        # No X11 socket to connect to, so we have to start one.
        start_vfb = True
    if stat:
        # We can't connect to the X11 display, but we can still stat its socket.
        # Perhaps we need to re-add an xauth entry.
        if not xauth_data:
            xauth_data = get_hex_uuid()
            if pam:
                pam.set_items({"XAUTHDATA": xauth_data})
        from xpra.x11.vfb_util import xauth_add
        xauth_add(xauthority, display_name, xauth_data, uid, gid)
        if not verify_display(None, display_name, log_errors=False, timeout=1):
            warn(f"display {display_name!r} is not accessible")
        else:
            start_vfb = False
    return X11DisplayResolution(start_vfb, xauth_data, use_display)


def start_server_vfb(opts, mode: str, display_name: str, old_display_name: str, start_vfb: bool,
                     xvfb_cmd: Sequence[str], xauth_data: str, xauthority: str | None,
                     cwd: str, uid: int, gid: int, username: str, protected_env: dict,
                     pam, shadowing: bool, proxying: bool, encoder: bool,
                     runner: bool, starting: str, write_session_file: Callable,
                     progress: Callable, log) -> VFBStartResult:
    xvfb = None
    xvfb_pid = 0
    devices = {}
    displayfd = 0
    if POSIX and getattr(opts, "displayfd", None):
        try:
            displayfd = int(opts.displayfd)
        except ValueError as e:
            noerr(sys.stderr.write, f"Error: invalid displayfd {opts.displayfd!r}:\n")
            noerr(sys.stderr.write, f" {e}\n")
            del e
    result_cmd = tuple(xvfb_cmd)
    if not POSIX or proxying or encoder or runner:
        return VFBStartResult(xvfb, xvfb_pid, devices, display_name, result_cmd, displayfd)

    create_input_devices = noop
    uinput_uuid_len = 0
    use_uinput = False
    if opts.backend != "wayland":
        try:
            from xpra.x11.uinput.setup import has_uinput, create_input_devices, UINPUT_UUID_LEN
            uinput_uuid_len = UINPUT_UUID_LEN
            use_uinput = not (shadowing or proxying or encoder or runner) and opts.input_devices.lower() in (
                "uinput", "auto",
            ) and has_uinput()
        except ImportError:
            use_uinput = False

    uinput_uuid = ""
    if start_vfb:
        progress(40, "starting a virtual display")
        from xpra.x11.vfb_util import start_Xvfb, xauth_add
        assert not proxying and xauth_data
        pixel_depth = validate_pixel_depth(opts.pixel_depth, starting in ("desktop", "monitor"))
        if use_uinput:
            # This only needs to be fairly unique.
            uinput_uuid = get_rand_chars(uinput_uuid_len).decode("latin1")
            write_session_file("uinput-uuid", uinput_uuid)
        vfb_geom: tuple | None = ()
        resize = opts.resize_display.lower()
        if resize not in ALL_BOOLEAN_OPTIONS and resize != "auto":
            sizes = opts.resize_display.split(":", 1)[-1]
            resolutions = parse_resolutions(sizes, opts.refresh_rate)
            if resolutions:
                vfb_geom = resolutions[0]
        fps = get_refresh_rate_for_value(opts.refresh_rate, 60) if opts.refresh_rate else 0
        xvfb, display_name = start_Xvfb(result_cmd, vfb_geom, pixel_depth, fps, display_name, cwd,
                                        uid, gid, username, uinput_uuid)
        assert xauthority
        xauth_add(xauthority, display_name, xauth_data, uid, gid)
        xvfb_pid = xvfb.pid
        xvfb_pidfile = write_session_file("xvfb.pid", str(xvfb.pid))
        log(f"saved xvfb.pid={xvfb.pid}")

        def xvfb_terminated() -> None:
            log(f"xvfb_terminated() removing {xvfb_pidfile}")
            if xvfb_pidfile:
                os.unlink(xvfb_pidfile)

        vfb_procinfo = get_child_reaper().add_process(xvfb, "xvfb", xvfb_cmd, ignore=True, callback=xvfb_terminated)
        log("xvfb process info=%s", vfb_procinfo.get_info())
        os.environ["DISPLAY"] = display_name
        os.environ["CKCON_X11_DISPLAY"] = display_name
        os.environ.update(protected_env)
        if display_name != old_display_name:
            if pam:
                pam.set_items({"XDISPLAY": display_name})
    elif not OSX and not shadowing and not proxying:
        try:
            xvfb_pid = int(load_session_file("xvfb.pid") or 0)
        except ValueError:
            pass
        log(f"reloaded xvfb.pid={xvfb_pid} from session file")
        if use_uinput:
            uinput_uuid = load_session_file("uinput-uuid").decode("latin1")
    if uinput_uuid:
        devices = create_input_devices(uinput_uuid, uid) or {}
    return VFBStartResult(xvfb, xvfb_pid, devices, display_name, result_cmd, displayfd)


def update_session_dir_for_display(mode: str, sessions_dir: str, log_dir_option: str,
                                   old_display_name: str, display_name: str,
                                   session_dir: str, log_dir: str, uid: int, log) -> tuple[str, str]:
    if display_name == old_display_name or not session_dir:
        return session_dir, log_dir
    new_session_dir = get_session_dir(mode, sessions_dir, display_name, uid)
    if new_session_dir == session_dir:
        return session_dir, log_dir
    try:
        if os.path.exists(new_session_dir):
            for sess_e in os.listdir(session_dir):
                os.rename(os.path.join(session_dir, sess_e), os.path.join(new_session_dir, sess_e))
            os.rmdir(session_dir)
        else:
            os.rename(session_dir, new_session_dir)
    except OSError as e:
        log.error("Error moving the session directory")
        log.error(f" from {session_dir!r} to {new_session_dir!r}")
        log.error(f" {e}")
    if not log_dir_option or log_dir_option.lower() == "auto":
        log_dir = new_session_dir
    os.environ["XPRA_SESSION_DIR"] = new_session_dir
    return new_session_dir, log_dir


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


def do_run_server(script_file: str, cmdline: list[str], error_cb: Callable, opts,
                  extra_args: list[str], full_mode: str, defaults) -> ExitValue:
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
    run_xpra_script = env_script = ""
    if POSIX and getuid() != 0 and BACKWARDS_COMPATIBLE:
        from xpra.server.runner_script import xpra_runner_shell_script, xpra_env_shell_script
        save_env = os.environ.copy()
        save_env.update(parse_env(opts.env))
        env_script = xpra_env_shell_script(opts.socket_dir, save_env)
        run_xpra_script = env_script + xpra_runner_shell_script(script_file, cwd)

    validate_encryption(opts)
    if opts.encoding == "help" or "help" in opts.encodings:
        return show_encoding_help(opts)
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
    display_result = resolve_server_display_name(opts, extra_args, desktop_display,
                                                 shadowing, expanding, runner, upgrading,
                                                 proxying, encoder, use_display, error_cb)
    display_name = display_result.display_name
    display_options = display_result.display_options

    splash_process, progress = get_splash_progress(mode, opts.daemon, opts.splash, display_name)

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

    uid: int = int(opts.uid)
    gid: int = int(opts.gid)
    username = get_username_for_uid(uid)
    if POSIX and uid and not gid:
        gid = find_group(uid)
    protected_env = {}

    if str_to_bool(opts.dbus):
        start_dbus()
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = f"unix:path={SYSTEM_DBUS_SOCKET}"
        protected_env["DBUS_SYSTEM_BUS_ADDRESS"] = f"unix:path={SYSTEM_DBUS_SOCKET}"

    if str_to_bool(opts.printing):
        start_cupsd()

    def write_session_file(filename: str, contents) -> str:
        return save_session_file(filename, contents, uid, gid)

    # Daemonize:
    if POSIX and opts.daemon:
        from xpra.util.daemon import daemonize
        daemonize()

    clobber = int(upgrading) * CLOBBER_UPGRADE | int(use_display or 0) * CLOBBER_USE_DISPLAY
    start_vfb: bool = not (shadowing or proxying or clobber or expanding or encoder or runner) and opts.xvfb.lower() not in FALSE_OPTIONS and opts.backend != "wayland"
    xauth_data: str = get_hex_uuid() if start_vfb else ""

    pam_result = setup_pam_session(username, display_name, xauth_data, uid)
    pam = pam_result.pam
    if pam_result.protected_env:
        protected_env = pam_result.protected_env

    runtime_dir_result = setup_runtime_dir(opts.env, uid, gid, protected_env)
    xrd = runtime_dir_result.xrd
    protected_env = runtime_dir_result.protected_env

    xvfb_cmd: list[str] = []
    if start_vfb:
        xvfb_cmd = xvfb_command(opts.xvfb, opts.pixel_depth, opts.dpi)

    sanitize_env()
    if not shadowing:
        os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.update(source_env(opts.source))
    if POSIX:
        if xrd:
            os.environ["XDG_RUNTIME_DIR"] = xrd
        if not OSX:
            os.environ["XDG_SESSION_TYPE"] = "x11"
        if starting != "desktop":
            os.environ["XDG_CURRENT_DESKTOP"] = opts.wm_name
    if display_name[0] != "S":
        os.environ["DISPLAY"] = display_name
        if POSIX:
            os.environ["CKCON_X11_DISPLAY"] = display_name
    elif not start_vfb or xvfb_cmd[0].find("Xephyr") < 0:
        os.environ.pop("DISPLAY", None)
    os.environ.update(protected_env)

    session_dir = setup_session_dir(mode, opts.sessions_dir, display_name, uid, gid)
    if upgrading:
        # if we had saved the start / start-desktop config, reload it:
        mode = apply_config(opts, mode, cmdline)
        if mode.startswith("upgrade-"):
            mode = mode.removeprefix("upgrade-")
        if mode.startswith("start-"):
            mode = mode.removeprefix("start-")

    write_initial_session_files(uid, gid, run_xpra_script, env_script, cmdline)
    write_session_file("config", get_options_file_contents(opts, mode))

    # warn early about this:
    if starting in ("seamless", "desktop") and desktop_display and opts.notifications and not opts.dbus_launch:
        print_DE_warnings()
    add_desktop_greeter(opts, starting, use_display)
    # make sure we don't start ibus in these modes:
    if POSIX and not OSX and (upgrading or shadowing):
        opts.input_method = "keep"

    if start_vfb and opts.sync_xvfb is None and any(xvfb_cmd[0].find(x) >= 0 for x in ("Xephyr", "Xnest")):
        # automatically enable sync-xvfb for Xephyr and Xnest:
        opts.sync_xvfb = 50

    if not (shadowing or starting == "desktop" or (upgrading and mode in ("desktop", "monitor"))):
        opts.rfb_upgrade = 0
        if opts.bind_rfb:
            get_logger().warn(f"Warning: bind-rfb sockets cannot be used with {mode!r} mode")
            opts.bind_rfb = []
        if opts.bind_rdp:
            get_logger().warn(f"Warning: bind-rdp sockets cannot be used with {mode!r} mode")
            opts.bind_rdp = []

    from xpra.server.features import set_server_features
    set_server_features(opts, mode)

    progress(30, "initializing server")
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

    stdout = sys.stdout
    stderr = sys.stderr
    daemon = app.get_subsystem("daemon")
    log_to_file = opts.daemon or envbool("XPRA_LOG_TO_FILE")
    if daemon:
        extra_expand = {"TIMESTAMP": datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}
        log_dir = daemon.setup_log(start_vfb, log_to_file, display_name, extra_expand, stdout, stderr)
    else:
        log_dir = get_server_log_dir(start_vfb, log_to_file, opts.log_dir or "", session_dir)
    log("env=%s", os.environ)

    progress(30, "creating network sockets")
    app.parse_socket_options(opts)
    app.init_sockets(retry=10 * int(upgrading))

    # Start the Xvfb server first to get the display_name if needed
    odisplay_name = display_name
    xauthority = None
    if POSIX and (start_vfb or clobber or (shadowing and display_name.startswith(":"))) and display_name.find("wayland") < 0:
        xauthority = setup_xauthority(display_name, username, uid, gid, shadowing, write_session_file, log)
        display_resolution = resolve_x11_display(display_name, xauthority, xauth_data, start_vfb, use_display,
                                                 upgrading, shadowing, proxying, encoder, pam, uid, gid,
                                                 error_cb, progress, log)
        start_vfb = display_resolution.start_vfb
        xauth_data = display_resolution.xauth_data
        use_display = display_resolution.use_display

    vfb_result = start_server_vfb(opts, mode, display_name, odisplay_name, start_vfb, xvfb_cmd,
                                  xauth_data, xauthority, cwd, uid, gid, username, protected_env,
                                  pam, shadowing, proxying, encoder, runner, starting,
                                  write_session_file, progress, log)
    display_name = vfb_result.display_name
    session_dir, log_dir = update_session_dir_for_display(mode, opts.sessions_dir, opts.log_dir or "",
                                                          odisplay_name, display_name,
                                                          session_dir, log_dir, uid, log)
    if daemon:
        daemon.update_log_dir(log_dir)
        daemon.display_name_changed(display_name)
    # we should not be using stdout or stderr from this point on:
    del stdout
    del stderr

    app.protected_env = protected_env
    # do this one early - because we want to change uid as early as possible:
    from xpra.server.subsystem.process import ProcessServer
    process = app.add_subsystem(ProcessServer)
    process.init(opts)
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
        if splash := app.get_subsystem("splash"):
            splash.splash_process = splash_process
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
