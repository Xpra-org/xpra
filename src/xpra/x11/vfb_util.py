# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# DO NOT IMPORT GTK HERE: see
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000041.html
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000042.html
# (also do not import anything that imports gtk)
from subprocess import Popen, PIPE, call
import os.path

from xpra.scripts.config import InitException, get_Xdummy_confdir
from xpra.util import envbool, envint
from xpra.os_util import (
    shellsub,
    setuidgid, getuid, getgid,
    strtobytes, bytestostr, osexpand, monotonic_time,
    pollwait,
    POSIX, OSX,
    )
from xpra.platform.displayfd import read_displayfd, parse_displayfd


VFB_WAIT = envint("XPRA_VFB_WAIT", 3)
def parse_resolution(envkey="XPRA_DEFAULT_VFB_RESOLUTION", default_res="8192x4096"):
    s = os.environ.get(envkey, default_res)
    res = tuple(int(x) for x in s.replace(",", "x").split("x", 1))
    assert len(res)==2, "invalid resolution string '%s'" % s
    return res
DEFAULT_VFB_RESOLUTION = parse_resolution()
DEFAULT_DESKTOP_VFB_RESOLUTION = parse_resolution("XPRA_DEFAULT_DESKTOP_VFB_RESOLUTION", "1280x1024")
PRIVATE_XAUTH = envbool("XPRA_PRIVATE_XAUTH", False)
XAUTH_PER_DISPLAY = envbool("XPRA_XAUTH_PER_DISPLAY", True)


vfb_logger = None
def get_vfb_logger():
    global vfb_logger
    if not vfb_logger:
        from xpra.log import Logger
        vfb_logger = Logger("server", "x11", "screen")
    return vfb_logger

def osclose(fd):
    try:
        os.close(fd)
    except OSError:
        pass

def create_xorg_device_configs(xorg_conf_dir, device_uuid, uid, gid):
    log = get_vfb_logger()
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

    conf_files = []
    for i, dev_type in (
        (0, "pointer"),
        (1, "touchpad"),
        ) :
        f = save_input_conf(xorg_conf_dir, i, dev_type, device_uuid, uid, gid)
        conf_files.append(f)
    def cleanup_input_conf_files():
        for f in conf_files:
            os.unlink(f)
    cleanups.insert(0, cleanup_input_conf_files)
    return cleanups

#create individual device files:
def save_input_conf(xorg_conf_dir, i, dev_type, device_uuid, uid, gid):
    upper_dev_type = dev_type[:1].upper()+dev_type[1:]   #ie: Pointer
    product_name = "Xpra Virtual %s %s" % (upper_dev_type, bytestostr(device_uuid))
    identifier = "xpra-virtual-%s" % dev_type
    conf_file = os.path.join(xorg_conf_dir, "%02i-%s.conf" % (i, dev_type))
    with open(conf_file, "wb") as f:
        f.write(strtobytes("""Section "InputClass"
Identifier "%s"
MatchProduct "%s"
MatchUSBID "ffff:ffff"
MatchIs%s "True"
Driver "libinput"
Option "AccelProfile" "flat"
Option "Ignore" "False"
EndSection
""" % (identifier, product_name, upper_dev_type)))
        os.fchown(f.fileno(), uid, gid)
    #Option "AccelerationProfile" "-1"
    #Option "AccelerationScheme" "none"
    #Option "AccelSpeed" "-1"
    return conf_file


def get_xauthority_path(display_name, username, uid, gid):
    assert POSIX
    def pathexpand(s):
        return osexpand(s, actual_username=username, uid=uid, gid=gid)
    filename = os.environ.get("XAUTHORITY")
    if filename:
        filename = pathexpand(filename)
        if os.path.exists(filename):
            return filename
    from xpra.platform.xposix.paths import _get_xpra_runtime_dir
    if PRIVATE_XAUTH:
        d = _get_xpra_runtime_dir()
        if XAUTH_PER_DISPLAY:
            filename = "Xauthority-%s" % display_name.lstrip(":")
        else:
            filename = "Xauthority"
    else:
        d = "~/"
        filename = ".Xauthority"
    return os.path.join(pathexpand(d), filename)

