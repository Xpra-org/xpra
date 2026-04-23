# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable-msg=E1101

import os
import glob
from typing import Any
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.util.system import is_DEB
from xpra.log import Logger

log = Logger("webcam")

# on Debian and Ubuntu, the v4l2loopback device is created with exclusive_caps=1,
# so we cannot check the devices caps for the "VIDEO_CAPTURE" flag.
# https://github.com/Xpra-org/xpra/issues/1596
CHECK_VIRTUAL_CAPTURE = envbool("XPRA_CHECK_VIRTUAL_CAPTURE", not is_DEB())


def _can_capture_video(dev_file, dev_info) -> bool:
    if not dev_info:
        return False
    caps = dev_info.get("capabilities", [])
    if "DEVICE_CAPS" in caps:
        caps = dev_info.get("device_caps", [])
    if "VIDEO_CAPTURE" not in caps:
        log(f"device {dev_file!r} does not support video capture, capabilities={caps}")
        return False
    return True


v4l2_virtual_dir = "/sys/devices/virtual/video4linux"


def check_virtual_dir() -> bool:
    return os.path.exists(v4l2_virtual_dir) and os.path.isdir(v4l2_virtual_dir)


def query_video_device(device) -> dict[str, Any]:
    try:
        # pylint: disable=import-outside-toplevel
        from xpra.codecs.v4l2.virtual import query_video_device as v4l_query_video_device
        return v4l_query_video_device(device)
    except ImportError as e:
        log(f"query_video_device({device}) no v4l2 module: {e}")
        return {}


def get_virtual_video_devices(capture_only=True) -> dict[int, dict]:
    log(f"get_virtual_video_devices({capture_only}) CHECK_VIRTUAL_CAPTURE={CHECK_VIRTUAL_CAPTURE}")
    if not check_virtual_dir():
        return {}
    contents = os.listdir(v4l2_virtual_dir)
    devices = {}
    for f in sorted(contents):
        if not f.startswith("video"):
            continue
        try:
            no_str = f.removeprefix("video")
            no = int(no_str)
            assert no >= 0
        except (TypeError, ValueError, AssertionError):
            continue
        dev_file = f"/dev/{f}"
        dev_info = query_video_device(dev_file)
        if CHECK_VIRTUAL_CAPTURE and capture_only and not _can_capture_video(dev_file, dev_info):
            continue
        info = {"device": dev_file}
        info.update(dev_info)
        if "card" not in dev_info:
            # look up the name from the v4l2 virtual dir:
            dev_dir = os.path.join(v4l2_virtual_dir, f)
            if not os.path.isdir(dev_dir):
                continue
            dev_name = os.path.join(dev_dir, "name")
            try:
                with open(dev_name, encoding="latin1") as df:
                    name = df.read().replace("\n", "")
                info["card"] = name
            except OSError:
                pass
        devices[no] = info
    log(f"devices: {devices}")
    log(f"found {len(devices)} virtual video devices")
    return devices


def get_all_video_devices(capture_only=True) -> dict[int, dict[str, Any]]:
    contents = os.listdir("/dev")
    devices: dict[int, dict[str, Any]] = {}
    device_paths = set()
    for f in contents:
        if not f.startswith("video"):
            continue
        dev_file = f"/dev/{f}"
        try:
            dev_file = os.readlink(dev_file)
        except OSError:
            pass
        if dev_file in device_paths:
            continue
        device_paths.add(dev_file)
        try:
            no_str = f.removeprefix("video")
            no = int(no_str)
            assert no >= 0
        except (TypeError, ValueError, AssertionError):
            continue
        dev_info = query_video_device(dev_file)
        if capture_only and not _can_capture_video(dev_file, dev_info):
            continue
        info = {"device": dev_file}
        info.update(dev_info)
        devices[no] = info
    return devices


device_timetamps: dict[str, float] = {}
device_monitor = None


def update_device_timestamps() -> None:
    for dev in glob.glob("/dev/video*"):
        try:
            device_timetamps[dev] = os.path.getmtime(dev)
        except OSError:
            pass


