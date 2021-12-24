# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2021 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=import-outside-toplevel

# DO NOT IMPORT GTK HERE: see
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000041.html
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000042.html
# (also do not import anything that imports gtk)
import sys
import glob
import os.path
import datetime
from subprocess import Popen  #pylint: disable=import-outside-toplevel

from xpra import __version__
from xpra.scripts.main import (
    info, warn,
    no_gtk, bypass_no_gtk, nox,
    validate_encryption, parse_env, configure_env,
    stat_X11_display, get_xpra_sessions,
    make_progress_process,
    X11_SOCKET_DIR,
    )
from xpra.scripts.config import (
    InitException, InitInfo, InitExit,
    FALSE_OPTIONS, OPTION_TYPES, CLIENT_ONLY_OPTIONS, CLIENT_OPTIONS,
    parse_bool,
    fixup_options, make_defaults_struct, read_config, dict_to_validated_config,
    )
from xpra.common import CLOBBER_USE_DISPLAY, CLOBBER_UPGRADE
from xpra.exit_codes import EXIT_VFB_ERROR, EXIT_OK, EXIT_FAILURE, EXIT_UPGRADE
from xpra.os_util import (
    SIGNAMES, POSIX, WIN32, OSX,
    FDChangeCaptureContext,
    force_quit,
    which,
    get_saved_env, get_saved_env_var,
    get_rand_chars,
    get_username_for_uid, get_home_for_uid, get_shell_for_uid, setuidgid,
    getuid, get_groups, get_group_id,
    get_hex_uuid, get_util_logger, osexpand,
    load_binary_file,
    )
from xpra.util import envbool, unsetenv, noerr, SERVER_UPGRADE
from xpra.common import GROUP
from xpra.child_reaper import getChildReaper
from xpra.platform.dotxpra import DotXpra


DESKTOP_GREETER = envbool("XPRA_DESKTOP_GREETER", True)
CLEAN_SESSION_FILES = envbool("XPRA_CLEAN_SESSION_FILES", True)
IBUS_DAEMON_COMMAND = os.environ.get("XPRA_IBUS_DAEMON_COMMAND",
                                     "ibus-daemon --xim --verbose --replace --panel=disable --desktop=xpra --daemonize")


def deadly_signal(signum):
    info("got deadly signal %s, exiting\n" % SIGNAMES.get(signum, signum))
    # This works fine in tests, but for some reason if I use it here, then I
    # get bizarre behavior where the signal handler runs, and then I get a
    # KeyboardException (?!?), and the KeyboardException is handled normally
    # and exits the program (causing the cleanup handlers to be run again):
    #signal.signal(signum, signal.SIG_DFL)
    #kill(os.getpid(), signum)
    force_quit(128 + signum)


def validate_pixel_depth(pixel_depth, starting_desktop=False):
    try:
        pixel_depth = int(pixel_depth)
    except ValueError:
        raise InitException("invalid value '%s' for pixel depth, must be a number" % pixel_depth) from None
    if pixel_depth==0:
        pixel_depth = 24
    if pixel_depth not in (8, 16, 24, 30):
        raise InitException("invalid pixel depth: %s" % pixel_depth)
    if not starting_desktop and pixel_depth==8:
        raise InitException("pixel depth 8 is only supported in 'start-desktop' mode")
    return pixel_depth


def display_name_check(display_name):
    """ displays a warning
        when a low display number is specified """
    if not display_name.startswith(":"):
        return
    n = display_name[1:].split(".")[0]    #ie: ":0.0" -> "0"
    try:
        dno = int(n)
    except (ValueError, TypeError):
        raise InitException("invalid display number %r" % n) from None
    else:
        if 0<=dno<10:
            warn("WARNING: low display number: %s" % dno)
            warn(" You are attempting to run the xpra server")
            warn(" against a low X11 display number: '%s'." % (display_name,))
            warn(" This is generally not what you want.")
            warn(" You should probably use a higher display number")
            warn(" just to avoid any confusion and this warning message.")


def print_DE_warnings():
    de = os.environ.get("XDG_SESSION_DESKTOP") or os.environ.get("SESSION_DESKTOP")
    if not de:
        return
    log = get_util_logger()
    log.warn("Warning: xpra start from an existing '%s' desktop session", de)
    log.warn(" without using dbus-launch,")
    log.warn(" notifications forwarding may not work")
    log.warn(" try using a clean environment, a dedicated user,")
    log.warn(" or disable xpra's notifications option")


def sanitize_env():
    #we don't want client apps to think these mean anything:
    #(if set, they belong to the desktop the server was started from)
    #TODO: simply whitelisting the env would be safer/better
    unsetenv("DESKTOP_SESSION",
             "GDMSESSION",
             "GNOME_DESKTOP_SESSION_ID",
             "SESSION_MANAGER",
             "XDG_VTNR",
             #we must keep this value on Debian / Ubuntu
             #to avoid breaking menu loading:
             #"XDG_MENU_PREFIX",
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
             "WAYLAND_DISPLAY",
             )

def configure_imsettings_env(input_method):
    im = (input_method or "").lower()
    if im=="auto":
        ibus_daemon = which("ibus-daemon")
        if ibus_daemon:
            im = "ibus"
        else:
            im = "none"
    if im in ("none", "no"):
        #the default: set DISABLE_IMSETTINGS=1, fallback to xim
        #that's because the 'ibus' 'immodule' breaks keyboard handling
        #unless its daemon is also running - and we don't know if it is..
        imsettings_env(True, "xim", "xim", "xim", "none", "@im=none")
    elif im=="keep":
        #do nothing and keep whatever is already set, hoping for the best
        pass
    elif im in ("xim", "ibus", "scim", "uim"):
        #ie: (False, "ibus", "ibus", "IBus", "@im=ibus")
        imsettings_env(True, im.lower(), im.lower(), im.lower(), im, "@im=%s" % im.lower())
    else:
        v = imsettings_env(True, im.lower(), im.lower(), im.lower(), im, "@im=%s" % im.lower())
        warn("using input method settings: %s" % str(v))
        warn("unknown input method specified: %s" % input_method)
        warn(" if it is correct, you may want to file a bug to get it recognized")
    return im