def start_Xvfb(xvfb_str, pixel_depth, display_name, cwd, uid, gid, username, xauth_data, uinput_uuid=None):
    if not POSIX:
        raise InitException("starting an Xvfb is not supported on %s" % os.name)
    if OSX:
        raise InitException("starting an Xvfb is not supported on MacOS")
    if not xvfb_str:
        raise InitException("the 'xvfb' command is not defined")

    cleanups = []
    log = get_vfb_logger()
    log("start_Xvfb%s", (xvfb_str, pixel_depth, display_name, cwd, uid, gid, username, xauth_data, uinput_uuid))
    xauthority = get_xauthority_path(display_name, username, uid, gid)
    os.environ["XAUTHORITY"] = xauthority
    if not os.path.exists(xauthority):
        log("creating XAUTHORITY=%s with data=%s", xauthority, xauth_data)
        try:
            with open(xauthority, "a") as f:
                if getuid()==0 and (uid!=0 or gid!=0):
                    os.fchown(f.fileno(), uid, gid)
        except Exception as e:
            #trying to continue anyway!
            log.error("Error trying to create XAUTHORITY file %s:", xauthority)
            log.error(" %s", e)
    else:
        log("found existing XAUTHORITY file '%s'", xauthority)
    use_display_fd = display_name[0]=='S'

    subs = {}
    def pathexpand(s):
        return osexpand(s, actual_username=username, uid=uid, gid=gid, subs=subs)
    subs.update({
        "DISPLAY"       : display_name,
        "XPRA_LOG_DIR"  : pathexpand(os.environ.get("XPRA_LOG_DIR")),
        })

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
        if logfile_argindex+1>=len(xvfb_cmd):
            raise InitException("invalid xvfb command string: -logfile should not be last")
        xorg_log_file = xvfb_cmd[logfile_argindex+1]
    except ValueError:
        xorg_log_file = None
    tmp_xorg_log_file = None
    if xorg_log_file:
        if use_display_fd:
            #keep track of it so we can rename it later:
            tmp_xorg_log_file = xorg_log_file
        #make sure the Xorg log directory exists:
        xorg_log_dir = os.path.dirname(xorg_log_file)
        if not os.path.exists(xorg_log_dir):
            try:
                log("creating Xorg log dir '%s'", xorg_log_dir)
                os.mkdir(xorg_log_dir, 0o700)
                if POSIX and uid!=getuid() or gid!=getgid():
                    try:
                        os.lchown(xorg_log_dir, uid, gid)
                    except OSError:
                        log("lchown(%s, %i, %i)", xorg_log_dir, uid, gid, exc_info=True)
            except OSError as e:
                raise InitException("failed to create the Xorg log directory '%s': %s" % (xorg_log_dir, e)) from None

    if uinput_uuid:
        #use uinput:
        #identify -config xorg.conf argument and replace it with the uinput one:
        try:
            config_argindex = xvfb_cmd.index("-config")
        except ValueError as e:
            log.warn("Warning: cannot use uinput")
            log.warn(" '-config' argument not found in the xvfb command")
        else:
            if config_argindex+1>=len(xvfb_cmd):
                raise InitException("invalid xvfb command string: -config should not be last")
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
    xvfb = None
    try:
        if use_display_fd:
            def displayfd_err(msg):
                raise InitException("%s: %s" % (xvfb_executable, msg))
            r_pipe, w_pipe = os.pipe()
            try:
                os.set_inheritable(w_pipe, True)        #@UndefinedVariable
                xvfb_cmd += ["-displayfd", str(w_pipe)]
                xvfb_cmd[0] = "%s-for-Xpra-%s" % (xvfb_executable, display_name)
                def preexec():
                    os.setpgrp()
                    if getuid()==0 and uid:
                        setuidgid(uid, gid)
                try:
                    xvfb = Popen(xvfb_cmd, executable=xvfb_executable,
                                 preexec_fn=preexec, cwd=cwd, pass_fds=(w_pipe,))
                except OSError as e:
                    log("Popen%s", (xvfb_cmd, xvfb_executable, cwd), exc_info=True)
                    raise InitException("failed to execute xvfb command %s: %s" % (xvfb_cmd, e)) from None
                assert xvfb.poll() is None, "xvfb command failed"
                # Read the display number from the pipe we gave to Xvfb
                try:
                    buf = read_displayfd(r_pipe)
                except Exception as e:
                    log("read_displayfd(%s)", r_pipe, exc_info=True)
                    displayfd_err("failed to read displayfd pipe %s: %s" % (r_pipe, e))
            finally:
                osclose(r_pipe)
                osclose(w_pipe)
            n = parse_displayfd(buf, displayfd_err)
            new_display_name = ":%s" % n
            log("Using display number provided by %s: %s", xvfb_executable, new_display_name)
            if tmp_xorg_log_file:
                #ie: ${HOME}/.xpra/Xorg.${DISPLAY}.log -> /home/antoine/.xpra/Xorg.S14700.log
                f0 = shellsub(tmp_xorg_log_file, subs)
                subs["DISPLAY"] = new_display_name
                #ie: ${HOME}/.xpra/Xorg.${DISPLAY}.log -> /home/antoine/.xpra/Xorg.:1.log
                f1 = shellsub(tmp_xorg_log_file, subs)
                if f0 != f1:
                    try:
                        os.rename(f0, f1)
                    except Exception as e:
                        log.warn("Warning: failed to rename Xorg log file,")
                        log.warn(" from '%s' to '%s'" % (f0, f1))
                        log.warn(" %s" % e)
            display_name = new_display_name
        else:
            # use display specified
            xvfb_cmd[0] = "%s-for-Xpra-%s" % (xvfb_executable, display_name)
            xvfb_cmd.append(display_name)
            def preexec():
                if getuid()==0 and (uid!=0 or gid!=0):
                    setuidgid(uid, gid)
                else:
                    os.setsid()
            log("xvfb_cmd=%s", xvfb_cmd)
            xvfb = Popen(xvfb_cmd, executable=xvfb_executable,
                         stdin=PIPE, preexec_fn=preexec)

        xauth_add(xauthority, display_name, xauth_data, uid, gid)
    except Exception as e:
        if xvfb and xvfb.poll() is None:
            log.error(" stopping vfb process with pid %i", xvfb.pid)
            xvfb.terminate()
        raise
    log("xvfb process=%s", xvfb)
    log("display_name=%s", display_name)
    return xvfb, display_name, cleanups


