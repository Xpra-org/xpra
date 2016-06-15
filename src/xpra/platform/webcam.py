#!/usr/bin/env python
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

def add_video_device_change_callback(callback):
    #not implemented here
    pass
def remove_video_device_change_callback(callback):
    #not implemented here
    pass


from xpra.platform import platform_import
platform_import(globals(), "webcam", False,
                "get_virtual_video_devices",
                "get_all_video_devices",
                "add_video_device_change_callback",
                "remove_video_device_change_callback")


def main():
    import sys
    if "-v" in sys.argv or "--verbose" in sys.argv:
        from xpra.log import add_debug_category
        add_debug_category("webcam")
    run = "-r" in sys.argv or "--run" in sys.argv
    if run:
        from xpra.gtk_common.gobject_compat import import_glib, import_gobject
        glib = import_glib()
        gobject = import_gobject()
        gobject.threads_init()

    from xpra.util import engs, print_nested_dict
    from xpra.platform import program_context
    with program_context("Webcam Info", "Webcam Info"):
        devices = get_virtual_video_devices() or {}
        log.info("Found %i virtual video device%s:", len(devices), engs(devices))
        print_nested_dict(devices)
        all_devices = get_all_video_devices() or {}
        log.info("Found %i video device%s in total:", len(all_devices), engs(all_devices))
        print_nested_dict(all_devices)
        
        if run:
            log.info("add watch for video device changes")
            def callback(added, device):
                log.info("video device %s: %s", ["removed", "added"][added], device)
            add_video_device_change_callback(callback)
            log.info("starting main loop")
            main_loop = glib.MainLoop()
            try:
                main_loop.run()
            except KeyboardInterrupt:
                pass
            log.info("terminating, removing callback")
            remove_video_device_change_callback(callback)

if __name__ == "__main__":
    main()
