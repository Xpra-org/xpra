# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("webcam")


def get_all_video_devices(capture_only=True):
    try:
        from xpra.platform.win32.win32_webcam import get_video_devices
        return get_video_devices()
    except ImportError as e:
        log("get_all_video_devices(%s) cannot import webcam native support: %s", capture_only, e)
    return {}
