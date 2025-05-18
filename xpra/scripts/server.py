# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=import-outside-toplevel

# DO NOT IMPORT GTK HERE: see
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000041.html
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000042.html
# (also do not import anything that imports gtk)
import sys
import glob
import shlex
import os.path
import datetime
from typing import Any, NoReturn
from subprocess import Popen  # pylint: disable=import-outside-toplevel
from collections.abc import Sequence

from xpra import __version__
from xpra.scripts.session import get_session_dir, make_session_dir, session_file_path, load_session_file, \
    save_session_file
from xpra.util.io import info, warn
from xpra.util.parsing import parse_str_dict
from xpra.scripts.parsing import fixup_defaults, MODE_ALIAS
from xpra.scripts.main import (
    no_gtk, bypass_no_gtk, nox,
    validate_encryption, parse_env, configure_env,
    stat_display_socket, get_xpra_sessions,
    make_progress_process,
    load_pid,
    X11_SOCKET_DIR,
    may_block_numpy,
)
from xpra.scripts.config import (
    InitException, InitInfo, InitExit,
    FALSE_OPTIONS, ALL_BOOLEAN_OPTIONS, OPTION_TYPES, CLIENT_ONLY_OPTIONS, CLIENT_OPTIONS,
    parse_bool_or,
    fixup_options, make_defaults_struct, read_config, dict_to_validated_config,
    xvfb_command,
)
from xpra.common import (
    CLOBBER_USE_DISPLAY, CLOBBER_UPGRADE, SSH_AGENT_DISPATCH,
    ConnectionMessage, SocketState, noerr,
)
from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import (
    POSIX, WIN32, OSX,
    force_quit,
    get_username_for_uid, get_home_for_uid, get_shell_for_uid, getuid, get_groups, get_group_id,
    get_hex_uuid, gi_import,
)
from xpra.server.util import setuidgid
from xpra.util.system import SIGNAMES
from xpra.util.str_fn import nicestr
from xpra.util.io import is_writable, stderr_print, which
from xpra.util.env import unsetenv, envbool, osexpand, get_saved_env, get_saved_env_var
from xpra.common import GROUP
from xpra.util.child_reaper import getChildReaper
from xpra.platform.dotxpra import DotXpra

DESKTOP_GREETER = envbool("XPRA_DESKTOP_GREETER", True)
IBUS_DAEMON_COMMAND = os.environ.get("XPRA_IBUS_DAEMON_COMMAND",
                                     "ibus-daemon --xim --verbose --replace --panel=disable --desktop=xpra --daemonize")
SHARED_XAUTHORITY = envbool("XPRA_SHARED_XAUTHORITY", True)
PROGRESS_TO_STDERR = envbool("XPRA_PROGRESS_TO_STDERR", False)


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


def validate_pixel_depth(pixel_depth, starting_desktop=False) -> int:
    try:
        pixel_depth = int(pixel_depth)
    except ValueError:
        raise InitException(f"invalid value {pixel_depth} for pixel depth, must be a number") from None
    if pixel_depth == 0:
        pixel_depth = 24
    if pixel_depth not in (8, 16, 24, 30):
        raise InitException(f"invalid pixel depth: {pixel_depth}")
    if not starting_desktop and pixel_depth == 8:
        raise InitException("pixel depth 8 is only supported in 'start-desktop' mode")
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
    de = os.environ.get("XDG_SESSION_DESKTOP") or os.environ.get("SESSION_DESKTOP")
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
             )


def configure_imsettings_env(input_method) -> str:
    im = (input_method or "").lower()
    if im == "auto":
        ibus_daemon = which("ibus-daemon")
        if ibus_daemon:
            im = "ibus"
        else:
            im = "none"
    if im in ("none", "no"):
        # the default: set DISABLE_IMSETTINGS=1, fallback to xim
        # that's because the 'ibus' 'immodule' breaks keyboard handling
        # unless its daemon is also running - and we don't know if it is..
        imsettings_env(True, "xim", "xim", "xim", "none", "@im=none")
    elif im == "keep":
        # do nothing and keep whatever is already set, hoping for the best
        pass
    elif im in ("xim", "ibus", "scim", "uim"):
        # ie: (False, "ibus", "ibus", "IBus", "@im=ibus")
        imsettings_env(True, im.lower(), im.lower(), im.lower(), im, "@im=" + im.lower())
    else:
        v = imsettings_env(True, im.lower(), im.lower(), im.lower(), im, "@im=" + im.lower())
        warn(f"using input method settings: {v}")
        warn(f"unknown input method specified: {input_method}")
        warn(" if it is correct, you may want to file a bug to get it recognized")
    return im


def imsettings_env(disabled, gtk_im_module, qt_im_module, clutter_im_module,
                   imsettings_module, xmodifiers) -> dict[str, str]:
    # for more information, see imsettings:
    # https://code.google.com/p/imsettings/source/browse/trunk/README
    if disabled is True:
        os.environ["DISABLE_IMSETTINGS"] = "1"  # this should override any XSETTINGS too
    elif disabled is False and ("DISABLE_IMSETTINGS" in os.environ):
        del os.environ["DISABLE_IMSETTINGS"]
    v = {
        "GTK_IM_MODULE": gtk_im_module,  # or "gtk-im-context-simple"?
        "QT_IM_MODULE": qt_im_module,  # or "simple"?
        "QT4_IM_MODULE": qt_im_module,
        "CLUTTER_IM_MODULE": clutter_im_module,
        "IMSETTINGS_MODULE": imsettings_module,  # or "xim"?
        "XMODIFIERS": xmodifiers,
        # not really sure what to do with those:
        # "IMSETTINGS_DISABLE_DESKTOP_CHECK"    : "true",
        # "IMSETTINGS_INTEGRATE_DESKTOP"        : "no"           #we're not a real desktop
    }
    os.environ.update(v)
    return v


