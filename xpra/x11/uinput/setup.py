# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.util.env import envbool

UINPUT_UUID_LEN: int = 12


def get_logger():
    from xpra.log import Logger
    return Logger("server", "util")


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
    from xpra.os_util import OSX, WIN32
    if OSX or WIN32:
        return False
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