def imsettings_env(disabled, gtk_im_module, qt_im_module, clutter_im_module, imsettings_module, xmodifiers):
    #for more information, see imsettings:
    #https://code.google.com/p/imsettings/source/browse/trunk/README
    if disabled is True:
        os.environ["DISABLE_IMSETTINGS"] = "1"                  #this should override any XSETTINGS too
    elif disabled is False and ("DISABLE_IMSETTINGS" in os.environ):
        del os.environ["DISABLE_IMSETTINGS"]
    v = {
         "GTK_IM_MODULE"      : gtk_im_module,            #or "gtk-im-context-simple"?
         "QT_IM_MODULE"       : qt_im_module,             #or "simple"?
         "QT4_IM_MODULE"      : qt_im_module,
         "CLUTTER_IM_MODULE"  : clutter_im_module,
         "IMSETTINGS_MODULE"  : imsettings_module,        #or "xim"?
         "XMODIFIERS"         : xmodifiers,
         #not really sure what to do with those:
         #"IMSETTINGS_DISABLE_DESKTOP_CHECK"   : "true",   #
         #"IMSETTINGS_INTEGRATE_DESKTOP" : "no"}           #we're not a real desktop
        }
    os.environ.update(v)
    return v

def create_runtime_dir(xrd, uid, gid):
    if not POSIX or OSX or getuid()!=0 or (uid==0 and gid==0):
        return
    #workarounds:
    #* some distros don't set a correct value,
    #* or they don't create the directory for us,
    #* or pam_open is going to create the directory but needs time to do so..
    if xrd and xrd.endswith("/user/0"):
        #don't keep root's directory, as this would not work:
        xrd = None
    if not xrd:
        #find the "/run/user" directory:
        run_user = "/run/user"
        if not os.path.exists(run_user):
            run_user = "/var/run/user"
        if os.path.exists(run_user):
            xrd = os.path.join(run_user, str(uid))
    if not xrd:
        return None
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


def guess_xpra_display(socket_dir, socket_dirs):
    dotxpra = DotXpra(socket_dir, socket_dirs)
    results = dotxpra.sockets()
    live = [display for state, display in results if state==DotXpra.LIVE]
    if not live:
        raise InitException("no existing xpra servers found")
    if len(live)>1:
        raise InitException("too many existing xpra servers found, cannot guess which one to use")
    return live[0]


def show_encoding_help(opts):
    #avoid errors and warnings:
    opts.encoding = ""
    opts.clipboard = False
    opts.notifications = False
    print("xpra server supports the following encodings:")
    print("(please wait, encoder initialization may take a few seconds)")
    #disable info logging which would be confusing here
    from xpra.log import get_all_loggers, set_default_level
    import logging
    set_default_level(logging.WARN)
    logging.root.setLevel(logging.WARN)
    for x in get_all_loggers():
        if x.logger.getEffectiveLevel()==logging.INFO:
            x.logger.setLevel(logging.WARN)
    from xpra.server.server_base import ServerBase
    sb = ServerBase()
    sb.init(opts)
    from xpra.codecs.codec_constants import PREFERRED_ENCODING_ORDER, HELP_ORDER
    if "help" in opts.encodings:
        sb.allowed_encodings = PREFERRED_ENCODING_ORDER
    from xpra.server.mixins.encoding_server import EncodingServer
    assert isinstance(sb, EncodingServer)
    EncodingServer.threaded_setup(sb)
    from xpra.codecs.loader import encoding_help
    for e in (x for x in HELP_ORDER if x in sb.encodings):
        print(" * %s" % encoding_help(e))
    return 0


def set_server_features(opts):
    def b(v):
        return str(v).lower() not in FALSE_OPTIONS
    #turn off some server mixins:
    from xpra.server import server_features
    impwarned = []
    def impcheck(*modules):
        for mod in modules:
            try:
                __import__("xpra.%s" % mod, {}, {}, [])
            except ImportError:
                if mod not in impwarned:
                    impwarned.append(mod)
                    log = get_util_logger()
                    log.warn("Warning: missing %s module", mod)
                return False
        return True
    server_features.notifications   = opts.notifications and impcheck("notifications")
    server_features.webcam          = b(opts.webcam) and impcheck("codecs")
    server_features.clipboard       = b(opts.clipboard) and impcheck("clipboard")
    server_features.audio           = (b(opts.speaker) or b(opts.microphone)) and impcheck("sound")
    server_features.av_sync         = server_features.audio and b(opts.av_sync)
    server_features.fileprint       = b(opts.printing) or b(opts.file_transfer)
    server_features.mmap            = b(opts.mmap)
    server_features.input_devices   = not opts.readonly and impcheck("keyboard")
    server_features.commands        = impcheck("server.control_command")
    server_features.dbus            = opts.dbus_proxy and impcheck("dbus", "server.dbus")
    server_features.encoding        = impcheck("codecs")
    server_features.logging         = b(opts.remote_logging)
    #server_features.network_state   = ??
    server_features.shell           = envbool("XPRA_SHELL", True)
    server_features.display         = opts.windows
    server_features.windows         = opts.windows and impcheck("codecs")
    server_features.rfb             = b(opts.rfb_upgrade) and impcheck("server.rfb")


def make_desktop_server():
    from xpra.x11.desktop_server import XpraDesktopServer
    return XpraDesktopServer()

def make_server(clobber):
    from xpra.x11.server import XpraServer
    return XpraServer(clobber)

def make_shadow_server():
    from xpra.platform.shadow_server import ShadowServer
    return ShadowServer()

def make_proxy_server():
    from xpra.platform.proxy_server import ProxyServer
    return ProxyServer()


def verify_display(xvfb=None, display_name=None, shadowing=False, log_errors=True, timeout=None):
    #check that we can access the X11 display:
    from xpra.x11.vfb_util import verify_display_ready, VFB_WAIT
    if timeout is None:
        timeout = VFB_WAIT
    if not verify_display_ready(xvfb, display_name, shadowing, log_errors, timeout):
        return 1
    from xpra.log import Logger
    log = Logger("screen", "x11")
    log("X11 display is ready")
    no_gtk()
    from xpra.x11.gtk_x11.gdk_display_source import verify_gdk_display
    display = verify_gdk_display(display_name)
    if not display:
        return 1
    log("GDK can access the display")
    return 0

def write_displayfd(display_name, fd):
    if OSX or not POSIX or fd<=0:
        return
    from xpra.log import Logger
    log = Logger("server")
    try:
        from xpra.platform import displayfd
        display_no = display_name[1:]
        #ensure it is a string containing the number:
        display_no = str(int(display_no))
        log("writing display_no='%s' to displayfd=%i", display_no, fd)
        assert displayfd.write_displayfd(fd, display_no), "timeout"
    except Exception as e:
        log.error("write_displayfd failed", exc_info=True)
        log.error("Error: failed to write '%s' to fd=%s", display_name, fd)
        log.error(" %s", str(e) or type(e))


