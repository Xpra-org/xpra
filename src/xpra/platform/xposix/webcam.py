# This file is part of Xpra.
# Copyright (C) 2016-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections import OrderedDict

from xpra.log import Logger
log = Logger("webcam")
from xpra.util import engs, envbool
from xpra.os_util import is_Ubuntu, is_Debian

#on Debian and Ubuntu, the v4l2loopback device is created with exclusive_caps=1,
#so we cannot check the devices caps for the "VIDEO_CAPTURE" flag.
#see http://xpra.org/trac/ticket/1596
CHECK_VIRTUAL_CAPTURE = envbool("XPRA_CHECK_VIRTUAL_CAPTURE", not (is_Ubuntu() or is_Debian()))


def _can_capture_video(dev_file, dev_info):
    if not dev_info:
        return False
    caps = dev_info.get("capabilities", [])
    if "DEVICE_CAPS" in caps:
        caps = dev_info.get("device_caps", [])
    if not "VIDEO_CAPTURE" in caps:
        log("device %s does not support video capture, capabilities=%s", dev_file, caps)
        return False
    return True

v4l2_virtual_dir = "/sys/devices/virtual/video4linux"
def check_virtual_dir(warn=True):
    global v4l2_virtual_dir
    if not os.path.exists(v4l2_virtual_dir) or not os.path.isdir(v4l2_virtual_dir):
        if warn:
            log.warn("Warning: webcam forwarding is disabled")
            log.warn(" the virtual video directory '%s' was not found", v4l2_virtual_dir)
            log.warn(" make sure that the 'v4l2loopback' kernel module is installed and loaded")
        return False
    return True

def query_video_device(device):
    try:
        from xpra.codecs.v4l2.pusher import query_video_device as v4l_query_video_device
        return v4l_query_video_device(device)
    except ImportError:
        return {}


def get_virtual_video_devices(capture_only=True):
    log("get_virtual_video_devices(%s) CHECK_VIRTUAL_CAPTURE=%s", capture_only, CHECK_VIRTUAL_CAPTURE)
    if not check_virtual_dir(False):
        return []
    contents = os.listdir(v4l2_virtual_dir)
    devices = OrderedDict()
    for f in sorted(contents):
        if not f.startswith("video"):
            continue
        try:
            no = int(f[len("video"):])
            assert no>=0
        except:
            continue
        dev_file = "/dev/%s" % f
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
                name = open(dev_name).read().replace("\n", "")
                info["card"] = name
            except:
                pass
        devices[no] = info
    log("devices: %s", devices)
    log("found %i virtual video device%s", len(devices), engs(devices))
    return devices

def get_all_video_devices(capture_only=True):
    contents = os.listdir("/dev")
    devices = {}
    device_paths = set()
    for f in contents:
        if not f.startswith("video"):
            continue
        dev_file = "/dev/%s" % f
        try:
            dev_file = os.readlink(dev_file)
        except OSError:
            pass
        if dev_file in device_paths:
            continue
        device_paths.add(dev_file)
        try:
            no = int(f[len("video"):])
            assert no>=0
        except:
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

def _video_device_file_filter(event):
    # return True to stop processing of event (to "stop chaining")
    return not event.pathname.startswith("/dev/video")


def add_video_device_change_callback(callback):
    from xpra.platform.webcam import _video_device_change_callbacks, _fire_video_device_change
    global _watch_manager, _notifier
    try:
        import pyinotify
    except ImportError as e:
        log.error("Error: cannot watch for video device changes without pyinotify:")
        log.error(" %s", e)
        return
    log("add_video_device_change_callback(%s) pyinotify=%s", callback, pyinotify)

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
        _notifier.setDaemon(True)
        wdd = _watch_manager.add_watch('/dev', mask)
        log("watching for video device changes in /dev")
        log("notifier=%s, watch=%s", _notifier, wdd)
        _notifier.start()
    _video_device_change_callbacks.append(callback)
    #for running standalone:
    #notifier.loop()

def remove_video_device_change_callback(callback):
    from xpra.platform.webcam import _video_device_change_callbacks
    global _watch_manager, _notifier
    if not _watch_manager:
        log.error("Error: cannot remove video device change callback, no watch manager!")
        return
    if callback not in _video_device_change_callbacks:
        log.error("Error: video device change callback not found, cannot remove it!")
        return
    log("remove_video_device_change_callback(%s)", callback)
    _video_device_change_callbacks.remove(callback)
    if len(_video_device_change_callbacks)==0:
        log("last video device change callback removed, closing the watch manager")
        #we can close it:
        try:
            _notifier.stop()
        except:
            pass
        _notifier = None
        try:
            _watch_manager.close()
        except:
            pass
        _watch_manager = None
