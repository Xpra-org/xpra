# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("webcam")


def get_virtual_video_devices():
    return {}

def get_all_video_devices():
    #None means we can't enumerate,
    #this is different from an empty dict!
    return None


from xpra.platform import platform_import
platform_import(globals(), "webcam", False,
                "get_virtual_video_devices",
                "get_all_video_devices")


def main():
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        from xpra.log import add_debug_category
        add_debug_category("webcam")

    from xpra.util import engs, print_nested_dict
    from xpra.platform import program_context
    with program_context("Webcam Info", "Webcam Info"):
        devices = get_virtual_video_devices() or {}
        log.info("Found %i virtual video device%s:", len(devices), engs(devices))
        print_nested_dict(devices)
        all_devices = get_all_video_devices() or {}
        log.info("Found %i video device%s in total:", len(all_devices), engs(all_devices))
        print_nested_dict(all_devices)

if __name__ == "__main__":
    main()
