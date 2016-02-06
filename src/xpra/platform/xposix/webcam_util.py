# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger("client")
from xpra.util import engs


def get_virtual_video_devices():
    log("get_virtual_video_devices")
    v4l2_virtual_dir = "/sys/devices/virtual/video4linux"
    if not os.path.exists(v4l2_virtual_dir) or not os.path.isdir(v4l2_virtual_dir):
        log.warn("Warning: webcam forwarding disabled")
        log.warn(" the virtual video directory %s was not found", v4l2_virtual_dir)
        log.warn(" make sure that the v4l2loopback kernel module is installed and loaded")
        return []
    contents = os.listdir(v4l2_virtual_dir)
    devices = []
    for f in contents:
        if not f.startswith("video"):
            continue
        try:
            no = int(f[len("video"):])
            assert no>=0
        except:
            continue
        dev_dir = os.path.join(v4l2_virtual_dir, f)
        if not os.path.isdir(dev_dir):
            continue
        dev_name = os.path.join(dev_dir, "name")
        try:
            name = open(dev_name).read().replace("\n", "")
            log("found %s: %s", f, name)
        except:
            continue
        dev_file = "/dev/%s" % f
        devices.append(dev_file)
    log("devices: %s", devices)
    log("found %i virtual video device%s", len(devices), engs(devices))
    return devices

def get_all_video_devices():
    contents = os.listdir("/dev")
    devices = []
    for f in contents:
        if not f.startswith("video"):
            continue
        dev_file = "/dev/%s" % f
        if not os.path.isfile(dev_file):
            continue
        try:
            no = int(f[len("video"):])
            assert no>=0
        except:
            continue
        devices.append(f)
    return devices


def main():
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        from xpra.log import add_debug_category
        add_debug_category("webcam")

    from xpra.platform import program_context
    with program_context("Webcam Info", "Webcam Info"):
        devices = get_virtual_video_devices()
        log.info("Found %i virtual video device%s:", len(devices), engs(devices))
        for d in devices:
            log.info("%s", d)

if __name__ == "__main__":
    main()
