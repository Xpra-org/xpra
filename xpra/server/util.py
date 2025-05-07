# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from typing import Any

from xpra.util.env import envbool, shellsub
from xpra.os_util import POSIX
from xpra.util.io import get_util_logger
from xpra.platform.dotxpra import norm_makepath
from xpra.scripts.config import InitException

UINPUT_UUID_LEN: int = 12


# pylint: disable=import-outside-toplevel


def get_logger():
    from xpra.log import Logger
    return Logger("server", "util")


# credit: https://stackoverflow.com/a/47080959/428751
# returns a dictionary of the environment variables resulting from sourcing a file


def open_log_file(logpath: str):
    """ renames the existing log file if it exists,
        then opens it for writing.
    """
    if os.path.exists(logpath):
        try:
            os.rename(logpath, logpath + ".old")
        except OSError:
            pass
    try:
        return os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    except OSError as e:
        raise InitException(f"cannot open log file {logpath!r}: {e}") from None


def select_log_file(log_dir: str, log_file: str, display_name: str) -> str:
    """ returns the log file path we should be using given the parameters,
        this may return a temporary logpath if display_name is not available.
    """
    if log_file:
        if os.path.isabs(log_file):
            logpath = log_file
        else:
            logpath = os.path.join(log_dir, log_file)
        v = shellsub(logpath, {"DISPLAY": display_name})
        if display_name or v == logpath:
            # we have 'display_name', or we just don't need it:
            return v
    if display_name:
        logpath = norm_makepath(log_dir, display_name) + ".log"
    else:
        logpath = os.path.join(log_dir, f"tmp_{os.getpid()}.log")
    return logpath


# Redirects stdin from /dev/null, and stdout and stderr to the file with the
# given file descriptor. Returns file objects pointing to the old stdout and
# stderr, which can be used to write a message about the redirection.
def redirect_std_to_log(logfd: int) -> tuple:
    # preserve old stdio in new filehandles for use (and subsequent closing)
    # by the caller
    old_fd_stdout = os.dup(1)
    old_fd_stderr = os.dup(2)
    stdout = os.fdopen(old_fd_stdout, "w", 1)
    stderr = os.fdopen(old_fd_stderr, "w", 1)

    # close the old stdio file handles
    os.close(0)
    os.close(1)
    os.close(2)

    # replace stdin with /dev/null
    fd0 = os.open("/dev/null", os.O_RDONLY)
    if fd0 != 0:
        os.dup2(fd0, 0)
        os.close(fd0)

    # replace standard stdout/stderr by the log file
    os.dup2(logfd, 1)
    os.dup2(logfd, 2)
    os.close(logfd)

    # Make these line-buffered:
    sys.stdout = os.fdopen(1, "w", 1)
    sys.stderr = os.fdopen(2, "w", 1)
    return stdout, stderr


def daemonize() -> None:
    os.chdir("/")
    if os.fork():
        os._exit(0)  # pylint: disable=protected-access
    os.setsid()
    if os.fork():
        os._exit(0)  # pylint: disable=protected-access


def get_uinput_device_path(device) -> str:
    log = get_logger()
    try:
        log("get_uinput_device_path(%s)", device)
        fd = device._Device__uinput_fd
        log("fd(%s)=%s", device, fd)
        import fcntl
        import ctypes
        path_len = 16
        buf = ctypes.create_string_buffer(path_len)
        # this magic value was calculated using the C macros:
        path_len = fcntl.ioctl(fd, 2148554028, buf)
        if 0 < path_len < 16:
            virt_dev_path = (buf.raw[:path_len].rstrip(b"\0")).decode()
            log("UI_GET_SYSNAME(%s)=%s", fd, virt_dev_path)
            uevent_path = "/sys/devices/virtual/input/%s" % virt_dev_path
            event_dirs = [x for x in os.listdir(uevent_path) if x.startswith("event")]
            log("event dirs(%s)=%s", uevent_path, event_dirs)
            for d in event_dirs:
                uevent_filename = os.path.join(uevent_path, d, "uevent")
                uevent_conf = open(uevent_filename, "rb").read()
                for line in uevent_conf.splitlines():
                    if line.find(b"=") > 0:
                        k, v = line.split(b"=", 1)
                        log("%s=%s", k, v)
                        if k == b"DEVNAME":
                            dev_path = (b"/dev/%s" % v).decode("latin1")
                            log(f"found device path: {dev_path}")
                            return dev_path
    except Exception as e:
        log("get_uinput_device_path(%s)", device, exc_info=True)
        log.error("Error: cannot query uinput device path:")
        log.estr(e)
    return ""


def has_uinput() -> bool:
    if not envbool("XPRA_UINPUT", True):
        return False
    try:
        import uinput
        assert uinput
    except ImportError:
        log = get_logger()
        log("has_uinput()", exc_info=True)
        log("no uinput module (not usually needed)")
        return False
    except Exception as e:
        log = get_logger()
        log("has_uinput()", exc_info=True)
        log.warn("Warning: the system python uinput module looks broken:")
        log.warn(" %s", e)
        return False
    try:
        uinput.fdopen()  # @UndefinedVariable
    except Exception as e:
        log = get_logger()
        log("has_uinput()", exc_info=True)
        if isinstance(e, OSError) and e.errno == 19:
            log("no uinput: is the kernel module installed?")
        else:
            log.info("cannot use uinput for virtual devices,")
            log.info(" this is usually a permission issue:")
            log.info(" %s", e)
        return False
    return True