def create_runtime_dir(xrd, uid, gid) -> str:
    if not POSIX or OSX or getuid() != 0 or (uid == 0 and gid == 0):
        return ""
    # workarounds:
    # * some distros don't set a correct value,
    # * or they don't create the directory for us,
    # * or pam_open is going to create the directory but needs time to do so..
    if xrd and xrd.endswith("/user/0"):
        # don't keep root's directory, as this would not work:
        xrd = None
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
    sf.audio = sf.av_sync = sf.clipboard = sf.commands = sf.control = sf.dbus = sf.fileprint = sf.input_devices = False
    sf.mmap = sf.logging = sf.network_state = sf.notifications = sf.rfb = sf.shell = sf.webcam = False
    from xpra.server.base import ServerBase
    sb = ServerBase()
    sb.init(opts)
    from xpra.codecs.constants import PREFERRED_ENCODING_ORDER, HELP_ORDER
    if "help" in opts.encodings:
        sb.allowed_encodings = PREFERRED_ENCODING_ORDER
    from xpra.server.mixins.encoding import EncodingServer
    assert isinstance(sb, EncodingServer)
    EncodingServer.threaded_setup(sb)
    EncodingServer.setup(sb)
    from xpra.codecs.loader import encoding_help
    for e in (x for x in HELP_ORDER if x in sb.encodings):
        print(" * " + encoding_help(e))
    return 0


def set_server_features(opts, mode: str) -> None:
    def b(v) -> bool:
        return str(v).lower() not in FALSE_OPTIONS

    impwarned: set[str] = set()
    from importlib.util import find_spec

    def impcheck(*modules) -> bool:
        for mod in modules:
            if find_spec(f"xpra.{mod}"):
                continue
            if mod not in impwarned:
                impwarned.add(mod)
                log = get_logger()
                log(f"impcheck{modules}", exc_info=True)
                log.warn(f"Warning: missing {mod!r} module")
                log.warn(f" for Python {sys.version}")
            return False
        return True

    # turn off some server mixins:
    from xpra.server import features
    if mode == "encoder":
        # turn off all relevant features:
        opts.start_new_commands = False
        features.commands = False
        features.notifications = features.webcam = features.clipboard = False
        features.gstreamer = features.x11 = features.audio = features.av_sync = False
        features.fileprint = features.input_devices = features.commands = False
        features.logging = features.display = features.windows = False
        features.cursors = features.rfb = False
        features.ssh = False
    else:
        features.commands = opts.commands
        features.notifications = opts.notifications and impcheck("notifications")
        features.webcam = b(opts.webcam) and impcheck("codecs")
        features.clipboard = b(opts.clipboard) and impcheck("clipboard")
        features.gstreamer = b(opts.gstreamer) and impcheck("gstreamer")
        features.x11 = b(opts.x11) and impcheck("x11")
        features.audio = features.gstreamer and b(opts.audio) and impcheck("audio")
        features.av_sync = features.audio and b(opts.av_sync)
        features.fileprint = b(opts.printing) or b(opts.file_transfer)
        features.input_devices = not opts.readonly and impcheck("keyboard")
        features.logging = b(opts.remote_logging)
        features.display = opts.windows
        features.windows = features.display and impcheck("codecs")
        features.cursors = features.display and opts.cursors
        features.rfb = b(opts.rfb_upgrade) and impcheck("server.rfb")
        features.ssh = b(opts.ssh) and impcheck("net.ssh")

    features.http = opts.http and impcheck("net.http")
    features.control = opts.control and impcheck("net.control")
    features.mmap = b(opts.mmap) and impcheck("net.mmap")
    features.ssl = b(opts.ssl)
    features.dbus = b(opts.dbus) and impcheck("dbus", "server.dbus")
    features.encoding = impcheck("codecs")
    # features.network_state   = ??
    features.shell = opts.shell


def enforce_server_features() -> None:
    """
    Prevent the modules from being imported later
    """
    from xpra.util.pysystem import enforce_features
    from xpra.server import features
    enforce_features(features, {
        "control": "xpra.net.control,xpra.server.mixins.controlcommands",
        "commands": "xpra.server.mixins.child_command",
        "notifications": "xpra.notifications,xpra.server.mixins.notification,xpra.server.source.notification",
        "webcam": "xpra.server.mixins.webcam,xpra.server.source.webcam",
        "clipboard": "xpra.clipboard,xpra.server.mixins.clipboard,xpra.server.source.clipboard",
        "audio": "xpra.audio,xpra.server.mixins.audio,xpra.server.source.audio",
        # "av_sync": "??",
        "fileprint": "xpra.server.mixins.fileprint,xpra.server.source.fileprint",
        "mmap": "xpra.net.mmap,xpra.server.mixins.mmap,xpra.server.source.mmap",
        "ssl": "ssl,xpra.net.ssl_util",
        "ssh": "paramiko,xpra.net.ssh,xpra.server.mixins.ssh_agent",
        "input_devices": "xpra.server.mixins.input,xpra.server.source.input",
        "gstreamer": "gi.repository.Gst,xpra.gstreamer,xpra.codecs.gstreamer",
        "x11": "xpra.x11,gi.repository.GdkX11",
        "dbus": "xpra.dbus,xpra.server.dbus,xpra.server.source.dbus",
        "encoding": "xpra.server.mixins.encoding,xpra.server.source.encodings",
        "logging": "xpra.server.mixins.logging",
        "network_state": "xpra.server.mixins.networkstate,xpra.server.source.networkstate",
        "shell": "xpra.server.mixins.shell,xpra.server.source.shell",
        "display": "xpra.server.mixins.display,xpra.server.source.display",
        "windows": "xpra.server.mixins.window,xpra.server.source.windows",
        "cursors": "xpra.server.mixins.cursors,xpra.server.source.cursors",
        "rfb": "xpra.net.rfb,xpra.server.rfb",
        "http": "xpra.net.http,xpra.server.mixins.http",
    })
    may_block_numpy()


def make_monitor_server():
    from xpra.x11.desktop.monitor_server import XpraMonitorServer
    return XpraMonitorServer()


