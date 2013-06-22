# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
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
    def __init__(self, quit_cb, children_pids={}):
        self._quit = quit_cb
        self._children_pids = children_pids
        self._dead_pids = set()
        from xpra.log import Logger
        self._logger = Logger()

    def check(self):
        if self._children_pids:
            pids = set(self._children_pids.keys())
            if pids.issubset(self._dead_pids):
                self._quit()

    def sigchld(self, signum, frame):
        self.reap()

    def add_dead_pid(self, pid):
        if pid not in self._dead_pids:
            cmd = self._children_pids.get(pid)
            if cmd:
                self._logger.info("child '%s' with pid %s has terminated", cmd, pid)
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
    from xpra.x11.gtk_x11.prop import prop_set
    prop_set(gtk.gdk.get_default_root_window(),
                           "_XPRA_SERVER_PID", "u32", pid)

def get_pid():
    import gtk
    from xpra.x11.gtk_x11.prop import prop_get
    return prop_get(gtk.gdk.get_default_root_window(),
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
        if var in ["XDG_SESSION_COOKIE", "LS_COLORS", "DISPLAY"]:
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
    (host, port) = spec.rsplit(":", 1)
    if host == "":
        host = "127.0.0.1"
    try:
        iport = int(port)
    except:
        raise Exception("invalid port number: %s" % port)
    if host.find(":")<0:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockaddr = (host, iport)
    else:
        assert socket.has_ipv6, "specified an IPv6 address but this is not supported"
        res = socket.getaddrinfo(host, iport, socket.AF_INET6, socket.SOCK_STREAM, 0, socket.SOL_TCP)
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sockaddr = res[0][-1]
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(sockaddr)
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
    if opts.encoding and opts.encoding=="help":
        from xpra.scripts.config import encodings_help
        from xpra.server.server_base import SERVER_ENCODINGS
        print("server supports the following encodings:\n * %s" % ("\n * ".join(encodings_help(SERVER_ENCODINGS))))
        return 0
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

    if not shadowing and opts.exit_with_children and not opts.start_child:
        sys.stderr.write("--exit-with-children specified without any children to spawn; exiting immediately")
        return  1

    atexit.register(run_cleanups)
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    dotxpra = DotXpra(opts.socket_dir)

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
        if opts.log_file:
            if os.path.isabs(opts.log_file):
                logpath = opts.log_file
            else:
                logpath = os.path.join(dotxpra.sockdir(), opts.log_file)
            logpath = logpath.replace("$DISPLAY", display_name)
        else:
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
    scriptfile.write(xpra_runner_shell_script(xpra_file, starting_dir, opts.socket_dir))
    scriptfile.close()

    from xpra.log import Logger
    log = Logger()

    # Initialize the sockets before the display,
    # That way, errors won't make us kill the Xvfb
    # (which may not be ours to kill at that point)
    sockets = []
    if opts.bind_tcp and len(opts.bind_tcp):
        def setup_tcp_socket(bind_to):
            try:
                tcp_socket = create_tcp_socket(parser, bind_to)
                sockets.append(("tcp", tcp_socket))
                def cleanup_tcp_socket():
                    log.info("closing tcp socket %s", bind_to)
                    try:
                        tcp_socket.close()
                    except:
                        pass
                _cleanups.append(cleanup_tcp_socket)
            except Exception, e:
                log.error("cannot start - failed to create tcp socket at %s : %s" % (bind_to, e))
                return  1
        for tcp_s in set(opts.bind_tcp):
            setup_tcp_socket(tcp_s)

    clobber = upgrading or opts.use_display
    if not sys.platform.startswith("win"):
        #print("creating server socket %s" % sockpath)
        try:
            sockpath = dotxpra.server_socket_path(display_name, clobber, wait_for_unknown=5)
        except ServerSockInUse:
            parser.error("You already have an xpra server running at %s\n"
                         "  (did you want 'xpra upgrade'?)"
                         % (display_name,))
        sock = create_unix_domain_socket(sockpath, opts.mmap_group)
        sockets.append(("unix-domain", sock))
        def cleanup_socket():
            log.info("removing socket %s", sockpath)
            try:
                os.unlink(sockpath)
            except:
                pass
        _cleanups.append(cleanup_socket)

    # Do this after writing out the shell script:
    os.environ["DISPLAY"] = display_name
    def unsetenv(*varnames):
        for x in varnames:
            if os.environ.get(x):
                del os.environ[x]
    #we don't want client apps to think these mean anything:
    #(if set, they belong to the desktop the server was started from)
    #TODO: simply whitelisting the env would be safer/better
    unsetenv("DESKTOP_SESSION",
             "GDMSESSION",
             "SESSION_MANAGER",
             "XDG_VTNR",
             "XDG_MENU_PREFIX",
             "XDG_SEAT",
             #"XDG_RUNTIME_DIR",
             "QT_GRAPHICSSYSTEM_CHECKED",
             )
    #force 'simple' / 'xim', as 'ibus' 'immodule' breaks keyboard handling
    #unless its daemon is also running - and we don't know if it is..
    #this should override any XSETTINGS too.
    os.environ["DISABLE_IMSETTINGS"] = "true"
    os.environ["GTK_IM_MODULE"] = "xim"                     #or "gtk-im-context-simple"?
    os.environ["QT_IM_MODULE"] = "xim"                      #or "simple"?
    os.environ["IMSETTINGS_MODULE"] = "none"                #or "xim"?
    os.environ["XMODIFIERS"] = ""

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
            xvfb = subprocess.Popen(xvfb_cmd+[display_name], executable=xvfb_executable, close_fds=True,
                                    stdin=subprocess.PIPE, preexec_fn=setsid)
        except OSError, e:
            sys.stderr.write("Error starting Xvfb: %s\n" % (e,))
            return  1
        from xpra.os_util import get_hex_uuid
        xauth_cmd = ["xauth", "add", display_name, "MIT-MAGIC-COOKIE-1", get_hex_uuid()]
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
        log.error("")
        log.error("Xvfb command has terminated! xpra cannot continue")
        log.error("")
        if instance_exists:
            log.error("There is an X11 server already running on display %s:" % display_name)
            log.error("You may want to use:")
            log.error("  'xpra upgrade %s' if an instance of xpra is still connected to it" % display_name)
            log.error("  'xpra --use-display start %s' to connect xpra to an existing X11 server only" % display_name)
            log.error("")
        return True

    if xvfb_error():
        return  1

    if not sys.platform.startswith("win") and not sys.platform.startswith("darwin"):
        from xpra.x11.bindings.wait_for_x_server import wait_for_x_server        #@UnresolvedImport
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
        import gtk.gdk          #@Reimport
        gtk.gdk.threads_init()
        display = gtk.gdk.Display(display_name)
        manager = gtk.gdk.display_manager_get()
        default_display = manager.get_default_display()
        if default_display is not None:
            default_display.close()
        manager.set_default_display(display)
    else:
        assert "gtk" not in sys.modules
        import gtk          #@Reimport

    if shadowing:
        xvfb_pid = None     #we don't own the display
        from xpra.platform.shadow_server import ShadowServer
        app = ShadowServer()
        app.init(sockets, opts)
    else:
        from xpra.x11.gtk_x11 import gdk_display_source
        assert gdk_display_source

        if clobber:
            #get the saved pid:
            xvfb_pid = get_pid()
        else:
            #check that the vfb has started ok:
            if xvfb_error(True):
                return  1
            xvfb_pid = xvfb.pid

        #check for an existing window manager:
        from xpra.x11.gtk_x11.wm import wm_check
        if not wm_check(display):
            return 1
        try:
            # This import is delayed because the module depends on gtk:
            from xpra.x11.server import XpraServer
            from xpra.x11.bindings.window_bindings import X11WindowBindings     #@UnresolvedImport
            X11Window = X11WindowBindings()
        except ImportError, e:
            log.error("Failed to load Xpra server components, check your installation: %s" % e)
            return 1
        if not X11Window.displayHasXComposite():
            log.error("Xpra is a compositing manager, it cannot use a display which lacks the XComposite extension!")
            return 1
        app = XpraServer()
        app.init(clobber, sockets, opts)


    if xvfb_pid is not None:
        save_pid(xvfb_pid)
    #we got this far so the sockets have initialized and
    #the server should be able to manage the display
    #from now on, if we exit without upgrading we will also kill the Xvfb
    def kill_xvfb():
        # Close our display(s) first, so the server dying won't kill us.
        log.info("killing xvfb with pid %s" % xvfb_pid)
        for display in gtk.gdk.display_manager_get().list_displays():
            display.close()
        os.kill(xvfb_pid, signal.SIGTERM)
    if xvfb_pid is not None and not opts.use_display and not shadowing:
        _cleanups.append(kill_xvfb)

    children_pids = {}
    def reaper_quit():
        if opts.exit_with_children:
            log.info("all children have exited and --exit-with-children was specified, exiting")
            gobject.idle_add(app.clean_quit)

    procs = []
    if os.name=="posix":
        child_reaper = ChildReaper(reaper_quit, children_pids)
        old_python = sys.version_info < (2, 7) or sys.version_info[:2] == (3, 0)
        if old_python:
            POLL_DELAY = int(os.environ.get("XPRA_POLL_DELAY", 2))
            log.warn("Warning: outdated/buggy version of Python: %s", ".".join(str(x) for x in sys.version_info))
            log.warn("switching to process polling every %s seconds to support 'exit-with-children'", POLL_DELAY)
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

        log("upgrading=%s, shadowing=%s, pulseaudio=%s, pulseaudio_command=%s",
                 upgrading, shadowing, opts.pulseaudio, opts.pulseaudio_command)
        if not upgrading and not shadowing and opts.pulseaudio and len(opts.pulseaudio_command)>0:
            pa_proc = subprocess.Popen(opts.pulseaudio_command, stdin=subprocess.PIPE, shell=True, close_fds=True)
            procs.append(pa_proc)
            log.info("pulseaudio server started with pid %s", pa_proc.pid)
            def check_pa_start():
                if pa_proc.poll() is not None or pa_proc.pid in child_reaper._dead_pids:
                    log.warn("Warning: pulseaudio has terminated. Either fix the pulseaudio command line or use --no-pulseaudio to avoid this warning.")
                return False
            gobject.timeout_add(1000*2, check_pa_start)
            def cleanup_pa():
                log("cleanup_pa() process.poll()=%s, pid=%s, dead_pids=%s", pa_proc.poll(), pa_proc.pid, child_reaper._dead_pids)
                if pa_proc.poll() is None and pa_proc.pid not in child_reaper._dead_pids:
                    log.info("stopping pulseaudio with pid %s", pa_proc.pid)
                    try:
                        pa_proc.terminate()
                    except:
                        log.warn("error trying to stop pulseaudio", exc_info=True)
            _cleanups.append(cleanup_pa)
    if opts.exit_with_children:
        assert opts.start_child
    if opts.start_child:
        assert os.name=="posix"
        #disable ubuntu's global menu using env vars:
        env = os.environ.copy()
        if os.name=="posix":
            env["UBUNTU_MENUPROXY"] = ""
            env["QT_X11_NO_NATIVE_MENUBAR"] = "1"
        for child_cmd in opts.start_child:
            if child_cmd:
                try:
                    proc = subprocess.Popen(child_cmd, stdin=subprocess.PIPE, env=env, shell=True, close_fds=True)
                    children_pids[proc.pid] = child_cmd
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
    except Exception, e:
        log.error("server error", exc_info=True)
        e = 128
    if e>0:
        log.info("upgrading: not cleaning up Xvfb or socket")
        # Upgrading, so leave X server running
        # and don't delete the new socket (not ours)
        if kill_xvfb in _cleanups:
            _cleanups.remove(kill_xvfb)
        _cleanups.remove(cleanup_socket)
    return  0
