# This file is part of Xpra.
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# DO NOT IMPORT GTK HERE: see
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000041.html
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000042.html
# (also do not import anything that imports gtk)
import subprocess
import sys
import os.path
import atexit
import signal
import socket
import traceback

from xpra.scripts.main import warn, no_gtk, validate_encryption
from xpra.scripts.config import InitException, TRUE_OPTIONS, FALSE_OPTIONS
from xpra.os_util import SIGNAMES, close_fds, get_ssh_port, get_username_for_uid, get_home_for_uid, getuid, getgid, setuidgid, WIN32, OSX
from xpra.util import envbool
from xpra.platform.dotxpra import DotXpra


_cleanups = []
def run_cleanups():
    global _cleanups
    cleanups = _cleanups
    _cleanups = []
    for c in cleanups:
        try:
            c()
        except:
            print("error running cleanup %s" % c)
            traceback.print_exception(*sys.exc_info())

_when_ready = []

def add_when_ready(f):
    _when_ready.append(f)

def add_cleanup(f):
    _cleanups.append(f)


def deadly_signal(signum, frame):
    from xpra.scripts.main import info
    info("got deadly signal %s, exiting\n" % SIGNAMES.get(signum, signum))
    run_cleanups()
    # This works fine in tests, but for some reason if I use it here, then I
    # get bizarre behavior where the signal handler runs, and then I get a
    # KeyboardException (?!?), and the KeyboardException is handled normally
    # and exits the program (causing the cleanup handlers to be run again):
    #signal.signal(signum, signal.SIG_DFL)
    #kill(os.getpid(), signum)
    os._exit(128 + signum)


def _save_int(prop_name, pid):
    import gtk
    from xpra.x11.gtk_x11.prop import prop_set
    prop_set(gtk.gdk.get_default_root_window(), prop_name, "u32", pid)

def _get_int(prop_name):
    import gtk
    from xpra.x11.gtk_x11.prop import prop_get
    return prop_get(gtk.gdk.get_default_root_window(), prop_name, "u32")

def _save_str(prop_name, s):
    import gtk
    from xpra.x11.gtk_x11.prop import prop_set
    prop_set(gtk.gdk.get_default_root_window(), prop_name, "latin1", s.decode("latin1"))

def _get_str(prop_name):
    import gtk
    from xpra.x11.gtk_x11.prop import prop_get
    v = prop_get(gtk.gdk.get_default_root_window(), prop_name, "latin1")
    if v is not None:
        return v.encode("latin1")
    return v

def save_xvfb_pid(pid):
    _save_int("_XPRA_SERVER_PID", pid)

def get_xvfb_pid():
    return _get_int("_XPRA_SERVER_PID")

def save_dbus_pid(pid):
    _save_int("_XPRA_DBUS_PID", pid)

def get_dbus_pid():
    return _get_int("_XPRA_DBUS_PID")

def get_dbus_env():
    env = {}
    for n,load in (
            ("ADDRESS",     _get_str),
            ("PID",         _get_int),
            ("WINDOW_ID",   _get_int)):
        k = "DBUS_SESSION_BUS_%s" % n
        try:
            v = load(k)
            if v:
                env[k] = str(v)
        except Exception as e:
            sys.stderr.write("failed to load dbus environment variable '%s':\n" % k)
            sys.stderr.write(" %s\n" % e)
    return env

def save_dbus_env(env):
    #DBUS_SESSION_BUS_ADDRESS=unix:abstract=/tmp/dbus-B8CDeWmam9,guid=b77f682bd8b57a5cc02f870556cbe9e9
    #DBUS_SESSION_BUS_PID=11406
    #DBUS_SESSION_BUS_WINDOWID=50331649
    for n,conv,save in (
            ("ADDRESS",     str,    _save_str),
            ("PID",         int,    _save_int),
            ("WINDOW_ID",   int,    _save_int)):
        k = "DBUS_SESSION_BUS_%s" % n
        v = env.get(k)
        if v is None:
            continue
        try:
            tv = conv(v)
            save(k, tv)
        except Exception as e:
            sys.stderr.write("failed to save dbus environment variable '%s' with value '%s':\n" % (k, v))
            sys.stderr.write(" %s\n" % e)


