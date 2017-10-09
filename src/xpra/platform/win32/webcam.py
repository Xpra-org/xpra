# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("webcam")


try:
    from win32con import WM_DEVICECHANGE
    from xpra.platform.win32.win32_events import get_win32_event_listener
except ImportError as e:
    WM_DEVICECHANGE = 7
    get_win32_event_listener = None
    log("cannot watch for device changes: %s", e)


def get_all_video_devices(capture_only=True):
    try:
        from xpra.platform.win32.win32_webcam import get_video_devices
        return get_video_devices()
    except ImportError as e:
        log("get_all_video_devices(%s) cannot import webcam native support: %s", capture_only, e)
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
    if not get_win32_event_listener:
        return
    from xpra.platform.webcam import _video_device_change_callbacks
    if len(_video_device_change_callbacks)==0:
        #first callback added, register our handler:
        get_win32_event_listener().add_event_callback(WM_DEVICECHANGE, callback)
    _video_device_change_callbacks.append(_device_change_callback)

def remove_video_device_change_callback(callback):
    if not get_win32_event_listener:
        return
    from xpra.platform.webcam import _video_device_change_callbacks
    if callback in _video_device_change_callbacks:
        _video_device_change_callbacks.remove(callback)
    if len(_video_device_change_callbacks)==0:
        #none left, stop listening
        get_win32_event_listener().remove_event_callback(WM_DEVICECHANGE, _device_change_callback)
