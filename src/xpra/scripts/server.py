# This file is part of Xpra.
# Copyright (C) 2010-2016 Antoine Martin <antoine@devloop.org.uk>
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
import select
import time
import traceback

from xpra.scripts.main import TCP_NODELAY, warn, no_gtk, validate_encryption
from xpra.scripts.config import InitException, parse_bool
from xpra.os_util import SIGNAMES
from xpra.platform.dotxpra import DotXpra, norm_makepath, osexpand


# use process polling with python versions older than 2.7 and 3.0, (because SIGCHLD support is broken)
# or when the user requests it with the env var:
USE_PROCESS_POLLING = os.environ.get("XPRA_USE_PROCESS_POLLING")=="1" or sys.version_info<(2, 7) or sys.version_info[:2]==(3, 0)
WAIT_FOR_UNKNOWN = int(os.environ.get("XPRA_WAIT_FOR_UNKNOWN_SOCKETS", "5"))

DEFAULT_VFB_RESOLUTION = tuple(int(x) for x in os.environ.get("XPRA_DEFAULT_VFB_RESOLUTION", "1920x1080").replace(",", "x").split("x", 1))


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
    sys.stdout.write("got deadly signal %s, exiting\n" % SIGNAMES.get(signum, signum))
    sys.stdout.flush()
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


def sh_quotemeta(s):
    return "'" + s.replace("'", "'\\''") + "'"

def xpra_runner_shell_script(xpra_file, starting_dir, socket_dir):
    script = []
    script.append("#!/bin/sh\n")
    for var, value in os.environ.items():
        # these aren't used by xpra, and some should not be exposed
        # as they are either irrelevant or simply do not match
        # the new environment used by xpra
        # TODO: use a whitelist
        if var in ["XDG_SESSION_COOKIE", "LS_COLORS", "DISPLAY"]:
            continue
        #XPRA_SOCKET_DIR is a special case, it is handled below
        if var=="XPRA_SOCKET_DIR":
            continue
        if var.startswith("BASH_FUNC"):
            #some versions of bash will apparently generate functions
            #that cannot be reloaded using this script
            continue
        # :-separated envvars that people might change while their server is
        # going:
        if var in ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH"):
            #prevent those paths from accumulating the same values multiple times,
            #only keep the first one:
            pval = value.split(os.pathsep)      #ie: ["/usr/bin", "/usr/local/bin", "/usr/bin"]
            seen = set()
            value = os.pathsep.join(x for x in pval if not (x in seen or seen.add(x)))
            script.append("%s=%s:\"$%s\"; export %s\n"
                          % (var, sh_quotemeta(value), var, var))
        else:
            script.append("%s=%s; export %s\n"
                          % (var, sh_quotemeta(value), var))
    #XPRA_SOCKET_DIR is a special case, we want to honour it
    #when it is specified, but the client may override it:
    if socket_dir:
        script.append('if [ -z "${XPRA_SOCKET_DIR}" ]; then\n');
        script.append('    XPRA_SOCKET_DIR=%s; export XPRA_SOCKET_DIR\n' % sh_quotemeta(os.path.expanduser(socket_dir)))
        script.append('fi\n');
    # We ignore failures in cd'ing, b/c it's entirely possible that we were
    # started from some temporary directory and all paths are absolute.
    script.append("cd %s\n" % sh_quotemeta(starting_dir))
    if sys.platform.startswith("darwin"):
        #OSX contortions:
        #The executable is the python interpreter,
        #which is execed by a shell script, which we have to find..
        sexec = sys.executable
        bini = sexec.rfind("Resources/bin/")
        if bini>0:
            sexec = os.path.join(sexec[:bini], "Resources", "MacOS", "Xpra")
        script.append("_XPRA_SCRIPT=%s\n" % (sh_quotemeta(sexec),))
        script.append("""
if which "$_XPRA_SCRIPT" > /dev/null; then
    # Happypath:
    exec "$_XPRA_SCRIPT" "$@"
else
    # Hope for the best:
    exec Xpra "$@"
fi
""")
    else:
        script.append("_XPRA_PYTHON=%s\n" % (sh_quotemeta(sys.executable),))
        script.append("_XPRA_SCRIPT=%s\n" % (sh_quotemeta(xpra_file),))
        script.append("""
if which "$_XPRA_PYTHON" > /dev/null && [ -e "$_XPRA_SCRIPT" ]; then
    # Happypath:
    exec "$_XPRA_PYTHON" "$_XPRA_SCRIPT" "$@"
else
    cat >&2 <<END
    Could not find one or both of '$_XPRA_PYTHON' and '$_XPRA_SCRIPT'
    Perhaps your environment has changed since the xpra server was started?
    I'll just try executing 'xpra' with current PATH, and hope...
END
    exec xpra "$@"
fi
""")
    return "".join(script)