def validate_pixel_depth(pixel_depth, starting_desktop=False):
    try:
        pixel_depth = int(pixel_depth)
    except ValueError:
        raise InitException("invalid value '%s' for pixel depth, must be a number" % pixel_depth)
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
        if dno>=0 and dno<10:
            sys.stderr.write("WARNING: low display number: %s\n" % dno)
            sys.stderr.write("You are attempting to run the xpra server against what seems to be a default X11 display '%s'.\n" % display_name)
            sys.stderr.write("This is generally not what you want.\n")
            sys.stderr.write("You should probably use a higher display number just to avoid any confusion (and also this warning message).\n")
    except:
        pass


def sanitize_env():
    def unsetenv(*varnames):
        for x in varnames:
            if x in os.environ:
                del os.environ[x]
    #we don't want client apps to think these mean anything:
    #(if set, they belong to the desktop the server was started from)
    #TODO: simply whitelisting the env would be safer/better
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
             #"XDG_RUNTIME_DIR",
             "QT_GRAPHICSSYSTEM_CHECKED",
             )
    os.environ["XDG_SESSION_TYPE"] = "x11"

def configure_imsettings_env(input_method):
    im = (input_method or "").lower()
    if im in ("none", "no"):
        #the default: set DISABLE_IMSETTINGS=1, fallback to xim
        #that's because the 'ibus' 'immodule' breaks keyboard handling
        #unless its daemon is also running - and we don't know if it is..
        imsettings_env(True, "xim", "xim", "none", "@im=none")
    elif im=="keep":
        #do nothing and keep whatever is already set, hoping for the best
        pass
    elif im in ("xim", "IBus", "SCIM", "uim"):
        #ie: (False, "ibus", "ibus", "IBus", "@im=ibus")
        imsettings_env(True, im.lower(), im.lower(), im, "@im=%s" % im.lower())
    else:
        v = imsettings_env(True, im.lower(), im.lower(), im, "@im=%s" % im.lower())
        warn("using input method settings: %s" % str(v))
        warn("unknown input method specified: %s" % input_method)
        warn(" if it is correct, you may want to file a bug to get it recognized")

def imsettings_env(disabled, gtk_im_module, qt_im_module, imsettings_module, xmodifiers):
    #for more information, see imsettings:
    #https://code.google.com/p/imsettings/source/browse/trunk/README
    if disabled is True:
        os.environ["DISABLE_IMSETTINGS"] = "1"                  #this should override any XSETTINGS too
    elif disabled is False and ("DISABLE_IMSETTINGS" in os.environ):
        del os.environ["DISABLE_IMSETTINGS"]
    v = {
         "GTK_IM_MODULE"      : gtk_im_module,            #or "gtk-im-context-simple"?
         "QT_IM_MODULE"       : qt_im_module,             #or "simple"?
         "IMSETTINGS_MODULE"  : imsettings_module,        #or "xim"?
         "XMODIFIERS"         : xmodifiers,
         #not really sure what to do with those:
         #"IMSETTINGS_DISABLE_DESKTOP_CHECK"   : "true",   #
         #"IMSETTINGS_INTEGRATE_DESKTOP" : "no"}           #we're not a real desktop
        }
    os.environ.update(v)
    return v


def guess_xpra_display(socket_dir, socket_dirs):
    dotxpra = DotXpra(socket_dir, socket_dirs)
    results = dotxpra.sockets()
    live = [display for state, display in results if state==DotXpra.LIVE]
    if len(live)==0:
        raise InitException("no existing xpra servers found")
    if len(live)>1:
        raise InitException("too many existing xpra servers found, cannot guess which one to use")
    return live[0]