def add_video_device_change_callback(callback: Callable) -> None:
    # pylint: disable=import-outside-toplevel
    Gio = gi_import("Gio")
    from xpra.platform.webcam import _video_device_change_callbacks, _fire_video_device_change
    log(f"add_video_device_change_callback({callback})")
    global device_monitor

    def dev_directory_changed(*_args) -> None:
        old = dict(device_timetamps)
        update_device_timestamps()
        if set(old.keys()) != set(device_timetamps.keys()):
            _fire_video_device_change()
            return
        for dev, ts in old.items():
            if device_timetamps.get(dev, -1) != ts:
                _fire_video_device_change()
                return

    if not device_monitor:
        update_device_timestamps()
        try:
            gfile = Gio.File.new_for_path("/dev")
            device_monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            device_monitor.connect("changed", dev_directory_changed)
            log("watching for video device changes in /dev")
        except Exception as e:
            log("add_video_device_change_callback(%s)", callback, exc_info=True)
            log.warn("Warning: unable to use Gio file monitor: %s", e)
    _video_device_change_callbacks.append(callback)


def _video_devices_by_rdev() -> dict[tuple[int, int], str]:
    """Map (major, minor) -> '/dev/videoN' for every v4l2 video node."""
    result: dict[tuple[int, int], str] = {}
    for dev in glob.glob("/dev/video*"):
        try:
            st = os.stat(dev)
        except OSError:
            continue
        result[(os.major(st.st_rdev), os.minor(st.st_rdev))] = dev
    return result


def _libcamera_system_devices(camera) -> list[int]:
    """
    Read the ``SystemDevices`` property (a list of dev_t values) from a
    libcamera ``Camera`` object, defensively across binding versions.
    """
    props = getattr(camera, "properties", None)
    if props is None:
        return []
    # preferred: properties.SystemDevices control id
    try:
        from libcamera import properties as lc_props
        key = getattr(lc_props, "SystemDevices", None)
        if key is not None and key in props:
            return list(props[key])
    except ImportError:
        pass
    # fallback: iterate and match by name
    try:
        items = props.items()
    except AttributeError:
        return []
    for key, val in items:
        if getattr(key, "name", "") == "SystemDevices":
            return list(val)
    return []


def _libcamera_device_paths(camera, rdev_map: dict[tuple[int, int], str]) -> list[str]:
    paths: list[str] = []
    for devnum in _libcamera_system_devices(camera):
        try:
            n = int(devnum)
        except (TypeError, ValueError):
            continue
        dev = rdev_map.get((os.major(n), os.minor(n)))
        if dev and dev not in paths:
            paths.append(dev)
    return paths


def get_libcamera_devices() -> dict[str, dict]:
    """
    Return a dict of {camera_id: {"id": ..., "name": ..., "device": ..., "devices": [...]}}
    for all cameras visible to the libcamera stack.
    ``device`` / ``devices`` are the matching /dev/videoN paths when they can
    be resolved via the camera's ``SystemDevices`` property.
    Returns an empty dict if libcamera is not installed.
    """
    try:
        import libcamera
    except ImportError as e:
        log("libcamera not available: %s", e)
        return {}
    try:
        cm = libcamera.CameraManager.singleton()
        rdev_map = _video_devices_by_rdev()
        devices: dict[str, dict] = {}
        for camera in cm.cameras:
            camera_id = camera.id
            info: dict = {"id": camera_id, "name": camera_id}
            paths = _libcamera_device_paths(camera, rdev_map)
            if paths:
                info["devices"] = paths
                info["device"] = paths[0]
            devices[camera_id] = info
        log("get_libcamera_devices() found %i cameras: %s", len(devices), devices)
        return devices
    except Exception as e:
        log("get_libcamera_devices() error: %s", e)
        return {}


def remove_video_device_change_callback(callback: Callable) -> None:
    # pylint: disable=import-outside-toplevel
    from xpra.platform.webcam import _video_device_change_callbacks
    log(f"remove_video_device_change_callback({callback})")
    global device_monitor, device_timetamps
    if callback not in _video_device_change_callbacks:
        log.error("Error: video device change callback not found, cannot remove it!")
        return
    _video_device_change_callbacks.remove(callback)
    if not _video_device_change_callbacks and device_monitor:
        device_monitor.cancel()
        device_monitor = None
        device_timetamps = {}
