# This file is part of Parti.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# DO NOT IMPORT GTK HERE: see
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000041.html
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000042.html
# (also do not import anything that imports gtk)
import gobject
import subprocess
import sys
import os.path
import atexit
import signal
import socket

from xpra.wait_for_x_server import wait_for_x_server        #@UnresolvedImport
from xpra.dotxpra import DotXpra, ServerSockInUse

o0117 = 79
o0177 = 127
o0666 = 438
o0700 = 448

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
            import traceback
            traceback.print_exception(*sys.exc_info())

def deadly_signal(signum, frame):
    print("got deadly signal %s, exiting" % {signal.SIGINT:"SIGINT", signal.SIGTERM:"SIGTERM"}.get(signum, signum))
    run_cleanups()
    # This works fine in tests, but for some reason if I use it here, then I
    # get bizarre behavior where the signal handler runs, and then I get a
    # KeyboardException (?!?), and the KeyboardException is handled normally
    # and exits the program (causing the cleanup handlers to be run again):
    #signal.signal(signum, signal.SIG_DFL)
    #kill(os.getpid(), signum)
    os._exit(128 + signum)

# Note that this class has async subtleties -- e.g., it is possible for a
# child to exit and us to receive the SIGCHLD before our fork() returns (and
# thus before we even know the pid of the child).  So be careful:
class ChildReaper(object):
    def __init__(self, quit_cb, children_pids):
        self._quit = quit_cb
        self._children_pids = children_pids
        self._dead_pids = set()

    def check(self):
        if (self._children_pids
            and self._children_pids.issubset(self._dead_pids)):
            from wimpiggy.log import Logger
            log = Logger()
            log.info("all children have exited and --exit-with-children was specified, exiting")
            self._quit()

    def sigchld(self, signum, frame):
        self.reap()

    def add_dead_pid(self, pid):
        if pid not in self._dead_pids:
            self._dead_pids.add(pid)
            self.check()

    def reap(self):
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except OSError:
                break
            if pid == 0:
                break
            self.add_dead_pid(pid)

def save_pid(pid):
    import gtk
    import wimpiggy.prop
    wimpiggy.prop.prop_set(gtk.gdk.get_default_root_window(),
                           "_XPRA_SERVER_PID", "u32", pid)

def get_pid():
    import gtk
    import wimpiggy.prop
    return wimpiggy.prop.prop_get(gtk.gdk.get_default_root_window(),
                                  "_XPRA_SERVER_PID", "u32")

def sh_quotemeta(s):
    safe = ("abcdefghijklmnopqrstuvwxyz"
            + "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            + "0123456789"
            + "/._:,-+")
    quoted_chars = []
    for char in s:
        if char not in safe:
            quoted_chars.append("\\")
        quoted_chars.append(char)
    return "\"%s\"" % ("".join(quoted_chars),)

def xpra_runner_shell_script(xpra_file, starting_dir, socket_dir):
    script = []
    script.append("#!/bin/sh\n")
    for var, value in os.environ.items():
        # these aren't used by xpra, and some should not be exposed
        # as they are either irrelevant or simply do not match
        # the new environment used by xpra
        # TODO: use a whitelist
        if var in ["XDG_SESSION_COOKIE", "LS_COLORS"]:
            continue
        #XPRA_SOCKET_DIR is a special case, it is handled below
        if var=="XPRA_SOCKET_DIR":
            continue
        # :-separated envvars that people might change while their server is
        # going:
        if var in ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH"):
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

def create_unix_domain_socket(sockpath, mmap_group):
    listener = socket.socket(socket.AF_UNIX)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #bind the socket, using umask to set the correct permissions
    if mmap_group:
        orig_umask = os.umask(o0117) #660
    else:
        orig_umask = os.umask(o0177) #600
    listener.bind(sockpath)
    os.umask(orig_umask)
    return listener

def create_tcp_socket(parser, spec):
    if ":" not in spec:
        parser.error("TCP port must be specified as [HOST]:PORT")
    (host, port) = spec.split(":", 1)
    if host == "":
        host = "127.0.0.1"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, int(port)))
    return listener

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

