#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.platform import platform_import
from xpra.log import Logger

log = Logger("webcam")


def get_virtual_video_devices() -> dict:
    return {}


def get_all_video_devices():
    # None means we can't enumerate,
    # this is different from an empty dict!
    return None


def add_video_device_change_callback(_callback: Callable):
    # not implemented here
    pass


def remove_video_device_change_callback(_callback: Callable):
    # not implemented here
    pass


_video_device_change_callbacks: list[Callable] = []


def _fire_video_device_change(create=None, pathname=None):
    for x in _video_device_change_callbacks:
        try:
            x(create, pathname)
        except Exception as e:
            log("error on %s", x, exc_info=True)
            log.error("Error: video device change callback error")
            log.estr(e)


platform_import(globals(), "webcam", False,
                "get_virtual_video_devices",
                "get_all_video_devices",
                "add_video_device_change_callback",
                "remove_video_device_change_callback")


def main(argv):
    # pylint: disable=import-outside-toplevel
    if "-v" in argv or "--verbose" in argv:
        from xpra.log import add_debug_category, enable_debug_for
        enable_debug_for("webcam")
        add_debug_category("webcam")
    run = "-r" in argv or "--run" in argv
    from xpra.util.str_fn import print_nested_dict
    from xpra.platform import program_context
    with program_context("Webcam Info", "Webcam Info"):
        devices = get_virtual_video_devices() or {}
        log.info("Found %i virtual video devices:", len(devices))
        print_nested_dict(devices)
        all_devices = get_all_video_devices() or {}
        log.info("Found %i video devices in total:", len(all_devices))
        print_nested_dict(all_devices)

        if run:
            log.info("add watch for video device changes")

            def callback(added=None, device=None):
                if added is not None or device:
                    log.info("video device %s: %s", ["removed", "added"][added], device)
                else:
                    log.info("device change")
            log.info("starting main loop")
            glib = gi_import("GLib")
            main_loop = glib.MainLoop()
            glib.idle_add(add_video_device_change_callback, callback)
            try:
                main_loop.run()
            except KeyboardInterrupt:
                pass
            log.info("terminating, removing callback")
            remove_video_device_change_callback(callback)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
