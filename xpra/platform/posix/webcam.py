# This file is part of Xpra.
# Copyright (C) 2016-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

import os
from typing import Dict, Any, Callable

from xpra.util import envbool
from xpra.os_util import is_Ubuntu, is_Debian
from xpra.log import Logger

log = Logger("webcam")

#on Debian and Ubuntu, the v4l2loopback device is created with exclusive_caps=1,
#so we cannot check the devices caps for the "VIDEO_CAPTURE" flag.
#https://github.com/Xpra-org/xpra/issues/1596
CHECK_VIRTUAL_CAPTURE = envbool("XPRA_CHECK_VIRTUAL_CAPTURE", not (is_Ubuntu() or is_Debian()))


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
def check_virtual_dir(warn=True) -> bool:
    if not os.path.exists(v4l2_virtual_dir) or not os.path.isdir(v4l2_virtual_dir):
        if warn:
            log.warn("Warning: webcam forwarding is disabled")
            log.warn(" the virtual video directory '%s' was not found", v4l2_virtual_dir)
            log.warn(" make sure that the 'v4l2loopback' kernel module is installed and loaded")
            log.warn(" or use the 'webcam=no' option")
        return False
    return True

def query_video_device(device) -> Dict[str,Any]:
    try:
        # pylint: disable=import-outside-toplevel
        from xpra.codecs.v4l2.pusher import query_video_device as v4l_query_video_device
        return v4l_query_video_device(device)
    except ImportError as e:
        log(f"query_video_device({device}) no v4l2 module: {e}")
        return {}


def get_virtual_video_devices(capture_only=True) -> Dict[int, Dict]:
    log(f"get_virtual_video_devices({capture_only}) CHECK_VIRTUAL_CAPTURE={CHECK_VIRTUAL_CAPTURE}")
    if not check_virtual_dir(False):
        return {}
    contents = os.listdir(v4l2_virtual_dir)
    devices = {}
    for f in sorted(contents):
        if not f.startswith("video"):
            continue
        try:
            no_str = f[len("video"):]
            no = int(no_str)
            assert no>=0
        except (TypeError, ValueError, AssertionError):
            continue
        dev_file = f"/dev/{f}"
        dev_info = query_video_device(dev_file)
        if CHECK_VIRTUAL_CAPTURE and capture_only and not _can_capture_video(dev_file, dev_info):
            continue
        info = {"device" : dev_file}
        info.update(dev_info)
        if "card" not in dev_info:
            #look up the name from the v4l2 virtual dir:
            dev_dir = os.path.join(v4l2_virtual_dir, f)
            if not os.path.isdir(dev_dir):
                continue
            dev_name = os.path.join(dev_dir, "name")
            try:
                with open(dev_name, "r", encoding="latin1") as df:
                    name = df.read().replace("\n", "")
                info["card"] = name
            except OSError:
                pass
        devices[no] = info
    log(f"devices: {devices}")
    log(f"found {len(devices)} virtual video devices")
    return devices

def get_all_video_devices(capture_only=True) -> Dict[int,Dict[str,Any]]:
    contents = os.listdir("/dev")
    devices : Dict[int,Dict[str,Any]] = {}
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
            no_str = f[len("video"):]
            no = int(no_str)
            assert no>=0
        except (TypeError, ValueError, AssertionError):
            continue
        dev_info = query_video_device(dev_file)
        if capture_only and not _can_capture_video(dev_file, dev_info):
            continue
        info = {"device" : dev_file}
        info.update(dev_info)
        devices[no] = info
    return devices


_watch_manager = None
_notifier = None

def _video_device_file_filter(event) -> bool:
    # return True to stop processing of event (to "stop chaining")
    return not event.pathname.startswith("/dev/video")


def add_video_device_change_callback(callback:Callable) -> None:
    # pylint: disable=import-outside-toplevel
    from xpra.platform.webcam import _video_device_change_callbacks, _fire_video_device_change
    global _watch_manager, _notifier
    try:
        import pyinotify
    except ImportError as e:
        log.error("Error: cannot watch for video device changes without pyinotify:")
        log.estr(e)
        return
    log(f"add_video_device_change_callback({callback}) pyinotify={pyinotify}")

    if not _watch_manager:
        class EventHandler(pyinotify.ProcessEvent):
            def process_IN_CREATE(self, event):
                _fire_video_device_change(True, event.pathname)

            def process_IN_DELETE(self, event):
                _fire_video_device_change(False, event.pathname)

        _watch_manager = pyinotify.WatchManager()
        mask = pyinotify.IN_DELETE | pyinotify.IN_CREATE  #@UndefinedVariable
        handler = EventHandler(pevent=_video_device_file_filter)
        _notifier = pyinotify.ThreadedNotifier(_watch_manager, handler)
        _notifier.daemon = True
        wdd = _watch_manager.add_watch('/dev', mask)
        log("watching for video device changes in /dev")
        log(f"notifier={_notifier}, watch={wdd}")
        _notifier.start()
    _video_device_change_callbacks.append(callback)
    #for running standalone:
    #notifier.loop()

def remove_video_device_change_callback(callback:Callable) -> None:
    # pylint: disable=import-outside-toplevel
    from xpra.platform.webcam import _video_device_change_callbacks
    global _watch_manager, _notifier
    if not _watch_manager:
        log.error("Error: cannot remove video device change callback, no watch manager!")
        return
    if callback not in _video_device_change_callbacks:
        log.error("Error: video device change callback not found, cannot remove it!")
        return
    log(f"remove_video_device_change_callback({callback})")
    _video_device_change_callbacks.remove(callback)
    if not _video_device_change_callbacks:
        log("last video device change callback removed, closing the watch manager")
        #we can close it:
        if _notifier:
            try:
                _notifier.stop()
            except Exception:
                pass
            _notifier = None
        if _watch_manager:
            try:
                _watch_manager.close()
            except Exception:
                pass
            _watch_manager = None
