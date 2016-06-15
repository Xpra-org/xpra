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
    return {}

def add_video_device_change_callback(callback):
    if get_win32_event_listener:
        def device_change(*args):
            log("device_change(%s)", args)
            callback()
        get_win32_event_listener().add_event_callback(WM_DEVICECHANGE, callback)

def remove_video_device_change_callback(callback):
    if get_win32_event_listener:
        get_win32_event_listener().add_event_callback(WM_DEVICECHANGE, callback)