def kill_xvfb(xvfb_pid):
    log = get_vfb_logger()
    log.info("killing xvfb with pid %s", xvfb_pid)
    import signal
    try:
        os.kill(xvfb_pid, signal.SIGTERM)
    except OSError as e:
        log.info("failed to kill xvfb process with pid %s:", xvfb_pid)
        log.info(" %s", e)
    xauthority = os.environ.get("XAUTHORITY")
    if PRIVATE_XAUTH and xauthority and os.path.exists(xauthority):
        os.unlink(xauthority)


def set_initial_resolution(res=DEFAULT_VFB_RESOLUTION):
    try:
        log = get_vfb_logger()
        log("set_initial_resolution(%s)", res)
        from xpra.x11.bindings.randr_bindings import RandRBindings      #@UnresolvedImport
        #try to set a reasonable display size:
        randr = RandRBindings()
        if not randr.has_randr():
            log.warn("Warning: no RandR support,")
            log.warn(" default virtual display size unchanged")
            return
        sizes = randr.get_xrr_screen_sizes()
        size = randr.get_screen_size()
        log("RandR available, current size=%s, sizes available=%s", size, sizes)
        if res in sizes:
            log("RandR setting new screen size to %s", res)
            randr.set_screen_size(*res)
    except Exception as e:
        log("set_initial_resolution(%s)", res, exc_info=True)
        log.error("Error: failed to set the default screen size:")
        log.error(" %s", e)