def make_desktop_server():
    from xpra.x11.desktop.desktop_server import XpraDesktopServer
    return XpraDesktopServer()


def make_seamless_server(clobber):
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


def verify_display(xvfb=None, display_name=None, shadowing=False, log_errors=True, timeout=None) -> bool:
    # check that we can access the X11 display:
    from xpra.log import Logger
    log = Logger("screen", "x11")
    if xvfb:
        from xpra.x11.vfb_util import verify_display_ready, VFB_WAIT
        if timeout is None:
            timeout = VFB_WAIT
        if not verify_display_ready(xvfb, display_name, shadowing, log_errors, timeout):
            return False
        log(f"X11 display {display_name!r} is ready")
    no_gtk()
    # we're going to load gtk:
    bypass_no_gtk()
    display = verify_gdk_display(display_name)
    if not display:
        return False
    log(f"GDK can access the display {display_name!r}")
    return True


def write_displayfd(display_name: str, fd: int) -> None:
    if OSX or not POSIX or fd <= 0:
        return
    from xpra.log import Logger
    log = Logger("server")
    try:
        from xpra.platform import displayfd
        display_no = display_name[1:]
        # ensure it is a string containing the number:
        display_no = str(int(display_no))
        log(f"writing display_no={display_no} to displayfd={fd}")
        assert displayfd.write_displayfd(fd, display_no), "timeout"
    except Exception as e:
        log.error("write_displayfd failed", exc_info=True)
        log.error(f"Error: failed to write {display_name} to fd={fd}")
        log.estr(e)


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


def apply_config(opts, mode: str, cmdline: str) -> str:
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


def reload_dbus_attributes(display_name: str) -> tuple[int, dict[str, str]]:
    from xpra.log import Logger
    dbuslog = Logger("dbus")
    session_dir = os.environ.get("XPRA_SESSION_DIR", "")
    dbus_pid = load_pid(session_dir, "dbus.pid")
    try:
        dbus_env_data = load_session_file("dbus.env").decode("utf8")
        dbuslog(f"reload_dbus_attributes({display_name}) dbus_env_data={dbus_env_data}")
    except UnicodeDecodeError:
        dbuslog.error("Error decoding dbus.env file", exc_info=True)
        dbus_env_data = ""
    dbus_env = {}
    if dbus_env_data:
        for line in dbus_env_data.splitlines():
            if not line or line.startswith("#") or line.find("=") < 0:
                continue
            parts = line.split("=", 1)
            dbus_env[parts[0]] = parts[1]
    dbuslog(f"reload_dbus_attributes({display_name}) dbus_env={dbus_env}")
    dbus_address = dbus_env.get("DBUS_SESSION_BUS_ADDRESS")
    if not (dbus_pid and dbus_address):
        # less reliable: get it from the wminfo output:
        from xpra.scripts.main import exec_wminfo
        wminfo = exec_wminfo(display_name)
        if not dbus_pid:
            try:
                dbus_pid = int(wminfo.get("dbus-pid", 0))
            except ValueError:
                pass
        if not dbus_address:
            dbus_address = wminfo.get("dbus-address", "")
    if dbus_pid and os.path.exists("/proc") and not os.path.exists(f"/proc/{dbus_pid}"):
        dbuslog(f"dbus pid {dbus_pid} is no longer valid")
        dbus_pid = 0
    if dbus_pid:
        dbus_env["DBUS_SESSION_BUS_PID"] = str(dbus_pid)
    if dbus_address:
        dbus_env["DBUS_SESSION_BUS_ADDRESS"] = dbus_address
    if dbus_pid and dbus_address:
        dbuslog(f"retrieved dbus pid: {dbus_pid}, environment: {dbus_env}")
    return dbus_pid, dbus_env


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
    xdisplay = os.environ.get("DISPLAY")
    if xdisplay:
        # make sure that the display isn't the one we're running against,
        # unless we're shadowing it
        return xdisplay != display or mode.startswith("shadow")
    if mode in ("proxy", "encoder"):
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


def do_run_server(script_file: str, cmdline, error_cb, opts, extra_args, full_mode: str,
                  display_name: str, defaults) -> ExitValue:
    mode_parts = full_mode.split(",", 1)
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])
    assert mode in (
        "seamless", "desktop", "monitor", "expand", "shadow", "shadow-screen",
        "upgrade", "upgrade-seamless", "upgrade-desktop", "upgrade-monitor",
        "proxy",
        "encoder",
    )
    validate_encryption(opts)
    if opts.encoding == "help" or "help" in opts.encodings:
        return show_encoding_help(opts)
    ################################################################################
    # splash screen:
    splash_process: Popen | None = None
    if is_splash_enabled(mode, opts.daemon, opts.splash, display_name):
        # use splash screen to show server startup progress:
        mode_str = MODE_TO_NAME.get(mode, "").split(" Upgrade")[0]
        title = f"Xpra {mode_str} Server {__version__}"
        splash_process = make_progress_process(title)
        progress = splash_process.progress
    else:
        if PROGRESS_TO_STDERR:
            def progress_to_stderr(*args):
                stderr_print(" ".join(str(x) for x in args))

            progress = progress_to_stderr
        else:
            def noprogressshown(*_args):
                """ messages aren't shown """

            progress = noprogressshown
    progress(10, "initializing environment")
    try:
        return _do_run_server(script_file, cmdline,
                              error_cb, opts, extra_args, full_mode, display_name, defaults,
                              splash_process, progress)
    except Exception as e:
        progress(100, f"error: {e}")
        import time
        time.sleep(1)
        raise


