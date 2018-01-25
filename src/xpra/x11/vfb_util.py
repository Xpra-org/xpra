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

from xpra.scripts.config import InitException, get_Xdummy_confdir
from xpra.os_util import setsid, shellsub, close_fds, setuidgid, getuid, getgid, strtobytes, osexpand, POSIX
from xpra.platform.displayfd import read_displayfd, parse_displayfd


DEFAULT_VFB_RESOLUTION = tuple(int(x) for x in os.environ.get("XPRA_DEFAULT_VFB_RESOLUTION", "8192x4096").replace(",", "x").split("x", 1))
assert len(DEFAULT_VFB_RESOLUTION)==2
DEFAULT_DESKTOP_VFB_RESOLUTION = tuple(int(x) for x in os.environ.get("XPRA_DEFAULT_DESKTOP_VFB_RESOLUTION", "1280x1024").replace(",", "x").split("x", 1))
assert len(DEFAULT_DESKTOP_VFB_RESOLUTION)==2


vfb_logger = None
def _vfb_logger():
    global vfb_logger
    if not vfb_logger:
        from xpra.log import Logger
        vfb_logger = Logger("server", "x11")
    return vfb_logger


def create_xorg_device_configs(xorg_conf_dir, device_uuid, uid, gid):
    log = _vfb_logger()
    log("create_xorg_device_configs(%s, %s, %i, %i)", xorg_conf_dir, device_uuid, uid, gid)
    cleanups = []
    if not device_uuid:
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

    #create individual device files,
    #only pointer for now:
    i = 0
    dev_type = "pointer"
    name = "Xpra Virtual Pointer %s" % device_uuid
    conf_file = os.path.join(xorg_conf_dir, "%02i-%s.conf" % (i, dev_type))
    with open(conf_file, "wb") as f:
        f.write(b"""Section "InputClass"
    Identifier "xpra-virtual-%s"
    MatchProduct "%s"
    MatchUSBID "ffff:ffff"
    MatchIsPointer "True"
    Driver "libinput"
    Option "AccelProfile" "flat"
    Option "Ignore" "False"
EndSection
""" % (dev_type, name))
        os.fchown(f.fileno(), uid, gid)
        #Option "AccelerationProfile" "-1"
        #Option "AccelerationScheme" "none"
        #Option "AccelSpeed" "-1"
    def cleanup_conf_file():
        log("cleanup_conf_file: %s", conf_file)
        os.unlink(conf_file)
    cleanups.insert(0, cleanup_conf_file)
    return cleanups