def write_runner_shell_scripts(contents, overwrite=True):
    # This used to be given a display-specific name, but now we give it a
    # single fixed name and if multiple servers are started then the last one
    # will clobber the rest.  This isn't great, but the tradeoff is that it
    # makes it possible to use bare 'ssh:hostname' display names and
    # autodiscover the proper numeric display name when only one xpra server
    # is running on the remote host.  Might need to revisit this later if
    # people run into problems or autodiscovery turns out to be less useful
    # than expected.
    from xpra.platform.paths import get_script_bin_dirs
    for d in get_script_bin_dirs():
        scriptdir = osexpand(d)
        if not os.path.exists(scriptdir):
            try:
                os.mkdir(scriptdir, 0o700)
            except Exception as e:
                sys.stderr.write("Error: failed to write script file in '%s':\n" % scriptdir)
                sys.stderr.write(" %s\n" % e)
                continue
        scriptpath = os.path.join(scriptdir, "run-xpra")
        if os.path.exists(scriptpath) and not overwrite:
            continue
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        try:
            with open(scriptpath, "w") as scriptfile:
                # Unix is a little silly sometimes:
                umask = os.umask(0)
                os.umask(umask)
                os.fchmod(scriptfile.fileno(), 0o700 & ~umask)
                scriptfile.write(contents)
        except Exception as e:
            sys.stderr.write("Error: failed to write script file '%s':\n" % scriptpath)
            sys.stderr.write(" %s\n" % e)


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


def get_ssh_port():
    #FIXME: how do we find out which port ssh is on?
    return 22

#warn just once:
MDNS_WARNING = False
def mdns_publish(display_name, mode, listen_on, text_dict={}):
    global MDNS_WARNING
    if MDNS_WARNING is True:
        return
    PREFER_PYBONJOUR = os.environ.get("XPRA_PREFER_PYBONJOUR", "0")=="1" or sys.platform.startswith("win") or sys.platform.startswith("darwin")
    try:
        if PREFER_PYBONJOUR:
            from xpra.net.pybonjour_publisher import BonjourPublishers as MDNSPublishers
        else:
            from xpra.net.avahi_publisher import AvahiPublishers as MDNSPublishers
    except ImportError as e:
        MDNS_WARNING = True
        from xpra.log import Logger
        log = Logger("mdns")
        log.warn("Warning: failed to load the mdns %s publisher:", ["avahi", "pybonjour"][PREFER_PYBONJOUR])
        log.warn(" %s", e)
        log.warn(" either fix your installation or use the 'mdns=no' option")
        return
    d = text_dict.copy()
    d["mode"] = mode
    ap = MDNSPublishers(listen_on, "Xpra %s %s" % (mode, display_name), text_dict=d)
    _when_ready.append(ap.start)
    _cleanups.append(ap.stop)


def create_unix_domain_socket(sockpath, mmap_group, socket_permissions):
    if mmap_group:
        #when using the mmap group option, use '660'
        umask = 0o117
    else:
        #parse octal mode given as config option:
        try:
            if type(socket_permissions)==int:
                sperms = socket_permissions
            else:
                #assume octal string:
                sperms = int(socket_permissions, 8)
            assert sperms>=0 and sperms<=0o777
        except ValueError:
            raise ValueError("invalid socket permissions (must be an octal number): '%s'" % socket_permissions)
        #now convert this to a umask!
        umask = 0o777-sperms
    listener = socket.socket(socket.AF_UNIX)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #bind the socket, using umask to set the correct permissions
    orig_umask = os.umask(umask)
    try:
        listener.bind(sockpath)
    finally:
        os.umask(orig_umask)
    def cleanup_socket():
        from xpra.log import Logger
        Logger("network").info("removing socket %s", sockpath)
        try:
            os.unlink(sockpath)
        except:
            pass
    return listener, cleanup_socket

