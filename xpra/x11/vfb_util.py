# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# DO NOT IMPORT GTK HERE: see
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000041.html
#  http://lists.partiwm.org/pipermail/parti-discuss/2008-September/000042.html
# (also do not import anything that imports gtk)
import glob
import shlex
import signal
from time import monotonic
from typing import NoReturn
from subprocess import Popen, PIPE, call
import os.path

from xpra.common import RESOLUTION_ALIASES, DEFAULT_REFRESH_RATE, get_refresh_rate_for_value
from xpra.scripts.config import InitException, get_Xdummy_confdir, FALSE_OPTIONS
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool, shellsub, osexpand, get_exec_env, get_saved_env_var
from xpra.os_util import getuid, getgid, POSIX, OSX
from xpra.server.util import setuidgid
from xpra.util.io import is_writable, pollwait
from xpra.platform.displayfd import read_displayfd, parse_displayfd
from xpra.log import Logger


VFB_WAIT = envint("XPRA_VFB_WAIT", 3)
XVFB_EXTRA_ARGS = os.environ.get("XPRA_XVFB_EXTRA_ARGS", "")


def parse_resolution(res_str, default_refresh_rate=DEFAULT_REFRESH_RATE//1000) -> tuple[int, int, int] | None:
    if not res_str:
        return None
    s = res_str.upper()       # ie: 4K60
    res_part = s
    hz = get_refresh_rate_for_value(str(default_refresh_rate), DEFAULT_REFRESH_RATE)//1000
    for sep in ("@", "K", "P"):
        pos = s.find(sep)
        if 0 < pos < len(s)-1:
            res_part, hz = s.split(sep, 1)
            if sep != "@":
                res_part += sep
            break
    if res_part in RESOLUTION_ALIASES:
        w, h = RESOLUTION_ALIASES[res_part]
    else:
        try:
            parts = tuple(int(x) for x in res_part.replace(",", "x").split("X", 1))
        except ValueError:
            raise ValueError(f"failed to parse resolution {res_str!r}") from None
        if len(parts) != 2:
            raise ValueError(f"invalid resolution string {res_str!r}")
        w = parts[0]
        h = parts[1]
    return w, h, int(hz)


def parse_resolutions(s, default_refresh_rate=DEFAULT_REFRESH_RATE//1000) -> tuple | None:
    if not s or s.lower() in FALSE_OPTIONS:
        return None
    if s.lower() in ("none", "default"):
        return ()
    return tuple(parse_resolution(v, default_refresh_rate) for v in s.split(","))


def parse_env_resolutions(envkey="XPRA_DEFAULT_VFB_RESOLUTIONS",
                          single_envkey="XPRA_DEFAULT_VFB_RESOLUTION",
                          default_res="8192x4096",
                          default_refresh_rate=DEFAULT_REFRESH_RATE//1000):
    s = os.environ.get(envkey)
    if s:
        return parse_resolutions(s, default_refresh_rate)
    return (parse_resolution(os.environ.get(single_envkey, default_res), default_refresh_rate), )


def get_desktop_vfb_resolutions(default_refresh_rate=DEFAULT_REFRESH_RATE//1000):
    return parse_env_resolutions("XPRA_DEFAULT_DESKTOP_VFB_RESOLUTIONS",
                                 "XPRA_DEFAULT_DESKTOP_VFB_RESOLUTION",
                                 "1280x1024",
                                 default_refresh_rate=default_refresh_rate)


PRIVATE_XAUTH = envbool("XPRA_PRIVATE_XAUTH", False)
XAUTH_PER_DISPLAY = envbool("XPRA_XAUTH_PER_DISPLAY", True)


vfb_logger = None


def get_vfb_logger() -> Logger:
    global vfb_logger
    if not vfb_logger:
        vfb_logger = Logger("server", "x11", "screen")
    return vfb_logger


def osclose(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def create_xorg_device_configs(xorg_conf_dir: str, device_uuid: str, uid: int, gid: int) -> None:
    log = get_vfb_logger()
    log("create_xorg_device_configs(%s, %s, %i, %i)", xorg_conf_dir, device_uuid, uid, gid)
    if not device_uuid:
        return

    def makedir(dirname) -> None:
        log("makedir(%s)", dirname)
        os.mkdir(dirname)
        os.lchown(dirname, uid, gid)

    # create conf dir if needed:
    d = xorg_conf_dir
    dirs: list[str] = []
    while d and not os.path.exists(d):
        log("create_device_configs: dir does not exist: %s", d)
        dirs.insert(0, d)
        d = os.path.dirname(d)
    for d in dirs:
        makedir(d)

    conf_files: list[str] = []
    for i, dev_type in (
        (0, "pointer"),
        (1, "touchpad"),
    ):
        f = save_input_conf(xorg_conf_dir, i, dev_type, device_uuid, uid, gid)
        conf_files.append(f)


def save_input_conf(xorg_conf_dir: str, i, dev_type, device_uuid: str, uid: int, gid: int) -> str:
    # create individual device files:
    upper_dev_type = dev_type[:1].upper()+dev_type[1:]   # ie: Pointer
    product_name = f"Xpra Virtual {upper_dev_type} {device_uuid}"
    identifier = f"xpra-virtual-{dev_type}"
    conf_file = os.path.join(xorg_conf_dir, f"{i:02}-{dev_type}.conf")
    with open(conf_file, "w", encoding="utf8") as f:
        f.write(f"""Section "InputClass"
Identifier "{identifier}"
MatchProduct "{product_name}"
MatchUSBID "ffff:ffff"
MatchIs{upper_dev_type} "True"
Driver "libinput"
Option "AccelProfile" "flat"
Option "Ignore" "False"
EndSection
""")
        os.fchown(f.fileno(), uid, gid)
    # Option "AccelerationProfile" "-1"
    # Option "AccelerationScheme" "none"
    # Option "AccelSpeed" "-1"
    return conf_file


def valid_xauth(filename: str, uid: int = getuid(), gid: int = getgid()) -> str:
    if not filename:
        return ""
    if not os.path.exists(filename):
        return ""
    if not is_writable(filename, uid, gid):
        log = get_vfb_logger()
        log.info(f"ignoring non-writable XAUTHORITY={filename!r}")
        return ""
    return filename


def get_xauthority_path(display_name: str) -> str:
    assert POSIX
    # pylint: disable=import-outside-toplevel
    from xpra.platform.posix.paths import _get_xpra_runtime_dir
    expanded_home = os.path.expanduser("~")
    has_home = os.path.exists(expanded_home) and is_writable(expanded_home, getuid(), getgid())
    if PRIVATE_XAUTH or (not has_home and os.environ.get("XDG_RUNTIME_DIR")):
        d = _get_xpra_runtime_dir()
        if XAUTH_PER_DISPLAY:
            filename = "Xauthority-" + display_name.lstrip(":")
        else:
            filename = "Xauthority"
    else:
        if has_home and is_writable(expanded_home, getuid(), getgid()):
            d = expanded_home
        else:
            d = os.environ.get("TMPDIR", "/tmp")
        filename = ".Xauthority"
    return os.path.join(d, filename)


def get_xvfb_env(xvfb_executable: str) -> dict[str, str]:
    keep = tuple(f"^{envname}$" for envname in (
        "SHELL", "HOSTNAME", "XMODIFIERS",
        "PWD", "HOME", "USERNAME", "LANG", "TERM", "USER",
        "XDG_RUNTIME_DIR", "XDG_DATA_DIR",
        "PATH", "LD_LIBRARY_PATH",
        "XAUTHORITY",
        "XPRA_SESSION_DIR",
    ))
    env = get_exec_env(keep=keep)
    if xvfb_executable.endswith("Xephyr"):
        env["DISPLAY"] = get_saved_env_var("DISPLAY")
    return env


def patch_xvfb_command(xvfb_cmd: list[str], w: int, h: int, pixel_depth: int):
    # find the ["-screen"] or ["screen", "0"] arguments:
    try:
        screen_arg = xvfb_cmd.index("-screen")
    except ValueError:
        # not found!
        screen_arg = -1
    if screen_arg > 0:
        # remove the screen number if specified:
        try:
            no_arg = xvfb_cmd.index("0")
        except ValueError:
            no_arg = -1
        if no_arg > 0 and no_arg == screen_arg + 1:
            xvfb_cmd.pop(no_arg)
        # remove the "-screen" argument and the geometry that follows:
        xvfb_cmd.pop(screen_arg)
        xvfb_cmd.pop(screen_arg)
    # this is the geometry we want to add:
    if xvfb_cmd[0].endswith("Xvfb"):
        # ie: "-screen 0 8192x4096x32"
        xvfb_cmd += ["-screen", "0", f"{w}x{h}x{pixel_depth}"]
    else:
        # play it safe, don't specify the screen number:
        xvfb_cmd += ["-screen", f"{w}x{h}x{pixel_depth}"]


def start_Xvfb(xvfb_cmd: list[str], vfb_geom, pixel_depth: int, display_name: str, cwd,
               uid: int, gid: int, username: str, uinput_uuid="") -> tuple[Popen, str]:
    if not POSIX:
        raise InitException(f"starting an Xvfb is not supported on {os.name}")
    if OSX:
        raise InitException("starting an Xvfb is not supported on MacOS")
    if not xvfb_cmd:
        raise InitException("the 'xvfb' command is not defined")
    if not display_name:
        raise ValueError("no display name")

    log = get_vfb_logger()
    log("start_Xvfb%s XVFB_EXTRA_ARGS=%s",
        (xvfb_cmd, vfb_geom, pixel_depth, display_name, cwd, uid, gid, username, uinput_uuid),
        XVFB_EXTRA_ARGS)
    use_display_fd = display_name[0] == "S"
    if XVFB_EXTRA_ARGS:
        xvfb_cmd += shlex.split(XVFB_EXTRA_ARGS)

    subs: dict[str, str] = {}

    def pathexpand(s: str) -> str:
        return osexpand(s, actual_username=username, uid=uid, gid=gid, subs=subs)
    etc_prefix = os.environ.get("XPRA_INSTALL_PREFIX", "")
    if etc_prefix.endswith("/usr"):
        etc_prefix = etc_prefix[:-4]
    subs |= {
        "DISPLAY": display_name,
        "XPRA_LOG_DIR": pathexpand(os.environ.get("XPRA_LOG_DIR", "")),
        "XORG_CONFIG_PREFIX": os.environ.get("XORG_CONFIG_PREFIX", etc_prefix),
    }

    # identify logfile argument if it exists,
    # as we may have to rename it, or create the directory for it:
    # make sure all path values are expanded:
    xvfb_cmd = [pathexpand(s) for s in xvfb_cmd]

    # try to honour initial geometries if specified:
    xvfb_executable = xvfb_cmd[0]
    if len(vfb_geom) >= 2 and (xvfb_executable.endswith("Xvfb") or xvfb_executable.endswith("Xephyr")):
        w, h = vfb_geom[:2]
        log("patch_xvfb_command%s", (xvfb_cmd, w, h, pixel_depth or 32))
        patch_xvfb_command(xvfb_cmd, w, h, pixel_depth or 32)
        log(f"{xvfb_cmd=!r}")
    try:
        logfile_argindex = xvfb_cmd.index('-logfile')
        if logfile_argindex+1 >= len(xvfb_cmd):
            raise InitException("invalid xvfb command string: -logfile should not be last")
        xorg_log_file = xvfb_cmd[logfile_argindex+1]
    except ValueError:
        xorg_log_file = None
    tmp_xorg_log_file = None
    if xorg_log_file:
        if use_display_fd:
            # keep track of it, so that we can rename it later:
            tmp_xorg_log_file = xorg_log_file
        # make sure the Xorg log directory exists:
        xorg_log_dir = os.path.dirname(xorg_log_file)
        if not os.path.exists(xorg_log_dir):
            try:
                log("creating Xorg log dir '%s'", xorg_log_dir)
                os.mkdir(xorg_log_dir, 0o700)
                if POSIX and uid != getuid() or gid != getgid():
                    try:
                        os.lchown(xorg_log_dir, uid, gid)
                    except OSError:
                        log("lchown(%s, %i, %i)", xorg_log_dir, uid, gid, exc_info=True)
            except OSError as e:
                raise InitException(f"failed to create the Xorg log directory {xorg_log_dir!r}: {e}") from None

    if uinput_uuid:
        # use uinput:
        # identify -config xorg.conf argument and replace it with the uinput one:
        try:
            config_argindex = xvfb_cmd.index("-config")
        except ValueError:
            log.warn("Warning: cannot use uinput")
            log.warn(" '-config' argument not found in the xvfb command")
        else:
            if config_argindex+1 >= len(xvfb_cmd):
                raise InitException("invalid xvfb command string: -config should not be last")
            xorg_conf = xvfb_cmd[config_argindex+1]
            if xorg_conf.endswith("xorg.conf"):
                xorg_conf = xorg_conf.replace("xorg.conf", "xorg-uinput.conf")
                if os.path.exists(xorg_conf):
                    xvfb_cmd[config_argindex+1] = xorg_conf
            # create uinput device definition files:
            # (we have to assume that Xorg is configured to use this path..)
            xorg_conf_dir = pathexpand(get_Xdummy_confdir())
            create_xorg_device_configs(xorg_conf_dir, uinput_uuid, uid, gid)

    if (xvfb_executable.endswith("Xorg") or xvfb_executable.endswith("Xdummy")) and pixel_depth > 0:
        xvfb_cmd.append("-depth")
        xvfb_cmd.append(str(pixel_depth))
    env = get_xvfb_env(xvfb_executable)
    log(f"xvfb env={env}")
    xvfb = None
    try:
        if use_display_fd:
            def displayfd_err(msg: str) -> NoReturn:
                if xvfb and xvfb.poll() is None:
                    log.error(" stopping vfb process with pid %i", xvfb.pid)
                    xvfb.terminate()
                raise InitException(f"{xvfb_executable}: {msg}")
            r_pipe, w_pipe = os.pipe()
            try:
                os.set_inheritable(w_pipe, True)
                xvfb_cmd += ["-displayfd", str(w_pipe)]
                xvfb_cmd[0] = f"{xvfb_executable}-for-Xpra-" + display_name.lstrip(":")

                def preexec() -> None:
                    os.setpgrp()
                    if getuid() == 0 and uid:
                        setuidgid(uid, gid)
                try:
                    # pylint: disable=consider-using-with
                    # pylint: disable=subprocess-popen-preexec-fn
                    xvfb = Popen(xvfb_cmd, executable=xvfb_executable,
                                 preexec_fn=preexec, cwd=cwd, env=env, pass_fds=(w_pipe,))
                except OSError as e:
                    log("Popen%s", (xvfb_cmd, xvfb_executable, cwd), exc_info=True)
                    raise InitException(f"failed to execute xvfb command {xvfb_cmd}: {e}") from None
                if xvfb.poll() is not None:
                    raise InitException(f"xvfb command has terminated: {xvfb_cmd}")
                # Read the display number from the pipe we gave to Xvfb
                try:
                    buf = read_displayfd(r_pipe, proc=xvfb)
                except Exception as e:
                    buf = b""
                    log("read_displayfd(%s)", r_pipe, exc_info=True)
                    displayfd_err(f"failed to read displayfd pipe {r_pipe}: {e}")
            finally:
                osclose(r_pipe)
                osclose(w_pipe)
            n = parse_displayfd(buf, displayfd_err)
            if n < 0:
                displayfd_err(f"failed to parse displayfd output {buf!r}")
            new_display_name = f":{n}"
            log(f"Using display number provided by {xvfb_executable}: {new_display_name}")
            if tmp_xorg_log_file:
                # ie: ${HOME}/.xpra/Xorg.${DISPLAY}.log -> /home/antoine/.xpra/Xorg.S14700.log
                f0 = shellsub(tmp_xorg_log_file, subs)
                subs["DISPLAY"] = new_display_name
                # ie: ${HOME}/.xpra/Xorg.${DISPLAY}.log -> /home/antoine/.xpra/Xorg.:1.log
                f1 = shellsub(tmp_xorg_log_file, subs)
                if f0 != f1:
                    try:
                        os.rename(f0, f1)
                    except Exception as e:
                        log.warn("Warning: failed to rename Xorg log file,")
                        log.warn(f" from {f0!r} to {f1!r}")
                        log.warn(f" {e}")
            display_name = new_display_name
        else:
            # use display specified
            xvfb_cmd[0] = f"{xvfb_executable}-for-Xpra-"+display_name.lstrip(":")
            xvfb_cmd.append(display_name)

            def preexec() -> None:
                if getuid() == 0 and (uid != 0 or gid != 0):
                    setuidgid(uid, gid)
                else:
                    os.setsid()
            log("xvfb_cmd=%s", xvfb_cmd)
            # pylint: disable=consider-using-with
            # pylint: disable=subprocess-popen-preexec-fn
            xvfb = Popen(xvfb_cmd, executable=xvfb_executable,
                         stdin=PIPE, preexec_fn=preexec, env=env)
    except Exception:
        if xvfb and xvfb.poll() is None:
            log.error(" stopping vfb process with pid %i", xvfb.pid)
            xvfb.terminate()
        raise
    log("xvfb process=%s", xvfb)
    log("display_name=%s", display_name)
    return xvfb, display_name


def start_xvfb_standalone(xvfb_cmd: list[str], sessions_dir: str, pixel_depth=0, display_name="") -> int:
    # we may have to tweak the environment to emulate having an xpra session
    # as the default xvfb commands may refer to $XAUTHORITY and $XPRA_SESSION_DIR
    xauthority = os.environ.get("XAUTHORITY", "")
    if "$XAUTHORITY" in xvfb_cmd and not valid_xauth(xauthority):
        xauthority = osexpand(get_xauthority_path(display_name))
        os.environ["XAUTHORITY"] = xauthority
    if "$XPRA_SESSION_DIR" in xvfb_cmd and "XPRA_SESSION_DIR" not in os.environ:
        from xpra.scripts.session import make_session_dir
        session_dir = make_session_dir("xvfb", sessions_dir, display_name)
        os.environ["XPRA_SESSION_DIR"] = session_dir
    vfb_geom = ()
    cwd = os.getcwd()
    xvfb, actual_display_name = start_Xvfb(xvfb_cmd, vfb_geom, pixel_depth, display_name,
                                           cwd, uid=getuid(), gid=getgid(), username="", uinput_uuid="")
    if actual_display_name != display_name:
        print(f"display {actual_display_name!r} started")
    print(f"xvfb pid: {xvfb.pid}")
    return xvfb.wait()


def kill_xvfb(xvfb_pid: int) -> None:
    log = get_vfb_logger()
    log.info("killing xvfb with pid %s", xvfb_pid)
    try:
        os.kill(xvfb_pid, signal.SIGTERM)
    except OSError as e:
        log.info("failed to kill xvfb process with pid %s:", xvfb_pid)
        log.info(" %s", e)
    xauthority = os.environ.get("XAUTHORITY", "")
    if PRIVATE_XAUTH and xauthority and os.path.exists(xauthority):
        os.unlink(xauthority)


def set_initial_resolution(resolutions, dpi: int = 0) -> None:
    log = get_vfb_logger()
    log("set_initial_resolution(%s)", resolutions)
    try:
        # pylint: disable=import-outside-toplevel
        from xpra.x11.bindings.randr import RandRBindings
        # try to set a reasonable display size:
        randr = RandRBindings()
        if not randr.has_randr():
            log.warn("Warning: no RandR support,")
            log.warn(" default virtual display size unchanged")
            return
        if randr.is_dummy16():
            monitors = {}
            x, y = 0, 0
            for i, res in enumerate(resolutions):
                assert len(res) == 3
                if not all(isinstance(v, int) for v in res):
                    raise ValueError(f"resolution values must be ints, found: {res} ({csv(type(v) for v in res)})")
                w, h, hz = res
                mdpi = dpi
                # guess the DPI if we don't have one:
                if mdpi <= 0:
                    # use a higher DPI for higher resolutions
                    if w >= 4096 or h >= 2560:
                        mdpi = 144
                    elif w >= 2560 or h >= 1440:
                        mdpi = 120
                    else:
                        mdpi = 96

                def rdpi(v: int) -> int:
                    return round(v * 25.4 / mdpi)
                monitors[i] = {
                    "name": f"VFB-{i}",
                    "primary": i == 0,
                    "geometry": (x, y, w, h),
                    "width-mm": rdpi(w),
                    "height-mm": rdpi(h),
                    "refresh-rate": hz*1000,
                    "automatic": True,
                }
                x += w
                # arranging vertically:
                # y += h
            randr.set_crtc_config(monitors)
            return
        res = resolutions[0][:2]
        sizes = randr.get_xrr_screen_sizes()
        size = randr.get_screen_size()
        log(f"RandR available, current {size=}, sizes available={sizes}")
        if res not in sizes:
            log.warn(f"Warning: cannot set resolution to {res}")
            log.warn(" (this resolution is not available)")
        elif res == size:
            log(f"initial resolution already set: {res}")
        else:
            log(f"RandR setting new screen size to {res}")
            randr.set_screen_size(*res)
    except Exception as e:
        log(f"set_initial_resolution({resolutions})", exc_info=True)
        log.error("Error: failed to set the default screen size:")
        log.estr(e)


def xauth_add(filename: str, display_name: str, xauth_data: str, uid: int, gid: int) -> None:
    xauth_args = ["-f", filename, "add", display_name, "MIT-MAGIC-COOKIE-1", xauth_data]
    xauth_cmd = ["xauth"] + xauth_args
    try:
        def preexec():
            os.setsid()
            if getuid() == 0 and uid:
                setuidgid(uid, gid)
        start = monotonic()
        log = get_vfb_logger()
        log("xauth command: %s", xauth_cmd)
        code = call(xauth_cmd, preexec_fn=preexec)
        end = monotonic()
        elapsed = round(end-start)
        if code != 0 and elapsed >= 10:
            log.warn(f"Warning: xauth command took {elapsed} seconds and failed")
            # took more than 10 seconds to fail, check for stale locks:
            if glob.glob(f"{filename}-*"):
                log.warn("Warning: trying to clean some stale xauth locks")
                xauth_cmd = ["xauth", "-b"]+xauth_args
                log(f"xauth command: {xauth_cmd}")
                code = call(xauth_cmd, preexec_fn=preexec)
        if code != 0:
            raise OSError(f"non-zero exit code: {code}")
    except OSError as e:
        # trying to continue anyway!
        log = get_vfb_logger()
        log(f"xauth_add%s xauth_cmd={xauth_cmd}", (filename, display_name, xauth_data, uid, gid))
        log.error(f"Error adding xauth entry for {display_name}")
        log.error(" using command \"%s\":" % (" ".join(xauth_cmd)))
        log.estr(e)


def check_xvfb_process(xvfb=None, cmd: str = "Xvfb", timeout: int = 0, command=()) -> bool:
    if xvfb is None:
        # we don't have a process to check
        return True
    if pollwait(xvfb, timeout) is None:
        # process is running
        return True
    log = get_vfb_logger()
    log.error("")
    log.error("%s command has terminated! xpra cannot continue", cmd)
    log.error(" if the display is already running, try a different one,")
    log.error(" if the `xvfb` command is invalid, try a different one")
    if command:
        log.error(" full command: %r", shlex.join(command))
    log.error("")
    return False


def verify_display_ready(xvfb, display_name: str, shadowing_check=True, log_errors=True, timeout=VFB_WAIT) -> bool:
    from xpra.x11.bindings.wait_for_x_server import wait_for_x_server  # pylint: disable=import-outside-toplevel
    # Whether we spawned our server or not, it is now running -- or at least
    # starting.  First wait for it to start up:
    try:
        wait_for_x_server(display_name, timeout)
    except Exception as e:
        log = get_vfb_logger()
        log("verify_display_ready%s", (xvfb, display_name, shadowing_check), exc_info=True)
        if log_errors:
            log.error(f"Error: failed to connect to display {display_name!r}")
            log.estr(e)
        return False
    if shadowing_check and not check_xvfb_process(xvfb):
        # if we're here, there is an X11 server, but it isn't the one we started!
        log = get_vfb_logger()
        log("verify_display_ready%s display exists, but the vfb process has terminated",
            (xvfb, display_name, shadowing_check, log_errors))
        if log_errors:
            log.error(f"There is an X11 server already running on display {display_name}:")
            log.error("You may want to use:")
            log.error(f"  'xpra upgrade {display_name}' if an instance of xpra is still connected to it")
            log.error(f"  'xpra --use-display start {display_name}' to connect xpra to an existing X11 server only")
            log.error("")
        return False
    return True


def main() -> None:
    # pylint: disable=import-outside-toplevel
    import sys
    display = ""
    if len(sys.argv) > 1:
        display = sys.argv[1]
    from xpra.x11.bindings.wait_for_x_server import wait_for_x_server
    wait_for_x_server(display, VFB_WAIT)
    print("OK")


if __name__ == "__main__":
    main()
