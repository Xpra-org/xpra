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
import select
import traceback

from xpra.scripts.main import warn, no_gtk, validate_encryption
from xpra.scripts.config import InitException, TRUE_OPTIONS, FALSE_OPTIONS
from xpra.os_util import SIGNAMES, setsid, getuid, getgid, get_username_for_uid, get_groups, get_group_id, monotonic_time, WIN32, OSX
from xpra.util import envint, envbool, csv, DEFAULT_PORT
from xpra.platform.dotxpra import DotXpra, norm_makepath, osexpand


#what timeout value to use on the socket probe attempt:
WAIT_PROBE_TIMEOUT = envint("XPRA_WAIT_PROBE_TIMEOUT", 6)

DEFAULT_VFB_RESOLUTION = tuple(int(x) for x in os.environ.get("XPRA_DEFAULT_VFB_RESOLUTION", "8192x4096").replace(",", "x").split("x", 1))


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
    if OSX:
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
    from xpra.log import Logger
    log = Logger("server")
    from xpra.platform.paths import get_script_bin_dirs
    for d in get_script_bin_dirs():
        scriptdir = osexpand(d)
        if not os.path.exists(scriptdir):
            try:
                os.mkdir(scriptdir, 0o700)
            except Exception as e:
                log.warn("Warning: failed to write script file in '%s':", scriptdir)
                log.warn(" %s", e)
                if scriptdir.startswith("/var/run/user") or scriptdir.startswith("/run/user"):
                    log.warn(" ($XDG_RUNTIME_DIR has not been created?)")
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
            log.error("Error: failed to write script file '%s':", scriptpath)
            log.error(" %s\n", e)

