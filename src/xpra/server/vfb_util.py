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
import select

from xpra.scripts.main import no_gtk
from xpra.scripts.config import InitException
from xpra.os_util import setsid, shellsub, monotonic_time, close_fds, setuidgid, getuid, getgid
from xpra.platform.dotxpra import osexpand


DEFAULT_VFB_RESOLUTION = tuple(int(x) for x in os.environ.get("XPRA_DEFAULT_VFB_RESOLUTION", "8192x4096").replace(",", "x").split("x", 1))


def start_Xvfb(xvfb_str, pixel_depth, display_name, cwd, uid, gid, xauth_data):
    if os.name!="posix":
        raise InitException("starting an Xvfb is not supported on %s" % os.name)
    if not xvfb_str:
        raise InitException("the 'xvfb' command is not defined")
    # We need to set up a new server environment
    xauthority = os.environ.get("XAUTHORITY", os.path.expanduser("~/.Xauthority"))
    if not os.path.exists(xauthority):
        try:
            with open(xauthority, 'wa') as f:
                if getuid()==0 and (uid!=0 or gid!=0):
                    os.fchown(f.fileno(), uid, gid)
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
                if os.name=="posix" and uid!=getuid() or gid!=getgid():
                    try:
                        os.chown(xorg_log_dir, uid, gid)
                    except:
                        pass
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
            if os.name=="posix" and getuid()==0 and uid:
                setuidgid(uid, gid)
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
            raise InitException("%s did not provide a display number using -displayfd" % xvfb_executable)
        if buf[-1] != '\n':
            raise InitException("%s output not terminated by newline: %s" % (xvfb_executable, buf))
        try:
            n = int(buf[:-1])
        except:
            raise InitException("%s display number is not a valid number: %s" % (xvfb_executable, buf[:-1]))
        if n<0 or n>=2**16:
            raise InitException("%s provided an invalid display number: %s" % (xvfb_executable, n))
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
        def preexec():
            if getuid()==0 and (uid!=0 or gid!=0):
                setuidgid(uid, gid)
            else:
                setsid()
        xvfb = subprocess.Popen(xvfb_cmd, executable=xvfb_executable, close_fds=True,
                                stdin=subprocess.PIPE, preexec_fn=preexec)
    xauth_add(display_name, xauth_data)
    return xvfb, display_name


def set_initial_resolution():
    try:
        from xpra.log import Logger
        log = Logger("server")
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


def xauth_add(display_name, xauth_data):
    xauth_cmd = ["xauth", "add", display_name, "MIT-MAGIC-COOKIE-1", xauth_data]
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
    import glib
    glib.threads_init()
    display = gtk.gdk.Display(display_name)
    manager = gtk.gdk.display_manager_get()
    default_display = manager.get_default_display()
    if default_display is not None and default_display!=display:
        default_display.close()
    manager.set_default_display(display)
    return display