def get_session_dir(mode, sessions_dir, display_name, uid):
    session_dir = osexpand(os.path.join(sessions_dir, display_name.lstrip(":")), uid=uid)
    if not os.path.exists(session_dir):
        ROOT = POSIX and getuid()==0
        if ROOT and uid==0:
            #there is usually no $XDG_RUNTIME_DIR when running as root
            #and even if there was, that's probably not a good path to use,
            #so try to find a more suitable directory we can use:
            for d in ("/run/xpra", "/var/run/xpra", "/tmp"):
                if os.path.exists(d):
                    if mode=="proxy" and (display_name or "").lstrip(":").split(",")[0]=="14500":
                        #stash the system wide proxy session files in a 'proxy' subdirectory:
                        return os.path.join(d, "proxy")
                    #otherwise just use the display as subdirectory name:
                    return os.path.join(d, (display_name or "").lstrip(":"))
    return session_dir

def make_session_dir(mode, sessions_dir, display_name, uid=0, gid=0):
    session_dir = get_session_dir(mode, sessions_dir, display_name, uid)
    try:
        os.makedirs(session_dir, 0o750, exist_ok=True)
    except OSError:
        import tempfile
        session_dir = osexpand(os.path.join(tempfile.gettempdir(), display_name.lstrip(":")))
        os.makedirs(session_dir, 0o750, exist_ok=True)
    ROOT = POSIX and getuid()==0
    if ROOT and (session_dir.startswith("/run/user/") or session_dir.startswith("/run/xpra/")):
        os.lchown(session_dir, uid, gid)
    return session_dir

def session_file_path(filename):
    session_dir = os.environ["XPRA_SESSION_DIR"]
    return os.path.join(session_dir, filename)

def load_session_file(filename):
    return load_binary_file(session_file_path(filename))

def save_session_file(filename, contents, uid=None, gid=None):
    if not os.environ.get("XPRA_SESSION_DIR"):
        return None
    if not isinstance(contents, bytes):
        contents = str(contents).encode("utf8")
    assert contents
    try:
        path = session_file_path(filename)
        with open(path, "wb+") as f:
            if POSIX:
                os.fchmod(f.fileno(), 0o640)
                if getuid()==0 and uid is not None and gid is not None:
                    os.fchown(f.fileno(), uid, gid)
            f.write(contents)
    except OSError as e:
        from xpra.log import Logger
        log = Logger("server")
        log("save_session_file", exc_info=True)
        log.error("Error saving session file '%s'", path)
        log.error(" %s", e)
    return path

def rm_session_dir():
    session_dir = os.environ.get("XPRA_SESSION_DIR")
    if not session_dir or not os.path.exists(session_dir):
        return
    try:
        session_files = os.listdir(session_dir)
    except OSError as e:
        from xpra.log import Logger
        log = Logger("server")
        log("os.listdir(%s)", session_dir, exc_info=True)
        log.warn("Warning: cannot access '%s'", session_dir)
        log.warn(" %s", e)
        return
    if not session_files:
        try:
            os.rmdir(session_dir)
        except OSError as e:
            from xpra.log import Logger
            log = Logger("server")
            log("rmdir(%s)", session_dir, exc_info=True)
            log.error("Error: failed to remove session directory '%s':", session_dir)
            log.error(" %s", e)

def clean_session_files(*filenames):
    if not CLEAN_SESSION_FILES:
        return
    for filename in filenames:
        path = session_file_path(filename)
        if path.find("*")>=0:
            clean_session_files(*glob.glob(path))
        elif os.path.exists(path):
            try:
                os.unlink(path)
            except OSError as e:
                from xpra.log import Logger
                log = Logger("server")
                log("clean_session_files%s", filenames, exc_info=True)
                log.error("Error removing session file '%s'", filename)
                log.error(" %s", e)
    rm_session_dir()

SERVER_SAVE_SKIP_OPTIONS = (
    "systemd-run",
    "daemon",
    )