def write_pidfile(pidfile):
    from xpra.log import Logger
    log = Logger("server")
    pidstr = str(os.getpid())
    try:
        with open(pidfile, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write("%s\n" % pidstr)
            try:
                inode = os.fstat(f.fileno()).st_ino
            except:
                inode = -1
        log.info("wrote pid %s to '%s'", pidstr, pidfile)
        def cleanuppidfile():
            #verify this is the right file!
            log("cleanuppidfile: inode=%i", inode)
            if inode>0:
                try:
                    i = os.stat(pidfile).st_ino
                    log("cleanuppidfile: current inode=%i", i)
                    if i!=inode:
                        return
                except:
                    pass
            try:
                os.unlink(pidfile)
            except:
                pass
        _cleanups.append(cleanuppidfile)
    except Exception as e:
        log.error("Error: failed to write pid %i to pidfile '%s':", os.getpid(), pidfile)
        log.error(" %s", e)


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
    if WIN32:
        return 0
    return 22

#warn just once:
MDNS_WARNING = False
def mdns_publish(display_name, mode, listen_on, text_dict={}):
    global MDNS_WARNING
    if MDNS_WARNING is True:
        return
    PREFER_PYBONJOUR = envbool("XPRA_PREFER_PYBONJOUR", False) or WIN32 or OSX
    try:
        from xpra.net import mdns
        assert mdns
        if PREFER_PYBONJOUR:
            from xpra.net.mdns.pybonjour_publisher import BonjourPublishers as MDNSPublishers, get_interface_index
        else:
            from xpra.net.mdns.avahi_publisher import AvahiPublishers as MDNSPublishers, get_interface_index
    except ImportError as e:
        MDNS_WARNING = True
        from xpra.log import Logger
        log = Logger("mdns")
        log("mdns import failure", exc_info=True)
        log.warn("Warning: failed to load the mdns %s publisher:", ["avahi", "pybonjour"][PREFER_PYBONJOUR])
        log.warn(" %s", e)
        log.warn(" either fix your installation or use the 'mdns=no' option")
        return
    d = text_dict.copy()
    d["mode"] = mode
    #ensure we don't have duplicate interfaces:
    f_listen_on = {}
    for host, port in listen_on:
        f_listen_on[get_interface_index(host)] = (host, port)
    try:
        name = socket.gethostname()
    except:
        name = "Xpra"
    if display_name and not (OSX or WIN32):
        name += " %s" % display_name
    if mode!="tcp":
        name += " (%s)" % mode
    ap = MDNSPublishers(f_listen_on.values(), name, text_dict=d)
    _when_ready.append(ap.start)
    _cleanups.append(ap.stop)


def create_unix_domain_socket(sockpath, mmap_group=False, socket_permissions="600"):
    from xpra.log import Logger
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
    try:
        inode = os.stat(sockpath).st_ino
    except:
        inode = -1
    #set to the "xpra" group if we are a member of it, or if running as root:
    uid = getuid()
    username = get_username_for_uid(uid)
    groups = get_groups(username)
    if uid==0 or "xpra" in groups:
        group_id = get_group_id("xpra")
        if group_id>=0:
            try:
                os.chown(sockpath, -1, group_id)
            except Exception as e:
                log = Logger("network")
                log.warn("Warning: failed to set 'xpra' group ownership")
                log.warn(" on socket '%s':", sockpath)
                log.warn(" %s", e)
            #don't know why this doesn't work:
            #os.fchown(listener.fileno(), -1, group_id)
    def cleanup_socket():
        log = Logger("network")
        try:
            cur_inode = os.stat(sockpath).st_ino
        except:
            log.info("socket '%s' already deleted", sockpath)
            return
        delpath = sockpath
        log("cleanup_socket '%s', original inode=%s, new inode=%s", sockpath, inode, cur_inode)
        if cur_inode==inode:
            log.info("removing socket %s", delpath)
            try:
                os.unlink(delpath)
            except:
                pass
    return listener, cleanup_socket

def create_tcp_socket(host, iport):
    from xpra.net.bytestreams import TCP_NODELAY
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
        log("create_tcp_socket%s", (host, iport), exc_info=True)
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
            if not port:
                iport = DEFAULT_PORT
            else:
                try:
                    iport = int(port)
                    assert iport>0 and iport<2**16
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
    pos = local_display_name.find(":")
    if pos<0:
        after_sc = local_display_name
        local_display_name = ":" + local_display_name
    else:
        after_sc = local_display_name[pos+1:]
    #we used to strip the screen from the display string, ie: ":0.0" -> ":0"
    #but now we allow it.. (untested!)
    for char in after_sc:
        assert char in "0123456789.", "invalid character in display name '%s': %s" % (local_display_name, char)
    return local_display_name


def setup_local_sockets(bind, socket_dir, socket_dirs, display_name, clobber, mmap_group=False, socket_permissions="600"):
    if not bind:
        return []
    if not socket_dir and (not socket_dirs or (len(socket_dirs)==1 and not socket_dirs[0])):
        raise InitException("at least one socket directory must be set to use unix domain sockets")
    dotxpra = DotXpra(socket_dir or socket_dirs[0], socket_dirs)
    display_name = normalize_local_display_name(display_name)
    from xpra.log import Logger
    defs = []
    log = Logger("network")
    try:
        sockpaths = []
        log("setup_local_sockets: bind=%s", bind)
        for b in bind:
            sockpath = b
            if b=="none" or b=="":
                continue
            elif b=="auto":
                sockpaths += dotxpra.norm_socket_paths(display_name)
                log("sockpaths(%s)=%s (uid=%i, gid=%i)", display_name, sockpaths, getuid(), getgid())
            else:
                sockpath = dotxpra.osexpand(b)
                if b.endswith("/") or (os.path.exists(sockpath) and os.path.isdir(sockpath)):
                    sockpath = os.path.abspath(sockpath)
                    if not os.path.exists(sockpath):
                        os.makedirs(sockpath)
                    sockpath = norm_makepath(sockpath, display_name)
                elif os.path.isabs(b):
                    sockpath = b
                else:
                    sockpath = dotxpra.socket_path(b)
                sockpaths += [sockpath]
            assert sockpaths, "no socket paths to try for %s" % b
        #expand and remove duplicate paths:
        tmp = []
        for tsp in sockpaths:
            sockpath = dotxpra.osexpand(tsp)
            if sockpath in tmp:
                log.warn("Warning: skipping duplicate bind path %s", sockpath)
                continue
            tmp.append(sockpath)
        sockpaths = tmp
        #create listeners:
        if WIN32:
            from xpra.platform.win32.namedpipes.listener import NamedPipeListener
            for sockpath in sockpaths:
                npl = NamedPipeListener(sockpath)
                log.info("created named pipe: %s", sockpath)
                defs.append((("named-pipe", npl, sockpath), npl.stop))
        else:
            def checkstate(sockpath, state):
                if state not in (DotXpra.DEAD, DotXpra.UNKNOWN):
                    raise InitException("You already have an xpra server running at %s\n"
                         "  (did you want 'xpra upgrade'?)"
                         % (sockpath,))
            #remove exisiting sockets if clobber is set,
            #otherwise verify there isn't a server already running
            #and create the directories for the sockets:
            unknown = []
            for sockpath in sockpaths:
                if clobber and os.path.exists(sockpath):
                    os.unlink(sockpath)
                else:
                    state = dotxpra.get_server_state(sockpath, 1)
                    log("state(%s)=%s", sockpath, state)
                    checkstate(sockpath, state)
                    if state==dotxpra.UNKNOWN:
                        unknown.append(sockpath)
                d = os.path.dirname(sockpath)
                try:
                    dotxpra.mksockdir(d)
                except Exception as e:
                    log.warn("Warning: failed to create socket directory '%s'", d)
                    log.warn(" %s", e)
            #wait for all the unknown ones:
            log("sockets in unknown state: %s", unknown)
            if unknown:
                #re-probe them using threads so we can do them in parallel:
                from time import sleep
                from xpra.make_thread import start_thread
                threads = []
                def timeout_probe(sockpath):
                    #we need a loop because "DEAD" sockets may return immediately
                    #(ie: when the server is starting up)
                    start = monotonic_time()
                    while monotonic_time()-start<WAIT_PROBE_TIMEOUT:
                        state = dotxpra.get_server_state(sockpath, WAIT_PROBE_TIMEOUT)
                        log("timeout_probe() get_server_state(%s)=%s", sockpath, state)
                        if state not in (DotXpra.UNKNOWN, DotXpra.DEAD):
                            break
                        sleep(1)
                log.warn("Warning: some of the sockets are in an unknown state:")
                for sockpath in unknown:
                    log.warn(" %s", sockpath)
                    t = start_thread(timeout_probe, "probe-%s" % sockpath, daemon=True, args=(sockpath,))
                    threads.append(t)
                log.warn(" please wait as we allow the socket probing to timeout")
                #wait for all the threads to do their job:
                for t in threads:
                    t.join(WAIT_PROBE_TIMEOUT+1)
            #now we can re-check quickly:
            #(they should all be DEAD or UNKNOWN):
            for sockpath in sockpaths:
                state = dotxpra.get_server_state(sockpath, 1)
                log("state(%s)=%s", sockpath, state)
                checkstate(sockpath, state)
                try:
                    if os.path.exists(sockpath):
                        os.unlink(sockpath)
                except:
                    pass
            #now try to create all the sockets:
            for sockpath in sockpaths:
                #create it:
                try:
                    sock, cleanup_socket = create_unix_domain_socket(sockpath, mmap_group, socket_permissions)
                    log.info("created unix domain socket: %s", sockpath)
                    defs.append((("unix-domain", sock, sockpath), cleanup_socket))
                except Exception as e:
                    handle_socket_error(sockpath, e)
    except:
        for sock, cleanup_socket in defs:
            try:
                cleanup_socket()
            except Exception as e:
                log.warn("error cleaning up socket %s", sock)
        defs = []
        raise
    return defs

def handle_socket_error(sockpath, e):
    from xpra.log import Logger
    log = Logger("network")
    log("socket creation error", exc_info=True)
    if sockpath.startswith("/var/run/xpra") or sockpath.startswith("/run/xpra"):
        log.warn("Warning: cannot create socket '%s'", sockpath)
        log.warn(" %s", e)
        dirname = sockpath[:sockpath.find("xpra")+len("xpra")]
        if not os.path.exists(dirname):
            log.warn(" %s does not exist", dirname)
        if os.name=="posix":
            uid = getuid()
            username = get_username_for_uid(uid)
            groups = get_groups(username)
            log.warn(" user '%s' is a member of groups: %s", username, csv(groups))
            if "xpra" not in groups:
                log.warn("  (missing 'xpra' group membership?)")
            try:
                import stat
                stat_info = os.stat(dirname)
                log.warn(" permissions on directory %s: %s", dirname, oct(stat.S_IMODE(stat_info.st_mode)))
                import pwd,grp      #@UnresolvedImport
                user = pwd.getpwuid(stat_info.st_uid)[0]
                group = grp.getgrgid(stat_info.st_gid)[0]
                log.warn("  ownership %s:%s", user, group)
            except:
                pass
    elif sockpath.startswith("/var/run/user") or sockpath.startswith("/run/user"):
        log.warn("Warning: cannot create socket '%s':", sockpath)
        log.warn(" %s", e)
        if not os.path.exists("/var/run/user"):
            log.warn(" %s does not exist", "/var/run/user")
        else:
            log.warn(" ($XDG_RUNTIME_DIR has not been created?)")
    else:
        log.error("Error: failed to create socket '%s':", sockpath)
        log.error(" %s", e)
        raise InitException("failed to create socket %s" % sockpath)


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
        try:
            os.rename(logpath, logpath + ".old")
        except:
            pass
    try:
        return os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
    except OSError as e:
        raise InitException("cannot open log file '%s': %s" % (logpath, e))

def select_log_file(log_dir, log_file, display_name):
    """ returns the log file path we should be using given the parameters,
        this may return a temporary logpath if display_name is not available.
    """
    if log_file:
        if os.path.isabs(log_file):
            logpath = log_file
        else:
            logpath = os.path.join(log_dir, log_file)
        v = shellsub(logpath, {"DISPLAY" : display_name})
        if display_name or v==logpath:
            #we have 'display_name', or we just don't need it:
            return v
    if display_name:
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

def start_Xvfb(xvfb_str, pixel_depth, display_name, cwd):
    if os.name!="posix":
        raise InitException("starting an Xvfb is not supported on %s" % os.name)
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
    import shlex
    xvfb_cmd = shlex.split(xvfb_str)
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
    subs = {
            "XAUTHORITY"    : xauthority,
            "USER"          : os.environ.get("USER", "unknown-user"),
            "UID"           : os.getuid(),
            "GID"           : os.getgid(),
            "HOME"          : os.environ.get("HOME", cwd),
            "DISPLAY"       : display_name,
            "XPRA_LOG_DIR"  : os.environ.get("XPRA_LOG_DIR"),
            }
    xvfb_str = shellsub(xvfb_str, subs)

    xvfb_cmd = xvfb_str.split()
    if not xvfb_cmd:
        raise InitException("cannot start Xvfb, the command definition is missing!")
    xvfb_executable = xvfb_cmd[0]
    if (xvfb_executable.endswith("Xorg") or xvfb_executable.endswith("Xdummy")) and pixel_depth>0:
        xvfb_cmd.append("-depth")
        xvfb_cmd.append(str(pixel_depth))
    if use_display_fd:
        # 'S' means that we allocate the display automatically
        r_pipe, w_pipe = os.pipe()
        xvfb_cmd += ["-displayfd", str(w_pipe)]
        xvfb_cmd[0] = "%s-for-Xpra-%s" % (xvfb_executable, display_name)
        def preexec():
            setsid()
            close_fds([0, 1, 2, r_pipe, w_pipe])
        #print("xvfb_cmd=%s" % (xvfb_cmd, ))
        xvfb = subprocess.Popen(xvfb_cmd, executable=xvfb_executable, close_fds=False,
                                stdin=subprocess.PIPE, preexec_fn=preexec, cwd=cwd)
        # Read the display number from the pipe we gave to Xvfb
        # waiting up to 10 seconds for it to show up
        limit = monotonic_time()+10
        buf = ""
        while monotonic_time()<limit and len(buf)<8:
            r, _, _ = select.select([r_pipe], [], [], max(0, limit-monotonic_time()))
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
    xauth_data = xauth_add(display_name)
    return xvfb, display_name, xauth_data

def xauth_add(display_name):
    from xpra.os_util import get_hex_uuid
    xauth_data = get_hex_uuid()
    xauth_cmd = ["xauth", "add", display_name, "MIT-MAGIC-COOKIE-1", xauth_data]
    try:
        code = subprocess.call(xauth_cmd)
        if code != 0:
            raise OSError("non-zero exit code: %s" % code)
    except OSError as e:
        #trying to continue anyway!
        sys.stderr.write("Error running \"%s\": %s\n" % (" ".join(xauth_cmd), e))
    return xauth_data

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
    import glib
    glib.threads_init()
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

def find_log_dir():
    from xpra.platform.paths import get_default_log_dirs
    errs  = []
    for x in get_default_log_dirs():
        v = osexpand(x)
        if not os.path.exists(v):
            try:
                os.mkdir(v, 0o700)
            except Exception as e:
                errs.append((v, e))
                continue
        return v
    for d, e in errs:
        sys.stderr.write("Error: cannot create log directory '%s':" % d)
        sys.stderr.write(" %s\n" % e)
    return None


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
    script = xpra_runner_shell_script(xpra_file, cwd, opts.socket_dir)

    if start_vfb or opts.daemon:
        #we will probably need a log dir
        #either for the vfb, or for our own log file
        log_dir = opts.log_dir or ""
        if not log_dir or log_dir.lower()=="auto":
            log_dir = find_log_dir()
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

    if opts.pidfile:
        write_pidfile(opts.pidfile)

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
            if opts.pulseaudio is not False:
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
    odisplay_name = display_name
    xvfb = None
    xvfb_pid = None
    xauth_data = None
    if start_vfb:
        assert not proxying
        try:
            pixel_depth = int(opts.pixel_depth)
        except ValueError as e:
            raise InitException("invalid value '%s' for pixel depth, must be a number" % opts.pixel_depth)
        if pixel_depth not in (8, 16, 24, 30):
            raise InitException("invalid pixel depth: %s" % pixel_depth)
        if not starting_desktop and pixel_depth==8:
            raise InitException("pixel depth 8 is only supported in 'start-desktop' mode")
        try:
            xvfb, display_name, xauth_data = start_Xvfb(opts.xvfb, pixel_depth, display_name, cwd)
        except OSError as e:
            log.error("Error starting Xvfb:")
            log.error(" %s", e)
            log("start_Xvfb error", exc_info=True)
            return  1
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
    PAM_OPEN = envbool("XPRA_PAM_OPEN")
    if os.name=="posix" and PAM_OPEN:
        try:
            from xpra.server.pam import pam_open, pam_close
        except ImportError as e:
            sys.stderr.write("No pam support: %s\n" % e)
        else:
            items = {
                   "XDISPLAY" : display_name
                   }
            if xauth_data:
                items["XAUTHDATA"] = xauth_data
            env = {
                   #"XDG_SEAT"               : "seat1",
                   #"XDG_VTNR"               : "0",
                   "XDG_SESSION_TYPE"       : "x11",
                   #"XDG_SESSION_CLASS"      : "user",
                   "XDG_SESSION_DESKTOP"    : "xpra",
                   }
            if pam_open(env=env, items=items):
                _cleanups.append(pam_close)

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
        mdns_info = {
                     "display"  : display_name,
                     "username" : get_username(),
                     "uuid"     : strtobytes(app.uuid),
                     "platform" : sys.platform,
                     "type"     : {"xpra" : "seamless", "xpra desktop" : "desktop"}.get(info, info),
                     }
        if opts.session_name:
            mdns_info["session"] = opts.session_name
        #reduce
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