def run_server(parser, opts, mode, xpra_file, extra_args):
    if len(extra_args) != 1:
        parser.error("need exactly 1 extra argument")
    assert mode in ("start", "upgrade", "shadow")
    upgrading = mode == "upgrade"
    shadowing = mode == "shadow"
    display_name = extra_args.pop(0)
    if display_name.startswith(":") and not shadowing:
        n = display_name[1:]
        p = n.find(".")
        if p>0:
            n = n[:p]
        try:
            dno = int(n)
            if dno>=0 and dno<10:
                sys.stderr.write("WARNING: low display number: %s\n" % dno)
                sys.stderr.write("You are attempting to run the xpra server against what seems to be a default X11 display '%s'.\n" % display_name)
                sys.stderr.write("This is generally not what you want.\n")
                sys.stderr.write("You should probably use a higher display number just to avoid any confusion (and also this warning message).\n")
        except:
            pass

    if opts.exit_with_children and not opts.children:
        sys.stderr.write("--exit-with-children specified without any children to spawn; exiting immediately")
        return  1

    atexit.register(run_cleanups)
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    from xpra.scripts.main import get_default_socket_dir
    dotxpra = DotXpra(opts.sockdir or get_default_socket_dir())

    # This used to be given a display-specific name, but now we give it a
    # single fixed name and if multiple servers are started then the last one
    # will clobber the rest.  This isn't great, but the tradeoff is that it
    # makes it possible to use bare 'ssh:hostname' display names and
    # autodiscover the proper numeric display name when only one xpra server
    # is running on the remote host.  Might need to revisit this later if
    # people run into problems or autodiscovery turns out to be less useful
    # than expected.
    scriptpath = os.path.join(dotxpra.confdir(), "run-xpra")

    # Save the starting dir now, because we'll lose track of it when we
    # daemonize:
    starting_dir = os.getcwd()

    # Daemonize:
    if opts.daemon:
        logpath = dotxpra.log_path(display_name) + ".log"
        sys.stderr.write("Entering daemon mode; "
                         + "any further errors will be reported to:\n"
                         + ("  %s\n" % logpath))
        # Do some work up front, so any errors don't get lost.
        if os.path.exists(logpath):
            os.rename(logpath, logpath + ".old")
        logfd = os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, o0666)
        assert logfd > 2
        os.chdir("/")

        if os.fork():
            os._exit(0)
        os.setsid()
        if os.fork():
            os._exit(0)
        close_all_fds(exceptions=[logfd])
        fd0 = os.open("/dev/null", os.O_RDONLY)
        if fd0 != 0:
            os.dup2(fd0, 0)
            os.close(fd0)
        os.dup2(logfd, 1)
        os.dup2(logfd, 2)
        os.close(logfd)
        # Make these line-buffered:
        sys.stdout = os.fdopen(1, "w", 1)
        sys.stderr = os.fdopen(2, "w", 1)

    # Write out a shell-script so that we can start our proxy in a clean
    # environment:
    scriptfile = open(scriptpath, "w")
    # Unix is a little silly sometimes:
    umask = os.umask(0)
    os.umask(umask)
    if hasattr(os, "fchmod"):
        os.fchmod(scriptfile.fileno(), o0700 & ~umask)
    else:
        os.chmod(scriptpath, o0700 & ~umask)
    scriptfile.write(xpra_runner_shell_script(xpra_file, starting_dir, opts.sockdir))
    scriptfile.close()

    from wimpiggy.log import Logger
    log = Logger()

    # Initialize the sockets before the display,
    # That way, errors won't make us kill the Xvfb
    # (which may not be ours to kill at that point)
    sockets = []
    if opts.bind_tcp:
        try:
            tcp_socket = create_tcp_socket(parser, opts.bind_tcp)
            sockets.append(tcp_socket)
            def cleanup_tcp_socket():
                log.info("closing tcp socket %s" % opts.bind_tcp)
                try:
                    tcp_socket.close()
                except:
                    pass
            _cleanups.append(cleanup_tcp_socket)
        except Exception, e:
            log.error("cannot start - failed to create tcp socket at %s: %s" % (opts.bind_tcp, e))
            return  1
    #print("creating server socket %s" % sockpath)
    clobber = upgrading or opts.use_display
    try:
        sockpath = dotxpra.server_socket_path(display_name, clobber, wait_for_unknown=5)
    except ServerSockInUse:
        parser.error("You already have an xpra server running at %s\n"
                     "  (did you want 'xpra upgrade'?)"
                     % (display_name,))
    sockets.append(create_unix_domain_socket(sockpath, opts.mmap_group))
    def cleanup_socket():
        log.info("removing socket %s", sockpath)
        try:
            os.unlink(sockpath)
        except:
            pass
    _cleanups.append(cleanup_socket)

    # Do this after writing out the shell script:
    os.environ["DISPLAY"] = display_name

    if not clobber and not shadowing:
        # We need to set up a new server environment
        xauthority = os.environ.get("XAUTHORITY", os.path.expanduser("~/.Xauthority"))
        subs = {"XAUTHORITY" : xauthority,
                "USER" : os.environ.get("USER", "unknown-user"),
                "HOME" : os.environ.get("HOME", os.getcwd()),
                "DISPLAY" : display_name}
        xvfb = opts.xvfb
        for var,value in subs.items():
            xvfb = xvfb.replace("$%s" % var, value)
            xvfb = xvfb.replace("${%s}" % var, value)
        xvfb_cmd = xvfb.split()
        xvfb_executable = xvfb_cmd[0]
        xvfb_cmd[0] = "%s-for-Xpra-%s" % (xvfb_executable, display_name)
        def setsid():
            #run in a new session
            if os.name=="posix":
                os.setsid()
        try:
            xvfb = subprocess.Popen(xvfb_cmd+[display_name], executable=xvfb_executable, close_fds=True, preexec_fn=setsid)
        except OSError, e:
            sys.stderr.write("Error starting Xvfb: %s\n" % (e,))
            return  1
        raw_cookie = os.urandom(16)
        baked_cookie = raw_cookie.encode("hex")
        xauth_cmd = ["xauth", "add", display_name, "MIT-MAGIC-COOKIE-1", baked_cookie]
        try:
            code = subprocess.call(xauth_cmd)
            if code != 0:
                raise OSError("non-zero exit code: %s" % code)
        except OSError, e:
            sys.stderr.write("Error running \"%s\": %s\n" % (" ".join(xauth_cmd), e))

    def xvfb_error(instance_exists=False):
        if clobber or shadowing:
            return False
        if xvfb.poll() is None:
            return False
        log.error("\n")
        log.error("Xvfb command has terminated! xpra cannot continue\n")
        log.error("\n")
        if instance_exists:
            log.error("There is an X11 server already running on display %s:\n" % display_name)
            log.error("You may want to use:\n")
            log.error("  'xpra upgrade' if an instance of xpra is still connected to it\n")
            log.error("  'xpra --use-display start' to connect xpra to an existing X11 server only\n")
        return True

    if xvfb_error():
        return  1
    # Whether we spawned our server or not, it is now running -- or at least
    # starting.  First wait for it to start up:
    try:
        wait_for_x_server(display_name, 3) # 3s timeout
    except Exception, e:
        sys.stderr.write("%s\n" % e)
        return  1
    if xvfb_error(True):
        return  1
    # Now we can safely load gtk and connect:
    assert "gtk" not in sys.modules
    import gtk
    display = gtk.gdk.Display(display_name)
    manager = gtk.gdk.display_manager_get()
    default_display = manager.get_default_display()
    if default_display is not None:
        default_display.close()
    manager.set_default_display(display)

    if shadowing:
        xvfb_pid = None
    elif clobber:
        xvfb_pid = get_pid()
    else:
        if xvfb_error(True):
            return  1
        xvfb_pid = xvfb.pid
        if xvfb_pid is not None:
            save_pid(xvfb_pid)

    def kill_xvfb():
        # Close our display(s) first, so the server dying won't kill us.
        log.info("killing xvfb with pid %s" % xvfb_pid)
        for display in gtk.gdk.display_manager_get().list_displays():
            display.close()
        os.kill(xvfb_pid, signal.SIGTERM)
    if xvfb_pid is not None and not opts.use_display and not shadowing:
        _cleanups.append(kill_xvfb)

    if shadowing:
        from xpra.shadow_server import XpraShadowServer
        app = XpraShadowServer(sockets, opts)
    else:
        try:
            from wimpiggy.lowlevel import displayHasXComposite     #@UnresolvedImport
            # This import is delayed because the module depends on gtk:
            from xpra.server import XpraServer
        except ImportError, e:
            log.error("Failed to load Xpra server components, check your installation: %s" % e)
            return 1
        root = gtk.gdk.get_default_root_window()
        if not displayHasXComposite(root):
            log.error("Xpra is a compositing manager, it cannot use a display which lacks the XComposite extension!")
            return 1

        app = XpraServer(clobber, sockets, opts)

    children_pids = set()
    procs = []
    if opts.exit_with_children:
        def reaper_quit():
            app.quit(False)
        child_reaper = ChildReaper(reaper_quit, children_pids)
        if sys.version_info < (2, 7) or sys.version_info[:2] == (3, 0):
                POLL_DELAY = int(os.environ.get("XPRA_POLL_DELAY", 2))
                log.warn("Warning: outdated/buggy version of Python (%s), switching to process polling every %s seconds to support 'exit-with-children'", ".".join(str(x) for x in sys.version_info), POLL_DELAY)
                ChildReaper.processes = procs
                def check_procs():
                    for proc in ChildReaper.processes:
                        if proc.poll() is not None:
                            child_reaper.add_dead_pid(proc.pid)
                            child_reaper.check()
                    ChildReaper.processes = [proc for proc in ChildReaper.processes if proc.poll() is None]
                    return True
                gobject.timeout_add(POLL_DELAY*1000, check_procs)
        else:
            #with non-buggy python, we can just check the list of pids
            #whenever we get a SIGCHLD
            signal.signal(signal.SIGCHLD, child_reaper.sigchld)
            # Check once after the mainloop is running, just in case the exit
            # conditions are satisfied before we even enter the main loop.
            # (Programming with unix the signal API sure is annoying.)
            def check_once():
                child_reaper.check()
                return False # Only call once
            gobject.timeout_add(0, check_once)

    if not upgrading and not shadowing and opts.pulseaudio and len(opts.pulseaudio_command)>0:
        pa_proc = subprocess.Popen(opts.pulseaudio_command, shell=True, close_fds=True)
        log.info("pulseaudio server started with pid %s", pa_proc.pid)
    if opts.exit_with_children:
        assert opts.children
    if opts.children:
        #disable ubuntu's global menu using env vars:
        env = os.environ.copy()
        env["UBUNTU_MENUPROXY"] = ""
        env["QT_X11_NO_NATIVE_MENUBAR"] = "1"
        for child_cmd in opts.children:
            if child_cmd:
                try:
                    proc = subprocess.Popen(child_cmd, env=env, shell=True, close_fds=True)
                    children_pids.add(proc.pid)
                    procs.append(proc)
                except OSError, e:
                    sys.stderr.write("Error spawning child '%s': %s\n"
                                     % (child_cmd, e))

    _cleanups.insert(0, app.cleanup)
    signal.signal(signal.SIGTERM, app.signal_quit)
    signal.signal(signal.SIGINT, app.signal_quit)
    try:
        e = app.run()
    except KeyboardInterrupt:
        e = 0
    if e>0:
        log.info("upgrading: not cleaning up Xvfb or socket")
        # Upgrading, so leave X server running
        # and don't delete the new socket (not ours)
        if kill_xvfb in _cleanups:
            _cleanups.remove(kill_xvfb)
        _cleanups.remove(cleanup_socket)
    return  0