def create_tcp_socket(host, iport):
    if host.find(":")<0:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockaddr = (host, iport)
    else:
        assert socket.has_ipv6, "specified an IPv6 address but this is not supported"
        res = socket.getaddrinfo(host, iport, socket.AF_INET6, socket.SOCK_STREAM, 0, socket.SOL_TCP)
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sockaddr = res[0][-1]
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, TCP_NODELAY)
    listener.bind(sockaddr)
    return listener

def setup_tcp_socket(host, iport, socktype="TCP"):
    from xpra.log import Logger
    log = Logger("network")
    try:
        tcp_socket = create_tcp_socket(host, iport)
    except Exception as e:
        raise InitException("failed to setup %s socket on %s:%s %s" % (socktype, host, iport, e))
    def cleanup_tcp_socket():
        log.info("closing %s socket %s:%s", socktype, host, iport)
        try:
            tcp_socket.close()
        except:
            pass
    _cleanups.append(cleanup_tcp_socket)
    return "tcp", tcp_socket, (host, iport)


def parse_bind_tcp(bind_tcp):
    tcp_sockets = set()
    if bind_tcp:
        for spec in bind_tcp:
            if ":" not in spec:
                raise InitException("TCP port must be specified as [HOST]:PORT")
            host, port = spec.rsplit(":", 1)
            if host == "":
                host = "127.0.0.1"
            try:
                iport = int(port)
            except:
                raise InitException("invalid port number: %s" % port)
            tcp_sockets.add((host, iport))
    return tcp_sockets

def setup_vsock_socket(cid, iport):
    from xpra.log import Logger
    log = Logger("network")
    try:
        from xpra.net.vsock import bind_vsocket     #@UnresolvedImport
        vsock_socket = bind_vsocket(cid=cid, port=iport)
    except Exception as e:
        raise InitException("failed to setup vsock socket on %s:%s %s" % (cid, iport, e))
    def cleanup_vsock_socket():
        log.info("closing vsock socket %s:%s", cid, iport)
        try:
            vsock_socket.close()
        except:
            pass
    _cleanups.append(cleanup_vsock_socket)
    return "vsock", vsock_socket, (cid, iport)

def parse_bind_vsock(bind_vsock):
    vsock_sockets = set()
    if bind_vsock:
        from xpra.scripts.main import parse_vsock
        for spec in bind_vsock:
            vsock_sockets.add(parse_vsock(spec))
    return vsock_sockets


def normalize_local_display_name(local_display_name):
    if not local_display_name.startswith(":"):
        local_display_name = ":" + local_display_name
    if "." in local_display_name:
        local_display_name = local_display_name[:local_display_name.rindex(".")]
    assert local_display_name.startswith(":")
    for char in local_display_name[1:]:
        assert char in "0123456789", "invalid character in display name: %s" % char
    return local_display_name

# Same as socket_path, but preps for the server:
def setup_server_socket_path(dotxpra, sockpath, local_display_name, clobber, wait_for_unknown=0):
    if not clobber:
        state = dotxpra.get_server_state(sockpath, 1)
        counter = 0
        while state==dotxpra.UNKNOWN and counter<wait_for_unknown:
            if counter==0:
                sys.stdout.write("%s is not responding, waiting for it to timeout before clearing it" % sockpath)
            sys.stdout.write(".")
            sys.stdout.flush()
            counter += 1
            if counter<wait_for_unknown:
                time.sleep(1)
            state = dotxpra.get_server_state(sockpath)
        if counter>0:
            sys.stdout.write("\n")
            sys.stdout.flush()
        if state not in (dotxpra.DEAD, dotxpra.UNKNOWN):
            raise InitException("You already have an xpra server running at %s\n"
                     "  (did you want 'xpra upgrade'?)"
                     % (local_display_name,))
    if os.path.exists(sockpath):
        os.unlink(sockpath)
    return sockpath