SERVER_LOAD_SKIP_OPTIONS = (
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

def get_options_file_contents(opts, mode="seamless"):
    from xpra.scripts.parsing import fixup_defaults
    defaults = make_defaults_struct()
    fixup_defaults(defaults)
    fixup_options(defaults)
    diff_contents = [
        "# xpra server %s" % __version__,
        "",
        "mode=%s" % mode,
        ]
    for attr, dtype in OPTION_TYPES.items():
        if attr in CLIENT_ONLY_OPTIONS:
            continue
        if attr in SERVER_SAVE_SKIP_OPTIONS:
            continue
        aname = attr.replace("-", "_")
        dval = getattr(defaults, aname, None)
        cval = getattr(opts, aname, None)
        if dval!=cval:
            if dtype is bool:
                BOOL_STR = {True : "yes", False : "no", None : "auto"}
                diff_contents.append("%s=%s" % (attr, BOOL_STR.get(cval, cval)))
            elif dtype in (tuple, list):
                for x in cval or ():
                    diff_contents.append("%s=%s" % (attr, x))
            else:
                diff_contents.append("%s=%s" % (attr, cval))
    diff_contents.append("")
    return "\n".join(diff_contents)

def load_options():
    config_file = session_file_path("config")
    return read_config(config_file)

def apply_config(opts, mode):
    #if we had saved the start / start-desktop config, reload it:
    options = load_options()
    if not options:
        return mode
    if mode=="upgrade":
        #unspecified upgrade, try to find the original mode used:
        mode = options.pop("mode", mode)
    upgrade_config = dict_to_validated_config(options)
    #apply the previous session options:
    for k in options.keys():
        if k in CLIENT_ONLY_OPTIONS:
            continue
        if k in SERVER_LOAD_SKIP_OPTIONS:
            continue
        dtype = OPTION_TYPES.get(k)
        if not dtype:
            continue
        fn = k.replace("-", "_")
        if not hasattr(upgrade_config, fn):
            warn("%s not found in saved config" % k)
            continue
        if not hasattr(opts, fn):
            warn("%s not found in config" % k)
            continue
        value = getattr(upgrade_config, fn)
        setattr(opts, fn, value)
    return mode


def reload_dbus_attributes(display_name):
    from xpra.log import Logger
    dbuslog = Logger("dbus")
    try:
        dbus_pid = int(load_session_file("dbus.pid") or 0)
    except ValueError:
        dbus_pid = 0
    dbus_env_data = load_session_file("dbus.env")
    dbuslog("reload_dbus_attributes(%s) found dbus_pid=%s, dbus_env_data=%s",
            display_name, dbus_pid, dbus_env_data)
    dbus_env = {}
    if dbus_env_data:
        for line in dbus_env_data.splitlines():
            if not line or line.startswith(b"#") or line.find(b"=")<0:
                continue
            parts = line.split(b"=", 1)
            dbus_env[parts[0]] = parts[1]
    dbuslog("reload_dbus_attributes(%s) dbus_env=%s",
            display_name, dbus_env)
    dbus_address = dbus_env.get(b"DBUS_SESSION_BUS_ADDRESS")
    if not (dbus_pid and dbus_address):
        #less reliable: get it from the wminfo output:
        from xpra.scripts.main import exec_wminfo
        wminfo = exec_wminfo(display_name)
        if not dbus_pid:
            try:
                dbus_pid = int(wminfo.get("dbus-pid", 0))
                dbus_env[b"DBUS_SESSION_BUS_PID"] = ("%s" % dbus_pid).encode("latin1")
            except ValueError:
                pass
        if not dbus_address:
            dbus_address = wminfo.get("dbus-address")
            if dbus_address:
                dbus_env[b"DBUS_SESSION_BUS_ADDRESS"] = dbus_address.encode()
    if dbus_pid and os.path.exists("/proc") and not os.path.exists("/proc/%s" % dbus_pid):
        dbuslog("dbus pid %s is no longer valid", dbus_pid)
        dbus_pid = 0
    if dbus_pid and dbus_address:
        dbuslog("retrieved dbus pid: %s, environment: %s", dbus_pid, dbus_env)
    return dbus_pid, dbus_env


def is_splash_enabled(mode, daemon, splash, display):
    if daemon:
        #daemon mode would have problems with the pipes
        return False
    if splash in (True, False):
        return splash
    #auto mode, figure out if we should show it:
    if not POSIX:
        return True
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        #don't show the splash screen over SSH forwarding
        return False
    xdisplay = os.environ.get("DISPLAY")
    if xdisplay:
        #make sure that the display isn't the one we're running against,
        #unless we're shadowing it
        return xdisplay!=display or mode=="shadow"
    if mode=="proxy":
        return False
    if os.environ.get("XDG_SESSION_DESKTOP"):
        return True
    return False

MODE_TO_NAME = {
    "start"             : "Seamless",
    "start-desktop"     : "Desktop",
    "upgrade"           : "Upgrade",
    "upgrade-seamless"  : "Seamless Upgrade",
    "upgrade-desktop"   : "Desktop Upgrade",
    "shadow"            : "Shadow",
    "proxy"             : "Proxy",
    }

def request_exit(uri):
    from xpra.platform.paths import get_xpra_command
    cmd = get_xpra_command()+["exit", uri]
    env = os.environ.copy()
    #don't wait too long:
    env["XPRA_CONNECT_TIMEOUT"] = "5"
    #don't log disconnect message
    env["XPRA_LOG_DISCONNECT"] = "0"
    env["XPRA_EXIT_MESSAGE"] = SERVER_UPGRADE
    try:
        p = Popen(cmd, env=env)
        p.wait()
    except OSError as e:
        noerr(sys.stderr.write, "Error: failed to 'exit' the server to upgrade\n")
        noerr(sys.stderr.write, " %s\n" % e)
        return False
    return p.poll() in (EXIT_OK, EXIT_UPGRADE)

def do_run_server(script_file, cmdline, error_cb, opts, extra_args, mode, display_name, defaults):
    assert mode in (
        "start", "start-desktop",
        "upgrade", "upgrade-seamless", "upgrade-desktop",
        "shadow", "proxy",
        )
    validate_encryption(opts)
    if opts.encoding=="help" or "help" in opts.encodings:
        return show_encoding_help(opts)
    ################################################################################
    # splash screen:
    splash_process = None
    if is_splash_enabled(mode, opts.daemon, opts.splash, display_name):
        # use splash screen to show server startup progress:
        title = "Xpra %s Server %s" % (MODE_TO_NAME.get(mode, ""), __version__)
        splash_process = make_progress_process(title)
        def stop_progress_process():
            if splash_process.poll() is not None:
                return
            try:
                splash_process.terminate()
            except Exception:
                pass
        def show_progress(pct, text=""):
            if splash_process.poll() is not None:
                return
            noerr(splash_process.stdin.write, ("%i:%s\n" % (pct, text)).encode("latin1"))
            noerr(splash_process.stdin.flush)
            if pct==100:
                #it should exit on its own, but just in case:
                from xpra.common import SPLASH_EXIT_DELAY
                from gi.repository import GLib
                GLib.timeout_add(SPLASH_EXIT_DELAY*1000+500, stop_progress_process)
        progress = show_progress
    else:
        def noprogressshown(*_args):
            """ messages aren't shown """
        progress = noprogressshown
    progress(10, "initializing environment")
    try:
        return _do_run_server(script_file, cmdline,
                              error_cb, opts, extra_args, mode, display_name, defaults,
                              splash_process, progress)
    except Exception as e:
        progress(100, "error: %s" % e)
        raise

def _do_run_server(script_file, cmdline,
                   error_cb, opts, extra_args, mode, display_name, defaults,
                   splash_process, progress):
    desktop_display = nox()
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = os.path.expanduser("~")
        warn("current working directory does not exist, using '%s'\n" % cwd)

    #remove anything pointing to dbus from the current env
    #(so we only detect a dbus instance started by pam,
    # and override everything else)
    for k in tuple(os.environ.keys()):
        if k.startswith("DBUS_"):
            del os.environ[k]

    use_display = parse_bool("use-display", opts.use_display)
    starting  = mode == "start"
    starting_desktop = mode == "start-desktop"
    upgrading = mode.startswith("upgrade")
    shadowing = mode == "shadow"
    proxying  = mode == "proxy"

    if not proxying and POSIX and not OSX:
        #we don't support wayland servers,
        #so make sure GDK will use the X11 backend:
        os.environ["GDK_BACKEND"] = "x11"

    has_child_arg = (
            opts.start_child or
            opts.start_child_on_connect or
            opts.start_child_after_connect or
            opts.start_child_on_last_client_exit
            )
    if proxying or upgrading:
        #when proxying or upgrading, don't exec any plain start commands:
        opts.start = []
        opts.start_child = []
        opts.start_late = []
        opts.start_child_late = []
    elif opts.exit_with_children:
        assert has_child_arg, "exit-with-children was specified but start-child* is missing!"
    elif opts.start_child:
        warn("Warning: the 'start-child' option is used,")
        warn(" but 'exit-with-children' is not enabled,")
        warn(" you should just use 'start' instead")

    if (upgrading or shadowing) and opts.pulseaudio is None:
        #there should already be one running
        #so change None ('auto') to False
        opts.pulseaudio = False

    display_options = ""
    #get the display name:
    if shadowing and not extra_args:
        if WIN32 or OSX:
            #just a virtual name for the only display available:
            display_name = "Main"
        else:
            from xpra.scripts.main import guess_X11_display
            dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
            display_name = guess_X11_display(dotxpra, desktop_display)
    elif upgrading and not extra_args:
        display_name = guess_xpra_display(opts.socket_dir, opts.socket_dirs)
    else:
        if len(extra_args) > 1:
            error_cb("too many extra arguments (%i): only expected a display number" % len(extra_args))
        if len(extra_args) == 1:
            display_name = extra_args[0]
            #look for display options:
            #ie: ":1,DP-2" -> ":1" "DP-2"
            if display_name and display_name.find(",")>0:
                display_name, display_options = display_name.split(",", 1)
            if not shadowing and not upgrading and not use_display:
                display_name_check(display_name)
        else:
            if proxying:
                #find a free display number:
                dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
                all_displays = dotxpra.sockets()
                #ie: [("LIVE", ":100"), ("LIVE", ":200"), ...]
                displays = [v[1] for v in all_displays]
                display_name = None
                for x in range(1000, 20000):
                    v = ":%s" % x
                    if v not in displays:
                        display_name = v
                        break
                if not display_name:
                    error_cb("you must specify a free virtual display name to use with the proxy server")
            elif use_display:
                #only use automatic guess for xpra displays and not X11 displays:
                display_name = guess_xpra_display(opts.socket_dir, opts.socket_dirs)
            else:
                # We will try to find one automaticaly
                # Use the temporary magic value 'S' as marker:
                display_name = 'S' + str(os.getpid())

    if upgrading:
        assert display_name, "no display found to upgrade"
        if POSIX and not OSX and get_saved_env_var("DISPLAY", "")==display_name:
            warn("Warning: upgrading from an environment connected to the same display")
        #try to stop the existing server if it exists:
        dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
        sessions = get_xpra_sessions(dotxpra, ignore_state=(DotXpra.UNKNOWN, DotXpra.DEAD),
                                     matching_display=display_name, query=True)
        session = sessions.get(display_name)
        print("session(%s)=%s" % (display_name, session))
        if session:
            socket_path = session.get("socket-path")
            uri = ("socket://%s" % socket_path) if socket_path else display_name
            if request_exit(uri):
                #the server has terminated as we had requested
                use_display = True
                #but it may need a second to disconnect the clients
                #and then close the sockets cleanly
                #(so we can re-create them safely)
                import time
                time.sleep(1)
            else:
                warn("server for %s is not exiting" % display_name)

    if not (shadowing or proxying or upgrading) and opts.exit_with_children and not has_child_arg:
        error_cb("--exit-with-children specified without any children to spawn; exiting immediately")

    # Generate the script text now, because os.getcwd() will
    # change if/when we daemonize:
    from xpra.server.server_util import (
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
    if POSIX and getuid()!=0:
        env = os.environb.copy()
        oenv = parse_env(opts.env)
        for k,v in oenv.items():
            env[k.encode("utf8")] = v.encode("utf8")
        env_script = xpra_env_shell_script(opts.socket_dir, env)
        run_xpra_script = env_script + xpra_runner_shell_script(script_file, cwd)

    uid = int(opts.uid)
    gid = int(opts.gid)
    username = get_username_for_uid(uid)
    home = get_home_for_uid(uid)
    ROOT = POSIX and getuid()==0
    if POSIX and uid and not gid:
        #try harder to use a valid group,
        #since we're going to chown files:
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

    def write_session_file(filename, contents):
        return save_session_file(filename, contents, uid, gid)

    protected_fds = []
    protected_env = {}
    stdout = sys.stdout
    stderr = sys.stderr
    # Daemonize:
    if POSIX and opts.daemon:
        #daemonize will chdir to "/", so try to use an absolute path:
        if opts.password_file:
            opts.password_file = tuple(os.path.abspath(x) for x in opts.password_file)
        daemonize()

    displayfd = 0
    if POSIX and opts.displayfd:
        try:
            displayfd = int(opts.displayfd)
            if displayfd>0:
                protected_fds.append(displayfd)
        except ValueError as e:
            stderr.write("Error: invalid displayfd '%s':\n" % opts.displayfd)
            stderr.write(" %s\n" % e)
            del e

    clobber = int(upgrading)*CLOBBER_UPGRADE | int(use_display or 0)*CLOBBER_USE_DISPLAY
    start_vfb = not (shadowing or proxying or clobber)
    xauth_data = None
    if start_vfb:
        xauth_data = get_hex_uuid()

    # if pam is present, try to create a new session:
    pam = None
    PAM_OPEN = POSIX and envbool("XPRA_PAM_OPEN", ROOT and uid!=0)
    if PAM_OPEN:
        try:
            from xpra.server.pam import pam_session #@UnresolvedImport
        except ImportError as e:
            stderr.write("Error: failed to import pam module\n")
            stderr.write(" %s" % e)
            del e
            PAM_OPEN = False
    if PAM_OPEN:
        fdc = FDChangeCaptureContext()
        with fdc:
            pam = pam_session(username)
            env = {
                   #"XDG_SEAT"               : "seat1",
                   #"XDG_VTNR"               : "0",
                   "XDG_SESSION_TYPE"       : "x11",
                   #"XDG_SESSION_CLASS"      : "user",
                   "XDG_SESSION_DESKTOP"    : "xpra",
                   }
            #maybe we should just bail out instead?
            if pam.start():
                pam.set_env(env)
                items = {}
                if display_name.startswith(":"):
                    items["XDISPLAY"] = display_name
                if xauth_data:
                    items["XAUTHDATA"] = xauth_data
                pam.set_items(items)
                if pam.open():
                    #we can't close it, because we're not going to be root any more,
                    #but since we're the process leader for the session,
                    #terminating will also close the session
                    #atexit.register(pam.close)
                    protected_env = pam.get_envlist()
                    os.environ.update(protected_env)
        #closing the pam fd causes the session to be closed,
        #and we don't want that!
        protected_fds += fdc.get_new_fds()

    #get XDG_RUNTIME_DIR from env options,
    #which may not have updated os.environ yet when running as root with "--uid="
    xrd = os.path.abspath(parse_env(opts.env).get("XDG_RUNTIME_DIR", ""))
    if ROOT and (uid>0 or gid>0):
        #we're going to chown the directory if we create it,
        #ensure this cannot be abused, only use "safe" paths:
        if xrd=="/run/user/%i" % uid:
            pass    #OK!
        elif not any(True for x in ("/tmp", "/var/tmp") if xrd.startswith(x)):
            xrd = ""
        #these paths could cause problems if we were to create and chown them:
        elif xrd.startswith(X11_SOCKET_DIR) or xrd.startswith("/tmp/.XIM-unix"):
            xrd = ""
    if not xrd:
        xrd = os.environ.get("XDG_RUNTIME_DIR")
    xrd = create_runtime_dir(xrd, uid, gid)
    if xrd:
        #this may override the value we get from pam
        #with the value supplied by the user:
        protected_env["XDG_RUNTIME_DIR"] = xrd

    sanitize_env()
    os.environ.update(source_env(opts.source))
    if POSIX:
        if xrd:
            os.environ["XDG_RUNTIME_DIR"] = xrd
        if not OSX:
            os.environ["XDG_SESSION_TYPE"] = "x11"
        if not starting_desktop:
            os.environ["XDG_CURRENT_DESKTOP"] = opts.wm_name
    if display_name[0] != 'S':
        os.environ["DISPLAY"] = display_name
        if POSIX:
            os.environ["CKCON_X11_DISPLAY"] = display_name
    elif not start_vfb or opts.xvfb.find("Xephyr")<0:
        os.environ.pop("DISPLAY", None)
    os.environ.update(protected_env)

    session_dir = make_session_dir(mode, opts.sessions_dir, display_name, uid, gid)
    os.environ["XPRA_SESSION_DIR"] = session_dir
    #populate it:
    if run_xpra_script:
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        write_runner_shell_scripts(run_xpra_script)
    if env_script:
        write_session_file("server.env", env_script)
    write_session_file("cmdline", "\n".join(cmdline)+"\n")
    upgrading_seamless = upgrading_desktop = False
    if upgrading:
        #if we had saved the start / start-desktop config, reload it:
        mode = apply_config(opts, mode)
        upgrading_desktop = mode=="desktop"
        upgrading_seamless = not upgrading_desktop

    write_session_file("config", get_options_file_contents(opts, mode))

    extra_expand = {"TIMESTAMP" : datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}
    log_to_file = opts.daemon or os.environ.get("XPRA_LOG_TO_FILE", "")=="1"
    if start_vfb or log_to_file:
        #we will probably need a log dir
        #either for the vfb, or for our own log file
        log_dir = opts.log_dir or ""
        if not log_dir or log_dir.lower()=="auto":
            log_dir = session_dir
        #expose the log-dir as "XPRA_LOG_DIR",
        #this is used by Xdummy for the Xorg log file
        if "XPRA_LOG_DIR" not in os.environ:
            os.environ["XPRA_LOG_DIR"] = log_dir

    if log_to_file:
        log_filename0 = osexpand(select_log_file(log_dir, opts.log_file, display_name),
                                 username, uid, gid, extra_expand)
        if os.path.exists(log_filename0) and not display_name.startswith("S"):
            #don't overwrite the log file just yet,
            #as we may still fail to start
            log_filename0 += ".new"
        logfd = open_log_file(log_filename0)
        if POSIX:
            os.fchmod(logfd, 0o640)
            if ROOT and (uid>0 or gid>0):
                try:
                    os.fchown(logfd, uid, gid)
                except OSError as e:
                    noerr(stderr.write, "failed to chown the log file '%s'\n" % log_filename0)
                    noerr(stderr.flush)
        stdout, stderr = redirect_std_to_log(logfd, *protected_fds)
        noerr(stderr.write, "Entering daemon mode; "
                     + "any further errors will be reported to:\n"
                     + ("  %s\n" % log_filename0))
        noerr(stderr.flush)
        os.environ["XPRA_SERVER_LOG"] = log_filename0
    else:
        #server log does not exist:
        os.environ.pop("XPRA_SERVER_LOG", None)

    #warn early about this:
    if (starting or starting_desktop) and desktop_display and opts.notifications and not opts.dbus_launch:
        print_DE_warnings()

    if start_vfb and opts.xvfb.find("Xephyr")>=0 and opts.sync_xvfb<=0:
        warn("Warning: using Xephyr as vfb")
        warn(" you should also enable the sync-xvfb option")
        warn(" to keep the Xephyr window updated")

    if not (shadowing or starting_desktop or upgrading_desktop):
        opts.rfb_upgrade = 0
        if opts.bind_rfb:
            get_util_logger().warn("Warning: bind-rfb sockets cannot be used with '%s' mode" % mode)
            opts.bind_rfb = []

    progress(30, "creating sockets")
    from xpra.net.socket_util import get_network_logger, setup_local_sockets, create_sockets
    retry = 10*int(mode.startswith("upgrade"))
    sockets = create_sockets(opts, error_cb, retry=retry)

    from xpra.log import Logger
    log = Logger("server")
    log("env=%s", os.environ)

    if POSIX and starting_desktop and not use_display and DESKTOP_GREETER:
        #if there are no start commands, auto-add a greeter:
        commands = []
        for start_prop in (
            "start", "start-late",
            "start-child","start-child-late",
            "start-after-connect", "start-child-after-connect",
            "start-on-connect", "start-child-on-connect",
            "start-on-last-client-exit", "start-child-on-last-client-exit",
            ):
            commands += list(getattr(opts, start_prop.replace("-", "_")))
        if not commands:
            opts.start.append("xpra desktop-greeter")
    if POSIX and configure_imsettings_env(opts.input_method)=="ibus" and not (upgrading or shadowing or proxying):
        #start ibus-daemon unless already specified in 'start':
        if IBUS_DAEMON_COMMAND and not (
            any(x.find("ibus-daemon")>=0 for x in opts.start) or any(x.find("ibus-daemon")>=0 for x in opts.start_late)
            ):
            log("adding ibus-daemon to late startup")
            opts.start_late.insert(0, IBUS_DAEMON_COMMAND)

    # Start the Xvfb server first to get the display_name if needed
    odisplay_name = display_name
    xvfb = None
    xauthority = None
    if start_vfb or clobber:
        #XAUTHORITY
        from xpra.x11.vfb_util import (
            start_Xvfb, check_xvfb_process, parse_resolution,
            get_xauthority_path,
            xauth_add,
            )
        xauthority = load_session_file("xauthority")
        if xauthority and os.path.exists(xauthority):
            os.environ["XAUTHORITY"] = xauthority.decode("latin1")
            log("found existing XAUTHORITY file '%s'", xauthority)
        else:
            xauthority = get_xauthority_path(display_name, username, uid, gid)
            os.environ["XAUTHORITY"] = xauthority
            if not os.path.exists(xauthority):
                log("creating XAUTHORITY file '%s'", xauthority)
                try:
                    with open(xauthority, "a") as f:
                        os.fchmod(f.fileno(), 0o640)
                        if ROOT and (uid!=0 or gid!=0):
                            os.fchown(f.fileno(), uid, gid)
                except Exception as e:
                    #trying to continue anyway!
                    log.error("Error trying to create XAUTHORITY file %s:", xauthority)
                    log.error(" %s", e)
            else:
                log("found existing XAUTHORITY file '%s'", xauthority)
        write_session_file("xauthority", xauthority)
        #resolve use-display='auto':
        if use_display is None or upgrading:
            #figure out if we have to start the vfb or not:
            if not display_name:
                if upgrading:
                    error_cb("no displays found to upgrade")
                use_display = False
            else:
                progress(40, "connecting to the display")
                display_no = int(display_name[1:])
                stat = stat_X11_display(display_no)
                log("stat_X11_display(%i)=%s", display_no, stat)
                if not stat:
                    if upgrading:
                        error_cb("cannot access display '%s'" % (display_name,))
                    #no X11 socket to connect to, so we have to start one:
                    start_vfb = True
                elif verify_display(None, display_name, log_errors=False, timeout=1)==0:
                    #accessed OK:
                    start_vfb = False
                    #we have already loaded gtk in 'verify_display':
                    bypass_no_gtk()
                else:
                    #verify failed but we can stat the X11 server socket...
                    #perhaps we need to re-add an xauth entry
                    if not xauth_data:
                        xauth_data = get_hex_uuid()
                        if pam:
                            pam.set_items({"XAUTHDATA" : xauth_data})
                    xauth_add(xauthority, display_name, xauth_data, uid, gid)
                    if verify_display(None, display_name, log_errors=False, timeout=1)!=0:
                        warn("display %s is not accessible" % (display_name,))
                    else:
                        #now OK!
                        start_vfb = False
    xvfb_pid = 0
    devices = {}
    if POSIX and not OSX:
        from xpra.server.server_util import has_uinput, UINPUT_UUID_LEN
        uinput_uuid = None
        use_uinput = has_uinput() and opts.input_devices.lower() in ("uinput", "auto") and not shadowing
        if start_vfb:
            progress(40, "starting a virtual display")
            assert not proxying and xauth_data
            pixel_depth = validate_pixel_depth(opts.pixel_depth, starting_desktop)
            if use_uinput:
                uinput_uuid = get_rand_chars(UINPUT_UUID_LEN)
                write_session_file("uinput-uuid", uinput_uuid)
            vfb_geom = ""
            try:
                vfb_geom = parse_resolution(opts.resize_display)
            except Exception:
                pass

            xvfb, display_name = start_Xvfb(opts.xvfb, vfb_geom, pixel_depth, display_name, cwd,
                                                      uid, gid, username, uinput_uuid)
            xauth_add(xauthority, display_name, xauth_data, uid, gid)
            xvfb_pid = xvfb.pid
            xvfb_pidfile = write_session_file("xvfb.pid", "%s" % xvfb.pid)
            def xvfb_terminated():
                log("xvfb_terminated() removing %s", xvfb_pidfile)
                if xvfb_pidfile:
                    os.unlink(xvfb_pidfile)
            getChildReaper().add_process(xvfb, "xvfb", opts.xvfb, ignore=True, callback=xvfb_terminated)
            #always update as we may now have the "real" display name:
            os.environ["DISPLAY"] = display_name
            os.environ["CKCON_X11_DISPLAY"] = display_name
            os.environ.update(protected_env)
            if display_name!=odisplay_name:
                #update with the real display value:
                if pam:
                    pam.set_items({"XDISPLAY" : display_name})
                if session_dir:
                    new_session_dir = get_session_dir(mode, opts.sessions_dir, display_name, uid)
                    if new_session_dir!=session_dir:
                        try:
                            if os.path.exists(new_session_dir):
                                for x in os.listdir(session_dir):
                                    os.rename(os.path.join(session_dir, x), os.path.join(new_session_dir, x))
                                os.rmdir(session_dir)
                            else:
                                os.rename(session_dir, new_session_dir)
                        except OSError as e:
                            log.error("Error moving the session directory")
                            log.error(" from '%s' to '%s'", session_dir, new_session_dir)
                            log.error(" %s", e)
                        session_dir = new_session_dir
                        #update session dir if needed:
                        if not opts.log_dir or opts.log_dir.lower()=="auto":
                            log_dir = session_dir
                        os.environ["XPRA_SESSION_DIR"] = new_session_dir
        elif POSIX and not OSX and not shadowing and not proxying:
            try:
                xvfb_pid = int(load_session_file("xvfb.pid") or 0)
            except ValueError:
                pass
            if use_uinput:
                uinput_uuid = load_session_file("uinput-uuid")
        if uinput_uuid:
            devices = create_input_devices(uinput_uuid, uid)

    def check_xvfb(timeout=0):
        if xvfb is None:
            return True
        if not check_xvfb_process(xvfb, timeout=timeout, command=opts.xvfb):
            progress(100, "xvfb failed")
            return False
        return True

    write_displayfd(display_name, displayfd)

    if not check_xvfb(1):
        noerr(stderr.write, "vfb failed to start, exiting\n")
        return EXIT_VFB_ERROR

    if WIN32 and os.environ.get("XPRA_LOG_FILENAME"):
        os.environ["XPRA_SERVER_LOG"] = os.environ["XPRA_LOG_FILENAME"]
    if opts.daemon:
        if odisplay_name!=display_name:
            #this may be used by scripts, let's try not to change it:
            noerr(stderr.write, "Actual display used: %s\n" % display_name)
            noerr(stderr.flush)
        log_filename1 = osexpand(select_log_file(log_dir, opts.log_file, display_name),
                                 username, uid, gid, extra_expand)
        if log_filename0 != log_filename1:
            if not os.path.exists(log_filename0) and os.path.exists(log_filename1) and log_filename1.startswith(session_dir):
                #the session dir was renamed with the log file inside it,
                #so we don't need to rename the log file
                pass
            else:
                # we now have the correct log filename, so use it:
                try:
                    os.rename(log_filename0, log_filename1)
                except (OSError, IOError):
                    pass
            os.environ["XPRA_SERVER_LOG"] = log_filename1
            noerr(stderr.write, "Actual log file name is now: %s\n" % log_filename1)
            noerr(stderr.flush)
        noerr(stdout.close)
        noerr(stderr.close)
    #we should not be using stdout or stderr from this point on:
    del stdout
    del stderr

    if not check_xvfb():
        noerr(stderr.write, "vfb failed to start, exiting\n")
        return EXIT_VFB_ERROR

    if ROOT and (uid!=0 or gid!=0):
        log("root: switching to uid=%i, gid=%i", uid, gid)
        setuidgid(uid, gid)
        os.environ.update({
            "HOME"      : home,
            "USER"      : username,
            "LOGNAME"   : username,
            })
        shell = get_shell_for_uid(uid)
        if shell:
            os.environ["SHELL"] = shell
        #now we've changed uid, it is safe to honour all the env updates:
        configure_env(opts.env)
        os.environ.update(protected_env)

    if opts.chdir:
        log("chdir(%s)", opts.chdir)
        os.chdir(opts.chdir)

    dbus_pid, dbus_env = 0, {}
    if not shadowing and POSIX and not OSX:
        dbuslog = Logger("dbus")
        dbus_pid, dbus_env = reload_dbus_attributes(display_name)
        if not dbus_pid and dbus_env:
            no_gtk()
            assert starting or starting_desktop or proxying
            try:
                from xpra.server.dbus.dbus_start import start_dbus
            except ImportError as e:
                dbuslog("dbus components are not installed: %s", e)
            else:
                dbus_pid, dbus_env = start_dbus(opts.dbus_launch)
                if dbus_env:
                    dbuslog("started new dbus instance: %s", dbus_env)
                    write_session_file("dbus.pid", "%s" % dbus_pid)
                    dbus_env_data = b"\n".join(b"%s=%s" % (k, v) for k,v in dbus_env.items())+b"\n"
                    write_session_file("dbus.env", dbus_env_data)
        if dbus_env:
            os.environb.update(dbus_env)

    if not proxying:
        if POSIX and not OSX:
            no_gtk()
            if starting or starting_desktop or shadowing:
                r = verify_display(xvfb, display_name, shadowing)
                if r:
                    return r
        #on win32, this ensures that we get the correct screen size to shadow:
        from xpra.platform.gui import init as gui_init
        log("gui_init()")
        gui_init()

    def init_local_sockets():
        progress(60, "initializing local sockets")
        #setup unix domain socket:
        netlog = get_network_logger()
        local_sockets = setup_local_sockets(opts.bind,
                                            opts.socket_dir, opts.socket_dirs,
                                            display_name, clobber,
                                            opts.mmap_group, opts.socket_permissions,
                                            username, uid, gid)
        netlog("setting up local sockets: %s", local_sockets)
        sockets.update(local_sockets)
        if POSIX and (starting or upgrading or starting_desktop):
            #all unix domain sockets:
            ud_paths = [sockpath for stype, _, sockpath, _ in local_sockets if stype=="unix-domain"]
            if ud_paths:
                #choose one so our xdg-open override script can use to talk back to us:
                if opts.forward_xdg_open:
                    for x in ("/usr/libexec/xpra", "/usr/lib/xpra"):
                        xdg_override = os.path.join(x, "xdg-open")
                        if os.path.exists(xdg_override):
                            os.environ["PATH"] = x+os.pathsep+os.environ.get("PATH", "")
                            os.environ["XPRA_SERVER_SOCKET"] = ud_paths[0]
                            break
            else:
                log.warn("Warning: no local server sockets,")
                if opts.forward_xdg_open:
                    log.warn(" forward-xdg-open cannot be enabled")
                log.warn(" non-embedded ssh connections will not be available")

    set_server_features(opts)

    if not proxying and POSIX and not OSX:
        if not check_xvfb():
            return  1
        from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
        if os.environ.get("NO_AT_BRIDGE") is None:
            os.environ["NO_AT_BRIDGE"] = "1"
        init_gdk_display_source()

        if not xvfb_pid:
            #perhaps this is an upgrade from an older version?
            #try harder to find the pid:
            def _get_int(prop):
                from xpra.gtk_common.gtk_util import get_default_root_window
                from xpra.x11.gtk_x11.prop import prop_get
                try:
                    return prop_get(get_default_root_window(), prop, "u32")
                except Exception:
                    return None
            xvfb_pid = _get_int(b"XPRA_XVFB_PID") or _get_int(b"_XPRA_SERVER_PID")

    progress(80, "initializing server")
    if shadowing:
        app = make_shadow_server()
    elif proxying:
        app = make_proxy_server()
    else:
        if starting or upgrading_seamless:
            app = make_server(clobber)
        else:
            assert starting_desktop or upgrading_desktop
            app = make_desktop_server()
        app.init_virtual_devices(devices)

    def server_not_started(msg="server not started"):
        progress(100, msg)
        #check the initial 'mode' value instead of "upgrading" or "upgrading_desktop"
        #as we may have switched to "starting=True"
        #if the existing server has exited as we requested)
        if mode.startswith("upgrade") or use_display:
            #something abnormal occurred,
            #don't kill the vfb on exit:
            from xpra.server import EXITING_CODE
            app._upgrading = EXITING_CODE
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
        app.init_dbus(dbus_pid, dbus_env)
        if not shadowing and not proxying:
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
        return EXIT_OK
    except InitExit as e:
        for m in str(e).split("\n"):
            log.info("%s", m)
        server_not_started(str(e))
        return e.status
    except InitException as e:
        log("%s failed to start", app, exc_info=True)
        log.error("xpra server initialization error:")
        for m in str(e).split("\n"):
            log.info(" %s", m)
        server_not_started(str(e))
        return EXIT_FAILURE
    except Exception as e:
        log.error("Error: cannot start the %s server", app.session_type, exc_info=True)
        log.error(str(e))
        log.info("")
        server_not_started(str(e))
        return EXIT_FAILURE

    ######################################################################
    if opts.attach is True:
        attach_client(opts, defaults)
    del opts

    try:
        progress(100, "running")
        log("%s()", app.run)
        r = app.run()
        log("%s()=%s", app.run, r)
    except KeyboardInterrupt:
        log.info("stopping on KeyboardInterrupt")
        app.cleanup()
        r = EXIT_OK
    except Exception:
        log.error("server error", exc_info=True)
        app.cleanup()
        r = -128
    else:
        if r>0:
            r = 0
    return r

def attach_client(options, defaults):
    from xpra.platform.paths import get_xpra_command
    cmd = get_xpra_command()+["attach"]
    display_name = os.environ.get("DISPLAY")
    if display_name:
        cmd += [display_name]
    #options has been "fixed up", make sure this has too:
    fixup_options(defaults)
    for x in CLIENT_OPTIONS:
        f = x.replace("-", "_")
        try:
            d = getattr(defaults, f)
            c = getattr(options, f)
        except Exception as e:
            print("error on %s: %s" % (f, e))
            continue
        if c!=d:
            if OPTION_TYPES.get(x)==list:
                v = ",".join(str(i) for i in x)
            else:
                v = str(c)
            cmd.append("--%s=%s" % (x, v))
    env = get_saved_env()
    proc = Popen(cmd, env=env, start_new_session=POSIX and not OSX)
    getChildReaper().add_process(proc, "client-attach", cmd, ignore=True, forget=False)