def start_dbus(dbus_launch):
    if not dbus_launch or dbus_launch.lower() in FALSE_OPTIONS:
        return 0, {}
    try:
        def preexec():
            assert os.name=="posix"
            os.setsid()
            close_fds()
        proc = subprocess.Popen(dbus_launch, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=True, preexec_fn=preexec)
        out,_ = proc.communicate()
        assert proc.poll()==0, "exit code is %s" % proc.poll()
        #parse and add to global env:
        dbus_env = {}
        for l in out.splitlines():
            parts = l.split("=", 1)
            if len(parts)!=2:
                continue
            k,v = parts
            if v.startswith("'") and v.endswith("';"):
                v = v[1:-2]
            dbus_env[k] = v
        dbus_pid = int(dbus_env.get("DBUS_SESSION_BUS_PID", 0))
        return dbus_pid, dbus_env
    except Exception as e:
        sys.stderr.write("dbus-launch failed to start using command '%s':\n" % dbus_launch)
        sys.stderr.write(" %s\n" % e)
        return 0, {}


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
        x.logger.setLevel(logging.WARN)
    from xpra.server.server_base import ServerBase
    sb = ServerBase()
    sb.init_options(opts)
    from xpra.codecs.loader import PREFERED_ENCODING_ORDER, HELP_ORDER
    if "help" in opts.encodings:
        sb.allowed_encodings = PREFERED_ENCODING_ORDER
    from xpra.codecs.video_helper import getVideoHelper
    getVideoHelper().init()
    sb.init_encodings()
    from xpra.codecs.loader import encoding_help
    for e in (x for x in HELP_ORDER if x in sb.encodings):
        print(" * %s" % encoding_help(e))
    return 0