def setup_local_sockets(bind, socket_dir, socket_dirs, display_name, clobber, mmap_group, socket_permissions):
    dotxpra = DotXpra(socket_dir or socket_dirs[0])
    try:
        dotxpra.mksockdir()
        display_name = normalize_local_display_name(display_name)
    except Exception as e:
        raise InitException("socket path error: %s" % e)
    from xpra.log import Logger
    defs = []
    sockpaths = set()
    log = Logger("network")
    try:
        log("setup_local_sockets: bind=%s", bind)
        for b in bind:
            sockpath = b
            try:
                if b=="none" or b=="":
                    continue
                elif b=="auto":
                    sockpath = dotxpra.socket_path(display_name)
                else:
                    sockpath = osexpand(b)
                    if b.endswith("/") or (os.path.exists(sockpath) and os.path.isdir(sockpath)):
                        sockpath = os.path.abspath(sockpath)
                        if not os.path.exists(sockpath):
                            os.makedirs(sockpath)
                        sockpath = norm_makepath(sockpath, display_name)
                    else:
                        sockpath = dotxpra.socket_path(b)
                if sockpath in sockpaths:
                    log.warn("Warning: skipping duplicate bind path %s", sockpath)
                    continue
                if sys.platform.startswith("win"):
                    from xpra.platform.win32.namedpipes.listener import NamedPipeListener
                    npl = NamedPipeListener(sockpath)
                    log.info("created named pipe: %s", sockpath)
                    defs.append((("named-pipe", npl, sockpath), npl.stop))
                else:
                    setup_server_socket_path(dotxpra, sockpath, display_name, clobber, wait_for_unknown=WAIT_FOR_UNKNOWN)
                    sock, cleanup_socket = create_unix_domain_socket(sockpath, mmap_group, socket_permissions)
                    log.info("created unix domain socket: %s", sockpath)
                    defs.append((("unix-domain", sock, sockpath), cleanup_socket))
                sockpaths.add(sockpath)
            except Exception as e:
                log("socket creation error", exc_info=True)
                log.error("Error: failed to create socket '%s':" % sockpath)
                log.error(" %s", e)
                raise InitException("failed to create socket %s" % sockpath)
    except:
        for sock, cleanup_socket in defs:
            try:
                cleanup_socket()
            except Exception as e:
                log.warn("error cleaning up socket %s", sock)
        defs = []
        raise
    return defs


def get_free_tcp_port():
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def close_all_fds(exceptions=[]):
    fd_dirs = ["/dev/fd", "/proc/self/fd"]
    for fd_dir in fd_dirs:
        if os.path.exists(fd_dir):
            for fd_str in os.listdir(fd_dir):
                try:
                    fd = int(fd_str)
                    if fd not in exceptions:
                        os.close(fd)
                except OSError:
                    # This exception happens inevitably, because the fd used
                    # by listdir() is already closed.
                    pass
            return
    print("Uh-oh, can't close fds, please port me to your system...")

def shellsub(s, subs={}):
    """ shell style string substitution using the dictionary given """
    for var,value in subs.items():
        s = s.replace("$%s" % var, str(value))
        s = s.replace("${%s}" % var, str(value))
    return s

def open_log_file(logpath):
    """ renames the existing log file if it exists,
        then opens it for writing.
    """
    if os.path.exists(logpath):
        os.rename(logpath, logpath + ".old")
    return os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)

def select_log_file(log_dir, log_file, display_name):
    """ returns the log file path we should be using given the parameters,
        this may return a temporary logpath if display_name is not available.
    """
    if log_file and display_name:
        if os.path.isabs(log_file):
            logpath = log_file
        else:
            logpath = os.path.join(log_dir, log_file)
        logpath = shellsub(logpath, {"DISPLAY" : display_name})
    elif display_name:
        logpath = norm_makepath(log_dir, display_name) + ".log"
    else:
        logpath = os.path.join(log_dir, "tmp_%d.log" % os.getpid())
    return logpath


def daemonize(logfd):
    os.chdir("/")
    if os.fork():
        os._exit(0)
    os.setsid()
    if os.fork():
        os._exit(0)
    # save current stdout/stderr to be able to print info
    # before exiting the non-deamon process
    # and closing those file descriptors definitively
    old_fd_stdout = os.dup(1)
    old_fd_stderr = os.dup(2)
    close_all_fds(exceptions=[logfd,old_fd_stdout,old_fd_stderr])
    fd0 = os.open("/dev/null", os.O_RDONLY)
    if fd0 != 0:
        os.dup2(fd0, 0)
        os.close(fd0)
    # reopen STDIO files
    old_stdout = os.fdopen(old_fd_stdout, "w", 1)
    old_stderr = os.fdopen(old_fd_stderr, "w", 1)
    # replace standard stdout/stderr by the log file
    os.dup2(logfd, 1)
    os.dup2(logfd, 2)
    os.close(logfd)
    # Make these line-buffered:
    sys.stdout = os.fdopen(1, "w", 1)
    sys.stderr = os.fdopen(2, "w", 1)
    return (old_stdout, old_stderr)


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