def start_Xvfb(xvfb_str, pixel_depth, display_name, cwd, uid, gid, username, xauth_data, uinput_uuid=None):
    if not POSIX:
        raise InitException("starting an Xvfb is not supported on %s" % os.name)
    if not xvfb_str:
        raise InitException("the 'xvfb' command is not defined")

    log = _vfb_logger()
    log("start_Xvfb%s", (xvfb_str, pixel_depth, display_name, cwd, uid, gid, username, xauth_data, uinput_uuid))

    subs = {}
    def pathexpand(s):
        return osexpand(s, actual_username=username, uid=uid, gid=gid, subs=subs)

    # We need to set up a new server environment
    xauthority = os.environ.get("XAUTHORITY", pathexpand("~/.Xauthority"))
    subs["XAUTHORITY"] = xauthority
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
    else:
        log("found existing XAUTHORITY file '%s'", xauthority)
    use_display_fd = display_name[0]=='S'
    subs["DISPLAY"] = display_name
    subs["XPRA_LOG_DIR"] = pathexpand(os.environ.get("XPRA_LOG_DIR"))

    #identify logfile argument if it exists,
    #as we may have to rename it, or create the directory for it:
    import shlex
    xvfb_cmd = shlex.split(xvfb_str)
    if not xvfb_cmd:
        raise InitException("cannot start Xvfb, the command definition is missing!")
    #make sure all path values are expanded:
    xvfb_cmd = [pathexpand(s) for s in xvfb_cmd]

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

    cleanups = []
    if uinput_uuid:
        #use uinput:
        #identify -config xorg.conf argument and replace it with the uinput one:
        try:
            config_argindex = xvfb_cmd.index("-config")
        except ValueError as e:
            log.warn("Warning: cannot use uinput")
            log.warn(" '-config' argument not found in the xvfb command")
        else:
            assert config_argindex+1<len(xvfb_cmd), "invalid xvfb command string: -config should not be last (found at index %i)" % config_argindex
            xorg_conf = xvfb_cmd[config_argindex+1]
            if xorg_conf.endswith("xorg.conf"):
                xorg_conf = xorg_conf.replace("xorg.conf", "xorg-uinput.conf")
                if os.path.exists(xorg_conf):
                    xvfb_cmd[config_argindex+1] = xorg_conf
            #create uinput device definition files:
            #(we have to assume that Xorg is configured to use this path..)
            xorg_conf_dir = pathexpand(get_Xdummy_confdir())
            cleanups = create_xorg_device_configs(xorg_conf_dir, uinput_uuid, uid, gid)

    xvfb_executable = xvfb_cmd[0]
    if (xvfb_executable.endswith("Xorg") or xvfb_executable.endswith("Xdummy")) and pixel_depth>0:
        xvfb_cmd.append("-depth")
        xvfb_cmd.append(str(pixel_depth))
    if use_display_fd:
        r_pipe, w_pipe = os.pipe()
        xvfb_cmd += ["-displayfd", str(w_pipe)]
        xvfb_cmd[0] = "%s-for-Xpra-%s" % (xvfb_executable, display_name)
        def preexec():
            setsid()
            if getuid()==0 and uid:
                setuidgid(uid, gid)
            close_fds([0, 1, 2, r_pipe, w_pipe])
        try:
            xvfb = subprocess.Popen(xvfb_cmd, executable=xvfb_executable, close_fds=False,
                                    stdin=subprocess.PIPE, preexec_fn=preexec, cwd=cwd)
        except OSError as e:
            log("Popen%s", (xvfb_cmd, xvfb_executable, cwd), exc_info=True)
            raise InitException("failed to execute xvfb command %s: %s" % (xvfb_cmd, e))
        # Read the display number from the pipe we gave to Xvfb
        buf = read_displayfd(r_pipe)
        os.close(r_pipe)
        os.close(w_pipe)
        def displayfd_err(msg):
            raise InitException("%s: %s" % (xvfb_executable, msg))
        n = parse_displayfd(buf, displayfd_err)
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
    xauth_add(xauthority, display_name, xauth_data, uid, gid)
    log("xvfb process=%s", xvfb)
    log("display_name=%s", display_name)
    return xvfb, display_name, cleanups


def set_initial_resolution(desktop=False):
    try:
        log = _vfb_logger()
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
        sizes = randr.get_xrr_screen_sizes()
        size = randr.get_screen_size()
        log("RandR available, current size=%s, sizes available=%s", size, sizes)
        if res in sizes:
            log("RandR setting new screen size to %s", res)
            randr.set_screen_size(*res)
    except Exception as e:
        log("set_initial_resolution(%s)", desktop, exc_info=True)
        log.error("Error: failed to set the default screen size:")
        log.error(" %s", e)


def xauth_add(filename, display_name, xauth_data, uid, gid):
    xauth_cmd = ["xauth", "-f", filename, "add", display_name, "MIT-MAGIC-COOKIE-1", xauth_data]
    try:
        def preexec():
            setsid()
            if getuid()==0 and uid:
                setuidgid(uid, gid)
        code = subprocess.call(xauth_cmd, preexec_fn=preexec, close_fds=True)
        if code != 0:
            raise OSError("non-zero exit code: %s" % code)
    except OSError as e:
        #trying to continue anyway!
        sys.stderr.write("Error adding xauth entry for %s\n" % display_name)
        sys.stderr.write(" using command \"%s\"\n" % (" ".join(xauth_cmd)))
        sys.stderr.write(" %s\n" % (e,))

def check_xvfb_process(xvfb=None, cmd="Xvfb"):
    if xvfb is None:
        #we don't have a process to check
        return True
    if xvfb.poll() is None:
        #process is running
        return True
    log = _vfb_logger()
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
        log = _vfb_logger()
        log("verify_display_ready%s", (xvfb, display_name, shadowing_check), exc_info=True)
        log.error("Error: failed to connect to display %s" % display_name)
        log.error(" %s", e)
        return False
    if shadowing_check and not check_xvfb_process(xvfb):
        #if we're here, there is an X11 server, but it isn't the one we started!
        log = _vfb_logger()
        log.error("There is an X11 server already running on display %s:" % display_name)
        log.error("You may want to use:")
        log.error("  'xpra upgrade %s' if an instance of xpra is still connected to it" % display_name)
        log.error("  'xpra --use-display start %s' to connect xpra to an existing X11 server only" % display_name)
        log.error("")
        return False
    return True
