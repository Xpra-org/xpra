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

from xpra.scripts.main import no_gtk
from xpra.scripts.config import InitException, get_Xdummy_confdir
from xpra.os_util import setsid, shellsub, monotonic_time, close_fds, setuidgid, getuid, getgid, strtobytes, POSIX


DEFAULT_VFB_RESOLUTION = tuple(int(x) for x in os.environ.get("XPRA_DEFAULT_VFB_RESOLUTION", "8192x4096").replace(",", "x").split("x", 1))
assert len(DEFAULT_VFB_RESOLUTION)==2
DEFAULT_DESKTOP_VFB_RESOLUTION = tuple(int(x) for x in os.environ.get("XPRA_DEFAULT_DESKTOP_VFB_RESOLUTION", "1280x1024").replace(",", "x").split("x", 1))
assert len(DEFAULT_DESKTOP_VFB_RESOLUTION)==2


XORG_MATCH_OPTIONS = {
    "pointer"   : """
    MatchIsPointer "True"
    Driver "libinput"
    Option "AccelProfile" "flat"
""",
    "keyboard"  : 'MatchIsKeyboard "True"',
    }


def create_xorg_device_configs(xorg_conf_dir, devices, uid, gid):
    from xpra.log import Logger
    log = Logger("server", "x11")
    cleanups = []
    if not devices:
        return cleanups

    def makedir(dirname):
        log("makedir(%s)", dirname)
        os.mkdir(dirname)
        os.lchown(dirname, uid, gid)
        def cleanup_dir():
            try:
                log("cleanup_dir() %s", dirname)
                os.rmdir(dirname)
            except Exception as e:
                log("failed to cleanup %s: %s", dirname, e)
        cleanups.insert(0, cleanup_dir)
    
    #create conf dir if needed:
    d = xorg_conf_dir
    dirs = []
    while d and not os.path.exists(d):
        log("create_device_configs: dir does not exist: %s", d)
        dirs.insert(0, d)
        d = os.path.dirname(d)
    for d in dirs:
        makedir(d)

    #create individual device files:
    i = 0
    for dev_type, devdef in devices.items():
        #ie:
        #name = "pointer"
        #devdef = {"uinput" : uninput.Device, "device" : "/dev/input20" }
        match_type = XORG_MATCH_OPTIONS.get(dev_type)
        uinput = devdef.get("uinput")
        device = devdef.get("device")
        name = devdef.get("name")
        if match_type and uinput and device and name:
            conf_file = os.path.join(xorg_conf_dir, "%02i-%s.conf" % (i, dev_type))
            with open(conf_file, "wb") as f:
                f.write("""
Section "InputClass"
    Identifier "xpra-virtual-%s"
    MatchProduct "%s"
    Option "Ignore" "False"
%s
EndSection
""" % (dev_type, name, match_type))
                os.fchown(f.fileno(), uid, gid)
                #Option "AccelerationProfile" "-1"
                #Option "AccelerationScheme" "none"
                #Option "AccelSpeed" "-1"
            def cleanup_conf_file():
                log("cleanup_conf_file: %s", conf_file)
                os.unlink(conf_file) 
            cleanups.insert(0, cleanup_conf_file)
    return cleanups