def close_fds(excluding=[0, 1, 2]):
    try:
        MAXFD = os.sysconf("SC_OPEN_MAX")
    except:
        MAXFD = 256
    for i in range(0, MAXFD):
        if i not in excluding:
            try:
                os.close(i)
            except:
                pass

def start_Xvfb(xvfb_str, display_name, cwd):
    if not xvfb_str:
        raise InitException("the 'xvfb' command is not defined")
    # We need to set up a new server environment
    xauthority = os.environ.get("XAUTHORITY", os.path.expanduser("~/.Xauthority"))
    if not os.path.exists(xauthority):
        try:
            open(xauthority, 'wa').close()
        except Exception as e:
            #trying to continue anyway!
            sys.stderr.write("Error trying to create XAUTHORITY file %s: %s\n" % (xauthority, e))
    use_display_fd = display_name[0]=='S'

    #identify logfile argument if it exists,
    #as we may have to rename it, or create the directory for it:
    xvfb_cmd = xvfb_str.split()
    try:
        logfile_argindex = xvfb_cmd.index('-logfile')
    except ValueError:
        logfile_argindex = -1
    assert logfile_argindex+1<len(xvfb_cmd), "invalid xvfb command string: -logfile should not be last (found at index %i)" % logfile_argindex
    tmp_xorg_log_file = None
    if logfile_argindex>0:
        if use_display_fd:
            #keep track of it so we can rename it later:
            tmp_xorg_log_file = xvfb_cmd[logfile_argindex+1]
        #make sure the Xorg log directory exists:
        xorg_log_dir = osexpand(os.path.dirname(xvfb_cmd[logfile_argindex+1]))
        if not os.path.exists(xorg_log_dir):
            try:
                os.mkdir(xorg_log_dir, 0o700)
            except OSError as e:
                raise InitException("failed to create the Xorg log directory '%s': %s" % (xorg_log_dir, e))

    #apply string substitutions:
    subs = {"XAUTHORITY"    : xauthority,
            "USER"          : os.environ.get("USER", "unknown-user"),
            "UID"           : os.getuid(),
            "GID"           : os.getgid(),
            "HOME"          : os.environ.get("HOME", cwd),
            "DISPLAY"       : display_name}
    xvfb_str = shellsub(xvfb_str, subs)

    def setsid():
        #run in a new session
        if os.name=="posix":
            os.setsid()

    xvfb_cmd = xvfb_str.split()
    if not xvfb_cmd:
        raise InitException("cannot start Xvfb, the command definition is missing!")
    xvfb_executable = xvfb_cmd[0]
    if use_display_fd:
        # 'S' means that we allocate the display automatically
        r_pipe, w_pipe = os.pipe()
        xvfb_cmd += ["-displayfd", str(w_pipe)]
        xvfb_cmd[0] = "%s-for-Xpra-%s" % (xvfb_executable, display_name)
        def preexec():
            setsid()
            close_fds([0, 1, 2, r_pipe, w_pipe])
        xvfb = subprocess.Popen(xvfb_cmd, executable=xvfb_executable, close_fds=False,
                                stdin=subprocess.PIPE, preexec_fn=preexec, cwd=cwd)
        # Read the display number from the pipe we gave to Xvfb
        # waiting up to 10 seconds for it to show up
        limit = time.time()+10
        buf = ""
        while time.time()<limit and len(buf)<8:
            r, _, _ = select.select([r_pipe], [], [], max(0, limit-time.time()))
            if r_pipe in r:
                buf += os.read(r_pipe, 8)
                if buf[-1] == '\n':
                    break
        os.close(r_pipe)
        os.close(w_pipe)
        if len(buf) == 0:
            raise OSError("%s did not provide a display number using -displayfd" % xvfb_executable)
        if buf[-1] != '\n':
            raise OSError("%s output not terminated by newline: %s" % (xvfb_executable, buf))
        try:
            n = int(buf[:-1])
        except:
            raise OSError("%s display number is not a valid number: %s" % (xvfb_executable, buf[:-1]))
        if n<0 or n>=2**16:
            raise OSError("%s provided an invalid display number: %s" % (xvfb_executable, n))
        new_display_name = ":%s" % n
        sys.stdout.write("Using display number provided by %s: %s\n" % (xvfb_executable, new_display_name))
        if tmp_xorg_log_file != None:
            #ie: ${HOME}/.xpra/Xorg.${DISPLAY}.log -> /home/antoine/.xpra/Xorg.S14700.log
            f0 = shellsub(tmp_xorg_log_file, subs)
            subs["DISPLAY"] = new_display_name
            #ie: ${HOME}/.xpra/Xorg.${DISPLAY}.log -> /home/antoine/.xpra/Xorg.:1.log
            f1 = shellsub(tmp_xorg_log_file, subs)
            if f0 != f1:
                try:
                    os.rename(f0, f1)
                except Exception as e:
                    sys.stderr.write("failed to rename Xorg log file from '%s' to '%s'\n" % (f0, f1))
                    sys.stderr.write(" %s\n" % e)
        display_name = new_display_name
    else:
        # use display specified
        xvfb_cmd[0] = "%s-for-Xpra-%s" % (xvfb_executable, display_name)
        xvfb_cmd.append(display_name)
        xvfb = subprocess.Popen(xvfb_cmd, executable=xvfb_executable, close_fds=True,
                                stdin=subprocess.PIPE, preexec_fn=setsid)
    xauth_add(display_name)
    return xvfb, display_name

