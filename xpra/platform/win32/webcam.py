# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.win32.constants import WM_DEVICECHANGE
from xpra.platform.win32.events import get_win32_event_listener

from xpra.log import Logger

log = Logger("webcam")


def get_directshow_devices() -> dict[int, dict]:
    """
    Return a dict of {device_index: info_dict} for all DirectShow video input
    devices, delegating to comtypes_webcam.  Returns an empty dict if
    comtypes or DirectShow.tlb is unavailable.
    """
    try:
        from xpra.platform.win32.comtypes_util import COMTYPES_ENABLED
        if COMTYPES_ENABLED:
            from xpra.platform.win32.comtypes_webcam import get_video_devices
            return get_video_devices()
    except Exception as e:
        log("get_directshow_devices() error: %s", e)
    return {}


def _get_directshow_devices() -> dict[int, dict]:
    return get_directshow_devices()


def _find_directshow_index(device_str: str, ds_devices: dict[int, dict]) -> int:
    """
    Map *device_str* to a DirectShow device index.

    Matches against:
    - a bare integer index ("0", "1", ...)
    - the "device" path stored in the device info dict (DevicePath)
    - automatic device selection values
    """
    if device_str in ("auto", "on", "yes", "true"):
        return next(iter(ds_devices), 0)
    try:
        idx = int(device_str)
        if idx in ds_devices:
            return idx
    except ValueError:
        pass
    for idx, info in ds_devices.items():
        if info.get("device") == device_str:
            return idx
    return 0


def get_all_video_devices(capture_only=True):
    try:
        from xpra.platform.win32.comtypes_util import COMTYPES_ENABLED
        if COMTYPES_ENABLED:
            from xpra.platform.win32.comtypes_webcam import get_video_devices
            return get_video_devices()
    except Exception as e:
        log("get_all_video_devices(%s)", capture_only, exc_info=True)
        log.warn("Warning: failed to load native webcam support:")
        log.warn(" %s", e)
    return {}


def _device_change_callback(*args):
    log("device_change(%s)", args)
    from xpra.platform.webcam import _fire_video_device_change
    _fire_video_device_change()


def add_video_device_change_callback(callback):
    from xpra.platform.webcam import _video_device_change_callbacks
    if len(_video_device_change_callbacks) == 0:
        # first callback added, register our handler:
        el = get_win32_event_listener()
        if el:
            el.add_event_callback(WM_DEVICECHANGE, callback)
    _video_device_change_callbacks.append(_device_change_callback)


def remove_video_device_change_callback(callback):
    from xpra.platform.webcam import _video_device_change_callbacks
    if callback in _video_device_change_callbacks:
        _video_device_change_callbacks.remove(callback)
    if len(_video_device_change_callbacks) == 0:
        # none left, stop listening
        el = get_win32_event_listener(False)
        if el:
            el.remove_event_callback(WM_DEVICECHANGE, _device_change_callback)