def create_uinput_device(uid: int, events, name: str) -> tuple[str, Any, str] | None:
    log = get_logger()
    import uinput  # @UnresolvedImport
    BUS_USB = 0x03
    # BUS_VIRTUAL = 0x06
    VENDOR = 0xffff
    PRODUCT = 0x1000
    # our 'udev_product_version' script will use the version attribute to set
    # the udev OWNER value
    VERSION = uid
    try:
        device = uinput.Device(events, name=name, bustype=BUS_USB, vendor=VENDOR, product=PRODUCT, version=VERSION)
    except OSError as e:
        log("uinput.Device creation failed", exc_info=True)
        if os.getuid() == 0:
            # running as root, this should work!
            log.error("Error: cannot open uinput,")
            log.error(" make sure that the kernel module is loaded")
            log.error(" and that the /dev/uinput device exists:")
            log.estr(e)
        return None
    dev_path = get_uinput_device_path(device)
    if not dev_path:
        device.destroy()
        return None
    return name, device, dev_path


def create_uinput_pointer_device(uuid: str, uid) -> tuple[str, Any, str] | None:
    if not envbool("XPRA_UINPUT_POINTER", True):
        return None
    from uinput import (
        REL_X, REL_Y, REL_WHEEL,
        BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE,
        BTN_EXTRA, BTN_FORWARD, BTN_BACK,
    )
    events = (
        REL_X, REL_Y, REL_WHEEL,
        BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE,
        BTN_EXTRA, BTN_FORWARD, BTN_BACK,
    )
    # REL_HIRES_WHEEL = 0x10
    # uinput.REL_HWHEEL,
    name = f"Xpra Virtual Pointer {uuid}"
    return create_uinput_device(uid, events, name)


def create_uinput_touchpad_device(uuid: str, uid: int) -> tuple[str, Any, str] | None:
    if not envbool("XPRA_UINPUT_TOUCHPAD", False):
        return None
    from uinput import BTN_TOUCH, ABS_X, ABS_Y, ABS_PRESSURE
    events = (
        BTN_TOUCH,
        ABS_X + (0, 2 ** 24 - 1, 0, 0),
        ABS_Y + (0, 2 ** 24 - 1, 0, 0),
        ABS_PRESSURE + (0, 255, 0, 0),
        # BTN_TOOL_PEN,
    )
    name = f"Xpra Virtual Touchpad {uuid}"
    return create_uinput_device(uid, events, name)


def create_uinput_devices(uinput_uuid: str, uid: int) -> dict[str, Any]:
    log = get_logger()
    try:
        import uinput  # @UnresolvedImport
        assert uinput
    except (ImportError, NameError) as e:
        log.error("Error: cannot access python uinput module:")
        log.estr(e)
        return {}
    pointer = create_uinput_pointer_device(uinput_uuid, uid)
    touchpad = create_uinput_touchpad_device(uinput_uuid, uid)
    if not pointer and not touchpad:
        return {}

    def i(device):
        if not device:
            return {}
        name, uinput_pointer, dev_path = device
        return {
            "name": name,
            "uinput": uinput_pointer,
            "device": dev_path,
        }

    return {
        "pointer": i(pointer),
        "touchpad": i(touchpad),
    }


def create_input_devices(uinput_uuid: str, uid: int) -> dict[str, Any]:
    return create_uinput_devices(uinput_uuid, uid)


def setuidgid(uid: int, gid: int) -> None:
    if not POSIX:
        return
    log = get_util_logger()
    if os.getuid() != uid or os.getgid() != gid:
        # find the username for the given uid:
        from pwd import getpwuid
        try:
            username = getpwuid(uid).pw_name
        except KeyError:
            raise ValueError(f"uid {uid} not found") from None
        # set the groups:
        if hasattr(os, "initgroups"):  # python >= 2.7
            os.initgroups(username, gid)
        else:
            import grp
            groups = [gr.gr_gid for gr in grp.getgrall() if username in gr.gr_mem]
            os.setgroups(groups)
    # change uid and gid:
    try:
        if os.getgid() != gid:
            os.setgid(gid)
    except OSError as e:
        log.error(f"Error: cannot change gid to {gid}")
        if os.getgid() == 0:
            # don't run as root!
            raise
        log.estr(e)
        log.error(f" continuing with gid={os.getgid()}")
    try:
        if os.getuid() != uid:
            os.setuid(uid)
    except OSError as e:
        log.error(f"Error: cannot change uid to {uid}")
        if os.getuid() == 0:
            # don't run as root!
            raise
        log.estr(e)
        log.error(f" continuing with uid={os.getuid()}")
    log(f"new uid={os.getuid()}, gid={os.getgid()}")