def xauth_add(display_name):
    from xpra.os_util import get_hex_uuid
    xauth_cmd = ["xauth", "add", display_name, "MIT-MAGIC-COOKIE-1", get_hex_uuid()]
    try:
        code = subprocess.call(xauth_cmd)
        if code != 0:
            raise OSError("non-zero exit code: %s" % code)
    except OSError as e:
        #trying to continue anyway!
        sys.stderr.write("Error running \"%s\": %s\n" % (" ".join(xauth_cmd), e))

def check_xvfb_process(xvfb=None, cmd="Xvfb"):
    if xvfb is None:
        #we don't have a process to check
        return True
    if xvfb.poll() is None:
        #process is running
        return True
    from xpra.log import Logger
    log = Logger("server")
    log.error("")
    log.error("%s command has terminated! xpra cannot continue", cmd)
    log.error(" if the display is already running, try a different one,")
    log.error(" or use the --use-display flag")
    log.error("")
    return False

def verify_display_ready(xvfb, display_name, shadowing_check=True):
    from xpra.x11.bindings.wait_for_x_server import wait_for_x_server        #@UnresolvedImport
    # Whether we spawned our server or not, it is now running -- or at least
    # starting.  First wait for it to start up:
    try:
        wait_for_x_server(display_name, 3) # 3s timeout
    except Exception as e:
        sys.stderr.write("display %s failed:\n" % display_name)
        sys.stderr.write("%s\n" % e)
        return False
    if shadowing_check and not check_xvfb_process(xvfb):
        #if we're here, there is an X11 server, but it isn't the one we started!
        from xpra.log import Logger
        log = Logger("server")
        log.error("There is an X11 server already running on display %s:" % display_name)
        log.error("You may want to use:")
        log.error("  'xpra upgrade %s' if an instance of xpra is still connected to it" % display_name)
        log.error("  'xpra --use-display start %s' to connect xpra to an existing X11 server only" % display_name)
        log.error("")
        return False
    return True