def _do_run_server(script_file: str, cmdline,
                   error_cb, opts, extra_args, full_mode: str, display_name: str, defaults,
                   splash_process, progress) -> ExitValue:
    mode_parts = full_mode.split(",", 1)
    mode = MODE_ALIAS.get(mode_parts[0], mode_parts[0])
    mode_attrs: dict[str, str] = {}
    if len(mode_parts) > 1:
        mode_attrs = parse_str_dict(mode_parts[1])
    desktop_display = nox()
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = os.path.expanduser("~")
        warn(f"current working directory does not exist, using {cwd!r}\n")

    # remove anything pointing to dbus from the current env
    # (so we only detect a dbus instance started by pam,
    # and override everything else)
    for k in tuple(os.environ.keys()):
        if k.startswith("DBUS_"):
            del os.environ[k]

    starting = mode == "seamless"
    starting_desktop = mode == "desktop"
    starting_monitor = mode == "monitor"
    expanding = mode == "expand"
    upgrading = mode.startswith("upgrade")
    shadowing = mode.startswith("shadow")
    proxying = mode == "proxy"
    encoder = mode == "encoder"
    use_display = parse_bool_or("use-display", opts.use_display)
    if shadowing or expanding:
        use_display = True

    if not proxying and not shadowing and POSIX and not OSX:
        if not opts.x11:
            raise InitExit(ExitCode.UNSUPPORTED, f"{mode!r} requires x11")
        os.environ["GDK_BACKEND"] = "x11"

    has_child_arg = any((
        opts.start_child,
        opts.start_child_late,
        opts.start_child_on_connect,
        opts.start_child_after_connect,
        opts.start_child_on_last_client_exit,
    ))
    if proxying or upgrading:
        # when proxying or upgrading, don't exec any plain start commands:
        opts.start = []
        opts.start_child = []
        opts.start_late = []
        opts.start_child_late = []
    elif opts.exit_with_children:
        if not has_child_arg:
            msg = "exit-with-children was specified but start-child* is missing!"
            warn(msg)
            warn(" command line is: %r" % shlex.join(cmdline))
            raise InitException(msg)
    elif opts.start_child:
        warn("Warning: the 'start-child' option is used,")
        warn(" but 'exit-with-children' is not enabled,")
        warn(" you should just use 'start' instead")

    if (upgrading or shadowing) and opts.pulseaudio is None:
        # there should already be one running
        # so change None ('auto') to False
        opts.pulseaudio = False

    display_options = ""
    # get the display name:
    if (shadowing or expanding) and not extra_args:
        if WIN32 or OSX:
            # just a virtual name for the only display available:
            display_name = "Main"
        else:
            from xpra.scripts.main import guess_display
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
            if proxying or encoder:
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

    if upgrading:
        assert display_name, "no display found to upgrade"
        if POSIX and not OSX and get_saved_env_var("DISPLAY", "") == display_name:
            warn("Warning: upgrading from an environment connected to the same display")
        # try to stop the existing server if it exists:
        dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
        sessions = get_xpra_sessions(dotxpra, ignore_state=(SocketState.UNKNOWN, SocketState.DEAD),
                                     matching_display=display_name, query=True)
        session = sessions.get(display_name)
        if session:
            socket_path = session.get("socket-path")
            uri = f"socket://{socket_path}" if socket_path else display_name
            if request_exit(uri):
                # the server has terminated as we had requested
                use_display = True
                # but it may need a second to disconnect the clients
                # and then close the sockets cleanly
                # (so we can re-create them safely)
                import time
                time.sleep(1)
            else:
                warn(f"server for {display_name} is not exiting")

    if not (shadowing or proxying or upgrading or encoder) and opts.exit_with_children and not has_child_arg:
        error_cb("--exit-with-children specified without any children to spawn; exiting immediately")

    # Generate the script text now, because os.getcwd() will
    # change if/when we daemonize:
    from xpra.server.util import (
        xpra_env_shell_script,
        xpra_runner_shell_script,
        write_runner_shell_scripts,
        create_input_devices,
        source_env,
        daemonize,
        select_log_file, open_log_file, redirect_std_to_log,
    )
    run_xpra_script = None
    env_script = None
    if POSIX and getuid() != 0:
        save_env = os.environ.copy()
        save_env.update(parse_env(opts.env))
        env_script = xpra_env_shell_script(opts.socket_dir, save_env)
        run_xpra_script = env_script + xpra_runner_shell_script(script_file, cwd)

    uid: int = int(opts.uid)
    gid: int = int(opts.gid)
    username = get_username_for_uid(uid)
    home = get_home_for_uid(uid)
    ROOT: bool = POSIX and getuid() == 0
    if POSIX and uid and not gid:
        # try harder to use a valid group,
        # since we're going to chown files:
        username = get_username_for_uid(uid)
        groups = get_groups(username)
        if GROUP in groups:
            gid = get_group_id(GROUP)
        else:
            try:
                import pwd
                pw = pwd.getpwuid(uid)
                gid = pw.pw_gid
            except KeyError:
                if groups:
                    gid = get_group_id(groups[0])
                else:
                    gid = os.getgid()

    def write_session_file(filename: str, contents) -> str:
        return save_session_file(filename, contents, uid, gid)

    protected_env = {}
    stdout = sys.stdout
    stderr = sys.stderr
    # Daemonize:
    if POSIX and opts.daemon:
        # daemonize will chdir to "/", so try to use an absolute path:
        if opts.password_file:
            opts.password_file = tuple(os.path.abspath(x) for x in opts.password_file)
        daemonize()

    displayfd = 0
    if POSIX and opts.displayfd:
        try:
            displayfd = int(opts.displayfd)
        except ValueError as e:
            stderr.write(f"Error: invalid displayfd {opts.displayfd!r}:\n")
            stderr.write(f" {e}\n")
            del e

    clobber = int(upgrading) * CLOBBER_UPGRADE | int(use_display or 0) * CLOBBER_USE_DISPLAY
    start_vfb: bool = not (shadowing or proxying or clobber or expanding or encoder)
    xauth_data: str = get_hex_uuid() if start_vfb else ""

    # if pam is present, try to create a new session:
    pam = None
    PAM_OPEN = POSIX and envbool("XPRA_PAM_OPEN", ROOT and uid != 0)
    if PAM_OPEN:
        try:
            from xpra.platform.pam import pam_session
        except ImportError as e:
            stderr.write("Error: failed to import pam module\n")
            stderr.write(f" {e}\n")
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

    # get XDG_RUNTIME_DIR from env options,
    # which may not have updated os.environ yet when running as root with "--uid="
    xrd = parse_env(opts.env).get("XDG_RUNTIME_DIR", "")
    if OSX and not xrd:
        xrd = osexpand("~/.xpra", uid=uid, gid=gid)
        os.environ["XDG_RUNTIME_DIR"] = xrd
    xrd = os.path.abspath(xrd)
    if ROOT and (uid > 0 or gid > 0):
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
        if not starting_desktop:
            os.environ["XDG_CURRENT_DESKTOP"] = opts.wm_name
    if display_name[0] != "S":
        os.environ["DISPLAY"] = display_name
        if POSIX:
            os.environ["CKCON_X11_DISPLAY"] = display_name
    elif not start_vfb or xvfb_cmd[0].find("Xephyr") < 0:
        os.environ.pop("DISPLAY", None)
    os.environ.update(protected_env)

    session_dir = make_session_dir(mode, opts.sessions_dir, display_name, uid, gid)
    os.environ["XPRA_SESSION_DIR"] = session_dir
    # populate it:
    if run_xpra_script:
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        write_runner_shell_scripts(run_xpra_script)
    if env_script:
        write_session_file("server.env", env_script)
    write_session_file("cmdline", "\n".join(cmdline) + "\n")
    upgrading_seamless = upgrading_desktop = upgrading_monitor = False
    if upgrading:
        # if we had saved the start / start-desktop config, reload it:
        mode = apply_config(opts, mode, cmdline)
        if mode.startswith("upgrade-"):
            mode = mode[len("upgrade-"):]
        if mode.startswith("start-"):
            mode = mode[len("start-"):]
        upgrading_desktop = mode == "desktop"
        upgrading_monitor = mode == "monitor"
        upgrading_seamless = not (upgrading_desktop or upgrading_monitor)

    write_session_file("config", get_options_file_contents(opts, mode))

    extra_expand = {"TIMESTAMP": datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}
    log_to_file = opts.daemon or os.environ.get("XPRA_LOG_TO_FILE", "") == "1"
    log_dir = opts.log_dir or ""
    if start_vfb or log_to_file:
        # we will probably need a log dir
        # either for the vfb, or for our own log file
        if not log_dir or log_dir.lower() == "auto":
            log_dir = session_dir
        # expose the log-dir as "XPRA_LOG_DIR",
        # this is used by Xdummy for the Xorg log file
        if "XPRA_LOG_DIR" not in os.environ:
            os.environ["XPRA_LOG_DIR"] = log_dir

    log_filename0 = ""
    if log_to_file:
        log_filename0 = osexpand(select_log_file(log_dir, opts.log_file, display_name),
                                 username, uid, gid, extra_expand)
        if os.path.exists(log_filename0) and not display_name.startswith("S"):
            # don't overwrite the log file just yet,
            # as we may still fail to start
            log_filename0 += ".new"
        logfd = open_log_file(log_filename0)
        if POSIX:
            os.fchmod(logfd, 0o640)
            if ROOT and (uid > 0 or gid > 0):
                try:
                    os.fchown(logfd, uid, gid)
                except OSError as e:
                    noerr(stderr.write, f"failed to chown the log file {log_filename0!r}\n")
                    noerr(stderr.write, f" {e!r}\n")
                    noerr(stderr.flush)
        stdout, stderr = redirect_std_to_log(logfd)
        noerr(stderr.write, f"Entering daemon mode; any further errors will be reported to:\n  {log_filename0!r}\n")
        noerr(stderr.flush)
        os.environ["XPRA_SERVER_LOG"] = log_filename0
    else:
        # server log does not exist:
        os.environ.pop("XPRA_SERVER_LOG", None)

    # warn early about this:
    if (starting or starting_desktop) and desktop_display and opts.notifications and not opts.dbus_launch:
        print_DE_warnings()

    if start_vfb and opts.sync_xvfb is None and any(xvfb_cmd[0].find(x) >= 0 for x in ("Xephyr", "Xnest")):
        # automatically enable sync-xvfb for Xephyr and Xnest:
        opts.sync_xvfb = 50

    if not (shadowing or starting_desktop or upgrading_desktop or upgrading_monitor):
        opts.rfb_upgrade = 0
        if opts.bind_rfb:
            get_logger().warn(f"Warning: bind-rfb sockets cannot be used with {mode!r} mode")
            opts.bind_rfb = []
        if opts.bind_rdp:
            get_logger().warn(f"Warning: bind-rdp sockets cannot be used with {mode!r} mode")
            opts.bind_rdp = []

    progress(30, "creating sockets")
    from xpra.net.socket_util import get_network_logger, setup_local_sockets, create_sockets
    retry = 10 * int(mode.startswith("upgrade"))
    sockets = create_sockets(opts, error_cb, retry=retry, sd_listen=POSIX and not OSX, ssh_upgrades=opts.ssh_upgrade)

    from xpra.log import Logger
    log = Logger("server")
    log("env=%s", os.environ)

    if POSIX and starting_desktop and not use_display and DESKTOP_GREETER:
        # if there are no start commands, auto-add a greeter:
        commands = []
        for start_prop in (
                "start", "start-late",
                "start-child", "start-child-late",
                "start-after-connect", "start-child-after-connect",
                "start-on-connect", "start-child-on-connect",
                "start-on-last-client-exit", "start-child-on-last-client-exit",
        ):
            commands += list(getattr(opts, start_prop.replace("-", "_")))
        if not commands:
            opts.start.append("xpra desktop-greeter")
    if POSIX and not (
            upgrading or shadowing or proxying or encoder
    ) and configure_imsettings_env(opts.input_method) == "ibus":
        # start ibus-daemon unless already specified in 'start':
        if IBUS_DAEMON_COMMAND and not (any(x.find("ibus-daemon") >= 0 for x in opts.start) or any(
            x.find("ibus-daemon") >= 0 for x in opts.start_late)
        ):
            # maybe we are inheriting one from a dead session?
            ibus_daemon_pid = load_pid(session_dir, "ibus-daemon.pid")
            if not ibus_daemon_pid or not os.path.exists("/proc") or not os.path.exists(f"/proc/{ibus_daemon_pid}"):
                Logger("ibus").debug("adding ibus-daemon to late startup")
                opts.start_late.insert(0, IBUS_DAEMON_COMMAND)

    # Start the Xvfb server first to get the display_name if needed
    odisplay_name = display_name
    xvfb = None
    xauthority = None
    if POSIX and not OSX and (start_vfb or clobber or (shadowing and display_name.startswith(":"))) and display_name.find("wayland") < 0:
        # XAUTHORITY
        from xpra.x11.vfb_util import get_xauthority_path, valid_xauth, xauth_add
        xauthority = valid_xauth((load_session_file("xauthority")).decode(), uid, gid)
        if not xauthority:
            # from here on, we need to save the `xauthority` session file
            # since there is no session file, or it isn't valid
            if SHARED_XAUTHORITY:
                # re-using the value from the environment may not always be safe
                # as the file may be removed when the X11 session that created it is closed,
                # but users expect things to "just work" in most cases,
                # and be able to run commands such as `DISPLAY=:10 xterm`,
                # so this is enabled by default
                xauthority = os.environ.get("XAUTHORITY", "")
            if shadowing and not valid_xauth(xauthority, uid, gid):
                # look for xauth files in magic directories (yuk)
                # matching this user, see ticket #3917
                xauth_time = 0.0
                candidates = [
                    "/tmp/xauth*",
                    "/tmp/.Xauth*",
                    "/var/run/*dm/xauth*",
                    "/var/run/lightdm/$USER/xauthority",
                    "$XDG_RUNTIME_DIR/xauthority",
                    "$XDG_RUNTIME_DIR/Xauthority",
                    "$XDG_RUNTIME_DIR/gdm/xauthority",
                    "$XDG_RUNTIME_DIR/gdm/Xauthority",
                ]
                for globstr in candidates:
                    for filename in glob.glob(osexpand(globstr, actual_username=username, uid=uid, gid=gid)):
                        if not os.path.isfile(filename):
                            continue
                        try:
                            stat_info = os.stat(filename)
                        except OSError:
                            continue
                        if not ROOT and stat_info.st_uid != uid:
                            continue
                        if xauth_time == 0.0 or stat_info.st_mtime > xauth_time:
                            xauthority = filename
                            xauth_time = stat_info.st_mtime
            if not valid_xauth(xauthority, uid, gid):
                # we can choose the path to use:
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
                    if ROOT and (uid != 0 or gid != 0):
                        os.fchown(xauth_file.fileno(), uid, gid)
            elif not is_writable(xauthority, uid, gid) and not ROOT:
                log(f"chmoding XAUTHORITY file {xauthority!r}")
                os.chmod(xauthority, 0o640)
            write_session_file("xauthority", xauthority)
            log(f"using XAUTHORITY file {xauthority!r}")
        os.environ["XAUTHORITY"] = xauthority
        # resolve use-display='auto':
        if (use_display is None or upgrading) and not proxying and not encoder:
            # figure out if we have to start the vfb or not
            # bail out if we need a display that is not running
            if not display_name:
                if upgrading:
                    error_cb("no displays found to upgrade")
                use_display = False
            else:
                progress(40, "connecting to the display")
                if verify_display(None, display_name, log_errors=False, timeout=1):
                    # accessed OK:
                    progress(40, "connected to the display")
                    start_vfb = False
                else:
                    stat = {}
                    if display_name.startswith(":"):
                        x11_socket_path = os.path.join(X11_SOCKET_DIR, "X" + display_name[1:])
                        stat = stat_display_socket(x11_socket_path)
                        log(f"stat_display_socket({x11_socket_path})={stat}")
                        if not stat and (upgrading or shadowing):
                            error_cb(f"cannot access display {display_name!r}")
                        # no X11 socket to connect to, so we have to start one:
                        start_vfb = True
                    if stat:
                        # we can't connect to the X11 display,
                        # but we can still `stat` its socket...
                        # perhaps we need to re-add an xauth entry
                        if not xauth_data:
                            xauth_data = get_hex_uuid()
                            if pam:
                                pam.set_items({"XAUTHDATA": xauth_data})
                        xauth_add(xauthority, display_name, xauth_data, uid, gid)
                        if not verify_display(None, display_name, log_errors=False, timeout=1):
                            warn(f"display {display_name!r} is not accessible")
                        else:
                            # now OK!
                            start_vfb = False
    xvfb_pid = 0
    devices = {}
    if POSIX and not OSX:
        from xpra.server.util import has_uinput, UINPUT_UUID_LEN
        uinput_uuid = ""
        use_uinput = not (shadowing or proxying or encoder) and opts.input_devices.lower() in ("uinput", "auto") and has_uinput()
        if start_vfb:
            progress(40, "starting a virtual display")
            from xpra.x11.vfb_util import start_Xvfb, parse_resolutions, xauth_add
            assert not proxying and xauth_data
            pixel_depth = validate_pixel_depth(opts.pixel_depth, starting_desktop or starting_monitor)
            if use_uinput:
                # this only needs to be fairly unique:
                uinput_uuid = get_rand_chars(UINPUT_UUID_LEN).decode("latin1")
                write_session_file("uinput-uuid", uinput_uuid)
            vfb_geom: tuple | None = ()
            if opts.resize_display.lower() not in ALL_BOOLEAN_OPTIONS:
                # "off:1080p" -> "1080p"
                # "4k" -> "4k"
                sizes = opts.resize_display.split(":", 1)[-1]
                vfb_geom = parse_resolutions(sizes, opts.refresh_rate)[0]

            xvfb, display_name = start_Xvfb(xvfb_cmd, vfb_geom, pixel_depth, display_name, cwd,
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

            vfb_procinfo = getChildReaper().add_process(xvfb, "xvfb", xvfb_cmd, ignore=True, callback=xvfb_terminated)
            log("xvfb process info=%s", vfb_procinfo.get_info())
            # always update as we may now have the "real" display name:
            os.environ["DISPLAY"] = display_name
            os.environ["CKCON_X11_DISPLAY"] = display_name
            os.environ.update(protected_env)
            if display_name != odisplay_name:
                # update with the real display value:
                if pam:
                    pam.set_items({"XDISPLAY": display_name})
                if session_dir:
                    new_session_dir = get_session_dir(mode, opts.sessions_dir, display_name, uid)
                    if new_session_dir != session_dir:
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
                        session_dir = new_session_dir
                        # update session dir if needed:
                        if not opts.log_dir or opts.log_dir.lower() == "auto":
                            log_dir = session_dir
                        os.environ["XPRA_SESSION_DIR"] = new_session_dir
        elif POSIX and not OSX and not shadowing and not proxying:
            try:
                xvfb_pid = int(load_session_file("xvfb.pid") or 0)
            except ValueError:
                pass
            log(f"reloaded xvfb.pid={xvfb_pid} from session file")
            if use_uinput:
                uinput_uuid = load_session_file("uinput-uuid").decode("latin1")
        if uinput_uuid:
            devices = create_input_devices(uinput_uuid, uid)

    def check_xvfb(timeout=0) -> bool:
        if xvfb is None:
            return True
        from xpra.x11.vfb_util import check_xvfb_process
        if not check_xvfb_process(xvfb, timeout=timeout, command=xvfb_cmd):
            progress(100, "xvfb failed")
            return False
        return True

    write_displayfd(display_name, displayfd)

    if not check_xvfb(1):
        noerr(stderr.write, "vfb failed to start, exiting\n")
        return ExitCode.VFB_ERROR

    if WIN32 and os.environ.get("XPRA_LOG_FILENAME"):
        os.environ["XPRA_SERVER_LOG"] = os.environ["XPRA_LOG_FILENAME"]
    if opts.daemon:
        if odisplay_name != display_name:
            # this may be used by scripts, let's try not to change it:
            noerr(stderr.write, f"Actual display used: {display_name}\n")
            noerr(stderr.flush)
        log_filename1 = osexpand(select_log_file(log_dir, opts.log_file, display_name),
                                 username, uid, gid, extra_expand)
        if log_filename0 != log_filename1:
            if not os.path.exists(log_filename0) and os.path.exists(log_filename1) and log_filename1.startswith(
                    session_dir):  # noqa: E501
                # the session dir was renamed with the log file inside it,
                # so we don't need to rename the log file
                pass
            else:
                # we now have the correct log filename, so use it:
                try:
                    os.rename(log_filename0, log_filename1)
                except OSError:
                    pass
            os.environ["XPRA_SERVER_LOG"] = log_filename1
            noerr(stderr.write, f"Actual log file name is now: {log_filename1!r}\n")
            noerr(stderr.flush)
        noerr(stdout.close)
        noerr(stderr.close)
    # we should not be using stdout or stderr from this point on:
    del stdout
    del stderr

    if not check_xvfb():
        return ExitCode.VFB_ERROR

    if ROOT and (uid != 0 or gid != 0):
        log("root: switching to uid=%i, gid=%i", uid, gid)
        setuidgid(uid, gid)
        os.environ.update({
            "HOME": home,
            "USER": username,
            "LOGNAME": username,
        })
        shell = get_shell_for_uid(uid)
        if shell:
            os.environ["SHELL"] = shell
        # now we've changed uid, it is safe to honour all the env updates:
        configure_env(opts.env)
        os.environ.update(protected_env)
    else:
        configure_env(opts.env)

    if opts.chdir:
        log(f"chdir({opts.chdir})")
        os.chdir(osexpand(opts.chdir))

    dbus_pid = 0
    dbus_env: dict[str, str] = {}
    if opts.dbus and not shadowing and POSIX and not OSX:
        dbuslog = Logger("dbus")
        dbus_pid, dbus_env = reload_dbus_attributes(display_name)
        if not (dbus_pid and dbus_env):
            no_gtk()
            if not (starting or starting_desktop or starting_monitor or proxying or encoder):
                dbuslog.warn("Warning: failed to reload the dbus session attributes")
                dbuslog.warn(f" for mode {mode}")
                dbuslog.warn(" a new dbus instance will be started")
                dbuslog.warn(" which may conflict with the previous one if it exists")
            try:
                from xpra.server.dbus.start import start_dbus
            except ImportError as e:
                dbuslog("dbus components are not installed: %s", e)
            else:
                dbus_pid, dbus_env = start_dbus(opts.dbus_launch)
                if dbus_env:
                    dbuslog(f"started new dbus instance: {dbus_env}")
                    write_session_file("dbus.pid", f"{dbus_pid}")
                    dbus_env_data = "\n".join("{}={}".format(k, v) for k, v in dbus_env.items()) + "\n"
                    write_session_file("dbus.env", dbus_env_data.encode("utf8"))
        if dbus_env:
            os.environ.update(dbus_env)

    if SSH_AGENT_DISPATCH and not (shadowing or proxying or encoder) and opts.ssh.lower() not in FALSE_OPTIONS:
        progress(50, "setup ssh agent forwarding")
        try:
            from xpra.net.ssh.agent import setup_ssh_auth_sock
            ssh_auth_sock = setup_ssh_auth_sock(session_dir)
            os.environ["SSH_AUTH_SOCK"] = ssh_auth_sock
            protected_env["SSH_AUTH_SOCK"] = ssh_auth_sock
        except Exception as e:
            log.error("Error setting up ssh agent forwarding", exc_info=True)
            progress(50, f"error setting up ssh agent forwarding: {e}")

    if not (proxying or encoder):
        if POSIX and not OSX:
            no_gtk()
            if starting or starting_desktop or starting_monitor:
                if not verify_display(xvfb, display_name, shadowing):
                    log.error(f"Error: unable to access display {display_name!r}")
                    return ExitCode.NO_DISPLAY
        # on win32, this ensures that we get the correct screen size to shadow:
        from xpra.platform.gui import init as gui_init
        log("gui_init()")
        gui_init()

    def init_local_sockets() -> None:
        progress(60, "initializing local sockets")
        # setup unix domain socket:
        netlog = get_network_logger()
        local_sockets = setup_local_sockets(
            opts.bind,  # noqa: F821
            opts.socket_dir, opts.socket_dirs, session_dir,  # noqa: F821
            display_name, clobber,  # noqa: F821
            opts.mmap_group, opts.socket_permissions,  # noqa: F821
            username, uid, gid)
        netlog(f"setting up local sockets: {local_sockets}")
        sockets.update(local_sockets)
        if POSIX and (starting or upgrading or starting_desktop):
            # all unix domain sockets:
            ud_paths = [sockpath for stype, _, sockpath, _ in local_sockets if stype == "socket"]
            forward_xdg_open = bool(opts.forward_xdg_open) or (  # noqa: F821
                opts.forward_xdg_open is None and mode.find("desktop") < 0 and mode.find("monitor") < 0
            )  # noqa: F821
            if ud_paths:
                os.environ["XPRA_SERVER_SOCKET"] = ud_paths[0]
                if forward_xdg_open and os.path.exists("/usr/libexec/xpra/xdg-open"):
                    os.environ["PATH"] = "/usr/libexec/xpra" + os.pathsep + os.environ.get("PATH", "")
            else:
                log.warn("Warning: no local server sockets,")
                if forward_xdg_open:
                    log.warn(" forward-xdg-open cannot be enabled")
                log.warn(" non-embedded ssh connections will not be available")

    set_server_features(opts, mode)
    if envbool("XPRA_ENFORCE_FEATURES", True):
        enforce_server_features()

    if not (proxying or shadowing or encoder) and POSIX and not OSX:
        if not check_xvfb():
            return 1
        from xpra.x11.gtk.display_source import init_gdk_display_source
        if os.environ.get("NO_AT_BRIDGE") is None:
            os.environ["NO_AT_BRIDGE"] = "1"
        init_gdk_display_source()

        if not xvfb_pid:
            # perhaps this is an upgrade from an older version?
            # try harder to find the pid:
            def _get_int(prop) -> int:
                from xpra.x11.bindings.core import X11CoreBindings
                from xpra.x11.gtk.prop import prop_get
                try:
                    xid = X11CoreBindings().get_root_xid()
                    return prop_get(xid, prop, "u32")
                except Exception:
                    return 0

            xvfb_pid = _get_int(b"XPRA_XVFB_PID") or _get_int(b"_XPRA_SERVER_PID")

    progress(80, "initializing server")
    if "backend" not in mode_attrs:
        mode_attrs["backend"] = opts.backend
    if shadowing:
        # "shadow" -> multi-window=True, "shadow-screen" -> multi-window=False
        mode_attrs["multi-window"] = str(mode == "shadow")
        app = make_shadow_server(display_name, mode_attrs)
    elif proxying:
        app = make_proxy_server()
    elif expanding:
        app = make_expand_server(mode_attrs)
    elif encoder:
        app = make_encoder_server()
    else:
        if starting or upgrading_seamless:
            app = make_seamless_server(clobber)
        elif starting_desktop or upgrading_desktop:
            app = make_desktop_server()
        else:
            assert starting_monitor or upgrading_monitor
            app = make_monitor_server()
        app.init_virtual_devices(devices)

    def server_not_started(msg="server not started"):
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
        app.splash_process = splash_process
        app.exec_cwd = opts.chdir or cwd
        app.display_name = display_name
        app.display_options = display_options
        app.init(opts)
        if not app.validate():
            progress(100, "server validation failed")
            return 1
        init_local_sockets()
        app.init_sockets(sockets)
        from xpra.server import features
        if features.dbus:
            app.init_dbus(dbus_pid, dbus_env)
        if not (shadowing or proxying or expanding or encoder):
            app.init_display_pid(xvfb_pid)
            app.save_pid()
        app.original_desktop_display = desktop_display
        progress(90, "finalizing")
        app.server_init()
        app.setup()
    except InitInfo as e:
        for m in str(e).split("\n"):
            log.info("%s", m)
        server_not_started(str(e))
        return ExitCode.OK
    except InitExit as e:
        for m in str(e).split("\n"):
            log.info("%s", m)
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

    ######################################################################
    if opts.attach is True:
        attach_client(opts, defaults)

    try:
        progress(100, "running")
        log("%s()", app.run)
        r = app.run()
        log("%s()=%s", app.run, r)
    except KeyboardInterrupt:
        log.info("stopping on KeyboardInterrupt")
        app.cleanup()
        r = ExitCode.OK
    except Exception:
        log.error("server error", exc_info=True)
        app.cleanup()
        r = -128
    else:
        if r > 0:
            r = 0
    return r


def attach_client(options, defaults) -> None:
    from xpra.platform.paths import get_xpra_command
    cmd = get_xpra_command() + ["attach"]
    display_name = os.environ.get("DISPLAY")
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
    getChildReaper().add_process(proc, "client-attach", cmd, ignore=True, forget=False)


def verify_gdk_display(display_name: str):
    # pylint: disable=import-outside-toplevel
    # Now we can safely load gtk and connect:
    Gdk = gi_import("Gdk")
    display = Gdk.Display.open(display_name)
    if not display:
        return None
    manager = Gdk.DisplayManager.get()
    default_display = manager.get_default_display()
    if default_display is not None and default_display != display:
        default_display.close()
    manager.set_default_display(display)
    return display