def run_server(error_cb, opts, mode, xpra_file, extra_args, desktop_display=None):
    try:
        cwd = os.getcwd()
    except:
        cwd = os.path.expanduser("~")
        sys.stderr.write("current working directory does not exist, using '%s'\n" % cwd)
    validate_encryption(opts)
    if opts.encoding=="help" or "help" in opts.encodings:
        return show_encoding_help(opts)

    from xpra.server.socket_util import parse_bind_tcp, parse_bind_vsock
    bind_tcp = parse_bind_tcp(opts.bind_tcp)
    bind_ssl = parse_bind_tcp(opts.bind_ssl)
    bind_vsock = parse_bind_vsock(opts.bind_vsock)

    assert mode in ("start", "start-desktop", "upgrade", "shadow", "proxy")
    starting  = mode == "start"
    starting_desktop = mode == "start-desktop"
    upgrading = mode == "upgrade"
    shadowing = mode == "shadow"
    proxying  = mode == "proxy"
    clobber   = upgrading or opts.use_display
    start_vfb = not shadowing and not proxying and not clobber

    if upgrading or shadowing:
        #there should already be one running
        opts.pulseaudio = False

    #get the display name:
    if shadowing and len(extra_args)==0:
        if WIN32 or OSX:
            #just a virtual name for the only display available:
            display_name = ":0"
        else:
            from xpra.scripts.main import guess_X11_display
            dotxpra = DotXpra(opts.socket_dir, opts.socket_dirs)
            display_name = guess_X11_display(dotxpra)
    elif upgrading and len(extra_args)==0:
        display_name = guess_xpra_display(opts.socket_dir, opts.socket_dirs)
    else:
        if len(extra_args) > 1:
            error_cb("too many extra arguments (%i): only expected a display number" % len(extra_args))
        if len(extra_args) == 1:
            display_name = extra_args[0]
            if not shadowing and not proxying:
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
            elif opts.use_display:
                #only use automatic guess for xpra displays and not X11 displays:
                display_name = guess_xpra_display(opts.socket_dir, opts.socket_dirs)
            else:
                # We will try to find one automaticaly
                # Use the temporary magic value 'S' as marker:
                display_name = 'S' + str(os.getpid())

    if not shadowing and not proxying and not upgrading and opts.exit_with_children and not opts.start_child:
        error_cb("--exit-with-children specified without any children to spawn; exiting immediately")

    atexit.register(run_cleanups)

    # Generate the script text now, because os.getcwd() will
    # change if/when we daemonize:
    from xpra.server.server_util import xpra_runner_shell_script, write_runner_shell_scripts, pam_open, write_pidfile, find_log_dir 
    script = xpra_runner_shell_script(xpra_file, cwd, opts.socket_dir)

    uid = int(opts.uid)
    gid = int(opts.gid)
    username = get_username_for_uid(uid)
    home = get_home_for_uid(uid)
    def fchown(fd):
        if os.name=="posix" and uid!=getuid() or gid!=getgid():
            try:
                os.fchown(fd, uid, gid)
            except:
                pass

    if start_vfb or opts.daemon:
        #we will probably need a log dir
        #either for the vfb, or for our own log file
        log_dir = opts.log_dir or ""
        if not log_dir or log_dir.lower()=="auto":
            log_dir = find_log_dir(username, uid=uid, gid=gid)
            if not log_dir:
                raise InitException("cannot find or create a logging directory")
        #expose the log-dir as "XPRA_LOG_DIR",
        #this is used by Xdummy for the Xorg log file
        if "XPRA_LOG_DIR" not in os.environ:
            os.environ["XPRA_LOG_DIR"] = log_dir
    stdout = sys.stdout
    stderr = sys.stderr
    # Daemonize:
    if opts.daemon:
        from xpra.server.server_util import select_log_file, open_log_file, daemonize
        #daemonize will chdir to "/", so try to use an absolute path:
        if opts.password_file:
            opts.password_file = os.path.abspath(opts.password_file)
        # At this point we may not know the display name,
        # so log_filename0 may point to a temporary file which we will rename later
        log_filename0 = select_log_file(log_dir, opts.log_file, display_name)
        logfd = open_log_file(log_filename0)
        fchown(logfd)
        assert logfd > 2
        stdout, stderr = daemonize(logfd)
        try:
            stderr.write("Entering daemon mode; "
                 + "any further errors will be reported to:\n"
                 + ("  %s\n" % log_filename0))
        except:
            #this can happen if stderr is closed by the caller already
            pass

    if opts.pidfile:
        write_pidfile(opts.pidfile, withfd=fchown)

    if os.name=="posix":
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        write_runner_shell_scripts(script, withfd=fchown)

    from xpra.log import Logger
    log = Logger("server")
    #warn early about this:
    if (starting or starting_desktop) and desktop_display:
        de = os.environ.get("XDG_SESSION_DESKTOP") or os.environ.get("SESSION_DESKTOP")
        if de:
            warnings = []
            if opts.pulseaudio is not False:
                try:
                    xprop = subprocess.Popen(["xprop", "-root", "-display", desktop_display], stdout=subprocess.PIPE)
                    out,_ = xprop.communicate()
                    for x in out.splitlines():
                        if x.startswith("PULSE_SERVER"):
                            #found an existing pulseaudio server
                            warnings.append("pulseaudio")
                            break
                except:
                    pass    #don't care, this is just to decide if we show an informative warning or not
            if opts.notifications and not opts.dbus_launch:
                warnings.append("notifications")
            if warnings:
                log.warn("Warning: xpra start from an existing '%s' desktop session", de)
                log.warn(" %s forwarding may not work", " ".join(warnings))
                log.warn(" try using a clean environment, a dedicated user,")
                log.warn(" or turn off %s", " and ".join(warnings))

    mdns_recs = []
    sockets = []

    #SSL sockets:
    wrap_socket_fn = None
    need_ssl = False
    ssl_opt = opts.ssl.lower()
    if ssl_opt in TRUE_OPTIONS or bind_ssl:
        need_ssl = True
    if opts.bind_tcp:
        if ssl_opt=="auto" and opts.ssl_cert:
            need_ssl = True
        elif ssl_opt=="tcp":
            need_ssl = True
        elif ssl_opt=="www":
            need_ssl = True
    if need_ssl:
        from xpra.scripts.main import ssl_wrap_socket_fn
        try:
            wrap_socket_fn = ssl_wrap_socket_fn(opts, server_side=True)
        except Exception as e:
            raise InitException("cannot create SSL socket (check your certificate paths): %s" % e)

    from xpra.server.socket_util import setup_tcp_socket, setup_vsock_socket, setup_local_sockets
    for host, iport in bind_ssl:
        _, tcp_socket, host_port = setup_tcp_socket(host, iport, "SSL")
        socket = ("SSL", wrap_socket_fn(tcp_socket), host_port)
        sockets.append(socket)
        if opts.mdns:
            rec = "ssl", [(host, iport)]
            mdns_recs.append(rec)

    # Initialize the TCP sockets before the display,
    # That way, errors won't make us kill the Xvfb
    # (which may not be ours to kill at that point)
    for host, iport in bind_tcp:
        socket = setup_tcp_socket(host, iport)
        sockets.append(socket)
        if opts.mdns:
            rec = "tcp", [(host, iport)]
            mdns_recs.append(rec)
            if ssl_opt in TRUE_OPTIONS or (ssl_opt=="auto" and opts.ssl_cert):
                #SSL is also available on this TCP socket:
                rec = "ssl", [(host, iport)]
                mdns_recs.append(rec)

    # VSOCK:
    for cid, iport in bind_vsock:
        socket = setup_vsock_socket(cid, iport)
        sockets.append(socket)
        if opts.mdns:
            rec = "vsock", [("", iport)]
            mdns_recs.append(rec)

    # Do this after writing out the shell script:
    if display_name[0] != 'S':
        os.environ["DISPLAY"] = display_name
    else:
        try:
            del os.environ["DISPLAY"]
        except:
            pass
    sanitize_env()
    os.environ["XDG_CURRENT_DESKTOP"] = opts.wm_name
    configure_imsettings_env(opts.input_method)

    # Start the Xvfb server first to get the display_name if needed
    from xpra.server.vfb_util import start_Xvfb, check_xvfb_process, verify_display_ready, verify_gdk_display, set_initial_resolution
    odisplay_name = display_name
    xvfb = None
    xvfb_pid = None
    xauth_data = None
    if start_vfb:
        assert not proxying
        pixel_depth = validate_pixel_depth(opts.pixel_depth)
        xvfb, display_name, xauth_data = start_Xvfb(opts.xvfb, pixel_depth, display_name, cwd, uid, gid)
        xvfb_pid = xvfb.pid
        #always update as we may now have the "real" display name:
        os.environ["DISPLAY"] = display_name

    close_display = None
    if not proxying:
        def close_display():
            # Close our display(s) first, so the server dying won't kill us.
            # (if gtk has been loaded)
            gtk_mod = sys.modules.get("gtk")
            if gtk_mod:
                for d in gtk_mod.gdk.display_manager_get().list_displays():
                    d.close()
            if xvfb_pid:
                log.info("killing xvfb with pid %s", xvfb_pid)
                try:
                    os.kill(xvfb_pid, signal.SIGTERM)
                except OSError as e:
                    log.info("failed to kill xvfb process with pid %s:", xvfb_pid)
                    log.info(" %s", e)
        _cleanups.append(close_display)

    # if pam is present, try to create a new session:
    PAM_OPEN = os.name=="posix" and envbool("XPRA_PAM_OPEN", os.getuid()==0 and os.getuid()!=uid)
    if PAM_OPEN:
        pam_open(display_name, xauth_data)

    if opts.daemon:
        def noerr(fn, *args):
            try:
                fn(*args)
            except:
                pass
        log_filename1 = select_log_file(log_dir, opts.log_file, display_name)
        if log_filename0 != log_filename1:
            # we now have the correct log filename, so use it:
            os.rename(log_filename0, log_filename1)
            if odisplay_name!=display_name:
                #this may be used by scripts, let's try not to change it:
                noerr(stderr.write, "Actual display used: %s\n" % display_name)
            noerr(stderr.write, "Actual log file name is now: %s\n" % log_filename1)
            noerr(stderr.flush)
        noerr(stdout.close)
        noerr(stderr.close)

    if not check_xvfb_process(xvfb):
        #xvfb problem: exit now
        return  1

    if os.name=="posix" and getuid()==0 and (uid!=0 or gid!=0):
        setuidgid(uid, gid)
        os.environ.update({
            "HOME"      : home,
            "USER"      : username,
            "LOGNAME"   : username,
            })

    display = None
    if not proxying:
        no_gtk()
        if os.name=="posix" and starting or starting_desktop:
            #check that we can access the X11 display:
            if not verify_display_ready(xvfb, display_name, shadowing):
                return 1
            display = verify_gdk_display(display_name)
            if not display:
                return 1
            import gtk          #@Reimport
            assert gtk
        #on win32, this ensures that we get the correct screen size to shadow:
        from xpra.platform.gui import init as gui_init
        gui_init()

    #setup unix domain socket:
    if not opts.socket_dir and not opts.socket_dirs:
        #we always need at least one valid socket dir
        from xpra.platform.paths import get_socket_dirs
        opts.socket_dirs = get_socket_dirs()
    local_sockets = setup_local_sockets(opts.bind, opts.socket_dir, opts.socket_dirs, display_name, clobber, opts.mmap_group, opts.socket_permissions, username, uid, gid)
    for socket, cleanup_socket in local_sockets:
        #ie: ("unix-domain", sock, sockpath), cleanup_socket
        sockets.append(socket)
        _cleanups.append(cleanup_socket)
        if opts.mdns:
            ssh_port = get_ssh_port()
            rec = "ssh", [("", ssh_port)]
            if ssh_port and rec not in mdns_recs:
                mdns_recs.append(rec)

    kill_dbus = None
    if shadowing:
        from xpra.platform.shadow_server import ShadowServer
        app = ShadowServer()
        info = "shadow"
    elif proxying:
        from xpra.server.proxy.proxy_server import ProxyServer
        app = ProxyServer()
        info = "proxy"
    else:
        assert starting or starting_desktop or upgrading
        from xpra.x11.gtk2 import gdk_display_source
        assert gdk_display_source
        #(now we can access the X11 server)

        if clobber:
            #get the saved pids and env
            dbus_pid = get_dbus_pid()
            dbus_env = get_dbus_env()
        else:
            assert starting or starting_desktop
            if xvfb_pid is not None:
                #save the new pid (we should have one):
                save_xvfb_pid(xvfb_pid)
            if os.name=="posix" and opts.dbus_launch:
                #start a dbus server:
                dbus_pid = 0
                dbus_env = {}
                def kill_dbus():
                    log("kill_dbus: dbus_pid=%s" % dbus_pid)
                    if dbus_pid<=0:
                        return
                    try:
                        os.kill(dbus_pid, signal.SIGINT)
                    except Exception as e:
                        log.warn("Warning: error trying to stop dbus with pid %i:", dbus_pid)
                        log.warn(" %s", e)
                _cleanups.append(kill_dbus)
                #this also updates os.environ with the dbus attributes:
                dbus_pid, dbus_env = start_dbus(opts.dbus_launch)
                if dbus_pid>0:
                    save_dbus_pid(dbus_pid)
                if dbus_env:
                    save_dbus_env(dbus_env)
            else:
                dbus_env = {}
        os.environ.update(dbus_env)

        try:
            # This import is delayed because the module depends on gtk:
            from xpra.x11.bindings.window_bindings import X11WindowBindings
            X11Window = X11WindowBindings()
            if (starting or starting_desktop) and not clobber and opts.resize_display:
                set_initial_resolution()
        except ImportError as e:
            log.error("Failed to load Xpra server components, check your installation: %s" % e)
            return 1
        if starting or upgrading:
            if not X11Window.displayHasXComposite():
                log.error("Xpra 'start' subcommand runs as a compositing manager")
                log.error(" it cannot use a display which lacks the XComposite extension!")
                return 1
            if starting:
                #check for an existing window manager:
                from xpra.x11.gtk2.wm import wm_check
                if not wm_check(display, opts.wm_name, upgrading):
                    return 1
            log("XShape=%s", X11Window.displayHasXShape())
            from xpra.x11.server import XpraServer
            app = XpraServer(clobber)
            info = "xpra"
        else:
            assert starting_desktop
            from xpra.x11.desktop_server import XpraDesktopServer
            app = XpraDesktopServer()
            info = "xpra desktop"

    #publish mdns records:
    if opts.mdns:
        from xpra.os_util import strtobytes
        from xpra.platform.info import get_username
        from xpra.server.socket_util import mdns_publish
        mdns_info = {
                     "display"  : display_name,
                     "username" : get_username(),
                     "uuid"     : strtobytes(app.uuid),
                     "platform" : sys.platform,
                     "type"     : {"xpra" : "seamless", "xpra desktop" : "desktop"}.get(info, info),
                     }
        if opts.session_name:
            mdns_info["session"] = opts.session_name
        for mode, listen_on in mdns_recs:
            mdns_publish(display_name, mode, listen_on, mdns_info)

    try:
        app._ssl_wrap_socket = wrap_socket_fn
        app.original_desktop_display = desktop_display
        app.exec_cwd = cwd
        app.init(opts)
        app.init_components(opts)
    except InitException as e:
        log.error("xpra server initialization error:")
        log.error(" %s", e)
        return 1
    except Exception as e:
        log.error("Error: cannot start the %s server", info, exc_info=True)
        log.error(str(e))
        log.info("")
        return 1

    #honour start child, html webserver, and setup child reaper
    if not proxying and not upgrading:
        if opts.exit_with_children:
            assert opts.start_child, "exit-with-children was specified but start-child is missing!"
        app.start_commands              = opts.start
        app.start_child_commands        = opts.start_child
        app.start_after_connect         = opts.start_after_connect
        app.start_child_after_connect   = opts.start_child_after_connect
        app.start_on_connect            = opts.start_on_connect
        app.start_child_on_connect      = opts.start_child_on_connect
        app.exec_start_commands()
    del opts

    log("%s(%s)", app.init_sockets, sockets)
    app.init_sockets(sockets)
    log("%s(%s)", app.init_when_ready, _when_ready)
    app.init_when_ready(_when_ready)

    try:
        #from here on, we own the vfb, even if we inherited one:
        if (starting or starting_desktop or upgrading) and clobber:
            #and it will be killed if exit cleanly:
            xvfb_pid = get_xvfb_pid()

        log("running %s", app.run)
        e = app.run()
        log("%s()=%s", app.run, e)
    except KeyboardInterrupt:
        log.info("stopping on KeyboardInterrupt")
        e = 0
    except Exception as e:
        log.error("server error", exc_info=True)
        e = -128
    if e>0:
        # Upgrading/exiting, so leave X and dbus servers running
        if close_display:
            _cleanups.remove(close_display)
        if kill_dbus:
            _cleanups.remove(kill_dbus)
        from xpra.server.server_core import ServerCore
        if e==ServerCore.EXITING_CODE:
            log.info("exiting: not cleaning up Xvfb")
        else:
            log.info("upgrading: not cleaning up Xvfb")
        log("cleanups=%s", _cleanups)
        e = 0
    return e