def verify_gdk_display(display_name):
    # Now we can safely load gtk and connect:
    no_gtk()
    import gtk.gdk          #@Reimport
    try:
        import glib
        glib.threads_init()
    except:
        #old versions do not have this method
        pass
    display = gtk.gdk.Display(display_name)
    manager = gtk.gdk.display_manager_get()
    default_display = manager.get_default_display()
    if default_display is not None and default_display!=display:
        default_display.close()
    manager.set_default_display(display)
    return display

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
        if sys.platform.startswith("win") or sys.platform.startswith("darwin"):
            #just a virtual name for the only display available:
            display_name = ":0"
        else:
            from xpra.scripts.main import guess_X11_display
            display_name = guess_X11_display(opts.socket_dir, opts.socket_dirs)
    elif upgrading and len(extra_args)==0:
        display_name = guess_xpra_display(opts.socket_dir, opts.socket_dirs)
    else:
        if len(extra_args) > 1:
            error_cb("too many extra arguments: only expected a display number")
        if len(extra_args) == 1:
            display_name = extra_args[0]
            if not shadowing and not proxying:
                display_name_check(display_name)
        else:
            if proxying:
                error_cb("you must specify a free virtual display name to use with the proxy server")
            if not opts.displayfd:
                error_cb("displayfd support is not enabled on this system, you must specify the display to use")
            if opts.use_display:
                #only use automatic guess for xpra displays and not X11 displays:
                display_name = guess_xpra_display(opts.socket_dir, opts.socket_dirs)
            else:
                # We will try to find one automaticaly
                # Use the temporary magic value 'S' as marker:
                display_name = 'S' + str(os.getpid())

    if not shadowing and not proxying and not upgrading and opts.exit_with_children and not opts.start_child:
        error_cb("--exit-with-children specified without any children to spawn; exiting immediately")

    atexit.register(run_cleanups)

    # if pam is present, create a new session:
    if os.name=="posix":
        try:
            from xpra.server.pam import pam_open, pam_close
        except ImportError as e:
            sys.stderr.write("No pam support: %s\n" % e)
        else:
            if pam_open():
                _cleanups.append(pam_close)

    # Generate the script text now, because os.getcwd() will
    # change if/when we daemonize:
    script = xpra_runner_shell_script(xpra_file, cwd, opts.socket_dir)

    if start_vfb or opts.daemon:
        #we will probably need a log dir
        #either for the vfb, or for our own log file
        log_dir = osexpand(opts.log_dir)
        if not os.path.exists(log_dir):
            try:
                os.mkdir(log_dir, 0o700)
            except Exception as e:
                sys.stderr.write("%s\n" % e)

    stdout = sys.stdout
    stderr = sys.stderr
    # Daemonize:
    if opts.daemon:
        #daemonize will chdir to "/", so try to use an absolute path:
        if opts.password_file:
            opts.password_file = os.path.abspath(opts.password_file)
        # At this point we may not know the display name,
        # so log_filename0 may point to a temporary file which we will rename later
        log_filename0 = select_log_file(log_dir, opts.log_file, display_name)
        logfd = open_log_file(log_filename0)
        assert logfd > 2
        stdout, stderr = daemonize(logfd)
        try:
            stderr.write("Entering daemon mode; "
                 + "any further errors will be reported to:\n"
                 + ("  %s\n" % log_filename0))
        except:
            #this can happen if stderr is closed by the caller already
            pass

    if os.name=="posix":
        # Write out a shell-script so that we can start our proxy in a clean
        # environment:
        write_runner_shell_scripts(script)

    from xpra.log import Logger
    log = Logger("server")

    #warn early about this:
    if (starting or starting_desktop) and desktop_display:
        de = os.environ.get("XDG_SESSION_DESKTOP") or os.environ.get("SESSION_DESKTOP")
        if de:
            warn = []
            if opts.pulseaudio:
                try:
                    xprop = subprocess.Popen(["xprop", "-root", "-display", desktop_display], stdout=subprocess.PIPE)
                    out,_ = xprop.communicate()
                    for x in out.splitlines():
                        if x.startswith("PULSE_SERVER"):
                            #found an existing pulseaudio server
                            warn.append("pulseaudio")
                            break
                except:
                    pass    #don't care, this is just to decide if we show an informative warning or not
            if opts.notifications and not opts.dbus_launch:
                warn.append("notifications")
            if warn:
                log.warn("Warning: xpra start from an existing '%s' desktop session", de)
                log.warn(" %s forwarding may not work", " ".join(warn))
                log.warn(" try using a clean environment, a dedicated user,")
                log.warn(" or turn off %s", " and ".join(warn))

    mdns_recs = []
    sockets = []

    #SSL sockets:
    wrap_socket_fn = None
    ssl_opt = parse_bool("ssl", opts.ssl)
    if ssl_opt is True or bind_ssl or (ssl_opt is None and opts.bind_tcp and opts.ssl_cert):
        from xpra.scripts.main import ssl_wrap_socket_fn
        try:
            wrap_socket_fn = ssl_wrap_socket_fn(opts, server_side=True)
        except Exception as e:
            raise InitException("cannot create SSL socket (check your certificate paths): %s" % e)
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
    xvfb = None
    xvfb_pid = None
    if start_vfb:
        try:
            xvfb, display_name = start_Xvfb(opts.xvfb, display_name, cwd)
        except OSError as e:
            log.error("Error starting Xvfb:")
            log.error(" %s", e)
            log("start_Xvfb error", exc_info=True)
            return  1
        xvfb_pid = xvfb.pid
        #always update as we may now have the "real" display name:
        os.environ["DISPLAY"] = display_name

    if opts.daemon:
        log_filename1 = select_log_file(log_dir, opts.log_file, display_name)
        if log_filename0 != log_filename1:
            # we now have the correct log filename, so use it:
            os.rename(log_filename0, log_filename1)
            stderr.write("Actual log file name is now: %s\n" % log_filename1)
        stdout.close()
        stderr.close()

    if not check_xvfb_process(xvfb):
        #xvfb problem: exit now
        return  1

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

    #setup unix domain socket:
    local_sockets = setup_local_sockets(opts.bind, opts.socket_dir, opts.socket_dirs, display_name, clobber, opts.mmap_group, opts.socket_permissions)
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
            xvfb_pid = get_xvfb_pid()
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
            if starting or starting_desktop and not clobber:
                try:
                    from xpra.x11.bindings.randr_bindings import RandRBindings
                    #try to set a reasonable display size:
                    randr = RandRBindings()
                    if not randr.has_randr():
                        log("no RandR, default virtual display size unchanged")
                    else:
                        sizes = randr.get_screen_sizes()
                        size = randr.get_screen_size()
                        log("RandR available, current size=%s, sizes available=%s", size, sizes)
                        if DEFAULT_VFB_RESOLUTION in sizes:
                            log("RandR setting new screen size to %s", DEFAULT_VFB_RESOLUTION)
                            randr.set_screen_size(*DEFAULT_VFB_RESOLUTION)
                except Exception as e:
                    log.warn("Warning: failed to set the default screen size:")
                    log.warn(" %s", e)
        except ImportError as e:
            log.error("Failed to load Xpra server components, check your installation: %s" % e)
            return 1
        if starting:
            if not X11Window.displayHasXComposite():
                log.error("Xpra 'start' subcommand runs as a compositing manager")
                log.error(" it cannot use a display which lacks the XComposite extension!")
                return 1
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
        from xpra.platform.info import get_username
        mdns_info = {"display" : display_name,
                     "username": get_username()}
        if opts.session_name:
            mdns_info["session"] = opts.session_name
        for mode, listen_on in mdns_recs:
            mdns_publish(display_name, mode, listen_on, mdns_info)

    #we got this far so the sockets have initialized and
    #the server should be able to manage the display
    #from now on, if we exit without upgrading we will also kill the Xvfb
    def close_display():
        # Close our display(s) first, so the server dying won't kill us.
        import gtk  #@Reimport
        for d in gtk.gdk.display_manager_get().list_displays():
            d.close()
        if xvfb_pid:
            log.info("killing xvfb with pid %s", xvfb_pid)
            try:
                os.kill(xvfb_pid, signal.SIGTERM)
            except OSError as e:
                log.info("failed to kill xvfb process with pid %s:", xvfb_pid)
                log.info(" %s", e)
    if not proxying:
        _cleanups.append(close_display)

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
        if close_display in _cleanups:
            _cleanups.remove(close_display)
            if kill_dbus:
                _cleanups.remove(kill_dbus)
        from xpra.server.server_core import ServerCore
        if e==ServerCore.EXITING_CODE:
            log.info("exiting: not cleaning up Xvfb")
        elif local_sockets:
            # don't delete the new sockets (probably not ours!)
            # FIXME: keep track of which server (new or old) owns which socket,
            # so we can delete the ones that have not been replaced
            for socket, cleanup_socket in local_sockets:
                if cleanup_socket in _cleanups:
                    log("removing cleanup: %s for %s", cleanup_socket, socket)
                    _cleanups.remove(cleanup_socket)
            log.info("upgrading: not cleaning up Xvfb or socket")
        log("cleanups=%s", _cleanups)
        e = 0
    return e