def xauth_add(filename, display_name, xauth_data, uid, gid):
    xauth_args = ["-f", filename, "add", display_name, "MIT-MAGIC-COOKIE-1", xauth_data]
    try:
        def preexec():
            os.setsid()
            if getuid()==0 and uid:
                setuidgid(uid, gid)
        xauth_cmd = ["xauth"]+xauth_args
        start = monotonic_time()
        code = call(xauth_cmd, preexec_fn=preexec)
        end = monotonic_time()
        if code!=0 and (end-start>=10):
            log = get_vfb_logger()
            log.warn("Warning: xauth command took %i seconds and failed" % (end-start))
            #took more than 10 seconds to fail, check for stale locks:
            import glob
            if glob.glob("%s-*" % filename):
                log.warn("Warning: trying to clean some stale xauth locks")
                xauth_cmd = ["xauth", "-b"]+xauth_args
                code = call(xauth_cmd, preexec_fn=preexec)
        if code!=0:
            raise OSError("non-zero exit code: %s" % code)
    except OSError as e:
        #trying to continue anyway!
        log = get_vfb_logger()
        log.error("Error adding xauth entry for %s" % display_name)
        log.error(" using command \"%s\":" % (" ".join(xauth_cmd)))
        log.error(" %s" % (e,))

def check_xvfb_process(xvfb=None, cmd="Xvfb", timeout=0):
    if xvfb is None:
        #we don't have a process to check
        return True
    if pollwait(xvfb, timeout) is None:
        #process is running
        return True
    log = get_vfb_logger()
    log.error("")
    log.error("%s command has terminated! xpra cannot continue", cmd)
    log.error(" if the display is already running, try a different one,")
    log.error(" or use the --use-display flag")
    log.error("")
    return False

def verify_display_ready(xvfb, display_name, shadowing_check=True, log_errors=True):
    from xpra.x11.bindings.wait_for_x_server import wait_for_x_server        #@UnresolvedImport
    # Whether we spawned our server or not, it is now running -- or at least
    # starting.  First wait for it to start up:
    try:
        wait_for_x_server(strtobytes(display_name), VFB_WAIT)
    except Exception as e:
        log = get_vfb_logger()
        log("verify_display_ready%s", (xvfb, display_name, shadowing_check), exc_info=True)
        if log_errors:
            log.error("Error: failed to connect to display %s" % display_name)
            log.error(" %s", e)
        return False
    if shadowing_check and not check_xvfb_process(xvfb):
        #if we're here, there is an X11 server, but it isn't the one we started!
        log = get_vfb_logger()
        log("verify_display_ready%s display exists, but the vfb process has terminated",
                (xvfb, display_name, shadowing_check, log_errors))
        if log_errors:
            log.error("There is an X11 server already running on display %s:" % display_name)
            log.error("You may want to use:")
            log.error("  'xpra upgrade %s' if an instance of xpra is still connected to it" % display_name)
            log.error("  'xpra --use-display start %s' to connect xpra to an existing X11 server only" % display_name)
            log.error("")
        return False
    return True


def main():
    import sys
    display = None
    if len(sys.argv)>1:
        display = strtobytes(sys.argv[1])
    from xpra.x11.bindings.wait_for_x_server import wait_for_x_server        #@UnresolvedImport
    wait_for_x_server(display, VFB_WAIT)
    print("OK")


if __name__ == "__main__":
    main()