def start_Xvfb(xvfb_str, pixel_depth, display_name, cwd, uid, gid, username, xauth_data, devices={}):
    if not POSIX:
        raise InitException("starting an Xvfb is not supported on %s" % os.name)
    if not xvfb_str:
        raise InitException("the 'xvfb' command is not defined")

    from xpra.platform.xposix.paths import _get_runtime_dir
    from xpra.log import Logger
    log = Logger("server", "x11")

    # We need to set up a new server environment
    xauthority = os.environ.get("XAUTHORITY", os.path.expanduser("~/.Xauthority"))
    if not os.path.exists(xauthority):
        log("creating XAUTHORITY=%s with data=%s", xauthority, xauth_data)
        try:
            with open(xauthority, 'wa') as f:
                if getuid()==0 and (uid!=0 or gid!=0):
                    os.fchown(f.fileno(), uid, gid)
        except Exception as e:
            #trying to continue anyway!
            log.error("Error trying to create XAUTHORITY file %s:", xauthority)
            log.error(" %s", e)
    use_display_fd = display_name[0]=='S'

    HOME = os.path.expanduser("~%s" % username)
    subs = {
            "XAUTHORITY"        : xauthority,
            "USER"              : username or os.environ.get("USER", "unknown-user"),
            "UID"               : uid,
            "GID"               : gid,
            "PID"               : os.getpid(),
            "HOME"              : HOME,
            "DISPLAY"           : display_name,
            "XDG_RUNTIME_DIR"   : os.environ.get("XDG_RUNTIME_DIR", _get_runtime_dir()),
            "XPRA_LOG_DIR"      : os.environ.get("XPRA_LOG_DIR"),
            }
    def pathexpand(s):
        return shellsub(s, subs)

    #create uinput device definition files:
    #(we are assuming that Xorg is configured to use this path..)
    xorg_conf_dir = pathexpand(get_Xdummy_confdir())
    cleanups = create_xorg_device_configs(xorg_conf_dir, devices, uid, gid)

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
        xorg_log_dir = os.path.dirname(pathexpand(xvfb_cmd[logfile_argindex+1]))
        log("xorg_log_dir=%s - exists=%s", xorg_log_dir, os.path.exists(xorg_log_dir))
        if not os.path.exists(xorg_log_dir):
            try:
                log("creating Xorg log dir '%s'", xorg_log_dir)
                os.mkdir(xorg_log_dir, 0o700)
                if POSIX and uid!=getuid() or gid!=getgid():
                    try:
                        os.lchown(xorg_log_dir, uid, gid)
                    except:
                        pass
            except OSError as e:
                raise InitException("failed to create the Xorg log directory '%s': %s" % (xorg_log_dir, e))

    #apply string substitutions:
    xvfb_cmd = pathexpand(xvfb_str).split()

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
            if POSIX and getuid()==0 and uid:
                setuidgid(uid, gid)
            close_fds([0, 1, 2, r_pipe, w_pipe])
        log("xvfb_cmd=%s", xvfb_cmd)
        xvfb = subprocess.Popen(xvfb_cmd, executable=xvfb_executable, close_fds=False,
                                stdin=subprocess.PIPE, preexec_fn=preexec, cwd=cwd)
        # Read the display number from the pipe we gave to Xvfb
        # waiting up to 10 seconds for it to show up
        limit = monotonic_time()+10
        buf = ""
        import select   #@UnresolvedImport
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
        log("Using display number provided by %s: %s", xvfb_executable, new_display_name)
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
        log("xvfb_cmd=%s", xvfb_cmd)
        xvfb = subprocess.Popen(xvfb_cmd, executable=xvfb_executable, close_fds=True,
                                stdin=subprocess.PIPE, preexec_fn=preexec)
    xauth_add(display_name, xauth_data)
    log("xvfb process=%s", xvfb)
    log("display_name=%s", display_name)
    return xvfb, display_name, cleanups


def set_initial_resolution(desktop=False):
    from xpra.log import Logger
    try:
        log = Logger("server")
        log("set_initial_resolution")
        if desktop:
            res = DEFAULT_DESKTOP_VFB_RESOLUTION
        else:
            res = DEFAULT_VFB_RESOLUTION
        from xpra.x11.bindings.randr_bindings import RandRBindings      #@UnresolvedImport
        #try to set a reasonable display size:
        randr = RandRBindings()
        if not randr.has_randr():
            l = log
            if desktop:
                l = log.warn
            l("Warning: no RandR support,")
            l(" default virtual display size unchanged")
            return
        sizes = randr.get_screen_sizes()
        size = randr.get_screen_size()
        log("RandR available, current size=%s, sizes available=%s", size, sizes)
        if res in sizes:
            log("RandR setting new screen size to %s", res)
            randr.set_screen_size(*res)
    except Exception as e:
        log("set_initial_resolution(%s)", desktop, exc_info=True)
        log.error("Error: failed to set the default screen size:")
        log.error(" %s", e)


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
        wait_for_x_server(strtobytes(display_name), 3) # 3s timeout
    except Exception as e:
        from xpra.log import Logger
        log = Logger("server")
        log("verify_display_ready%s", (xvfb, display_name, shadowing_check), exc_info=True)
        log.error("Error: failed to connect to display %s" % display_name)
        log.error(" %s", e)
        return False
    if shadowing_check and not check_xvfb_process(xvfb):
        #if we're here, there is an X11 server, but it isn't the one we started!
        from xpra.log import Logger     #@Reimport
        log = Logger("server")
        log.error("There is an X11 server already running on display %s:" % display_name)
        log.error("You may want to use:")
        log.error("  'xpra upgrade %s' if an instance of xpra is still connected to it" % display_name)
        log.error("  'xpra --use-display start %s' to connect xpra to an existing X11 server only" % display_name)
        log.error("")
        return False
    return True
