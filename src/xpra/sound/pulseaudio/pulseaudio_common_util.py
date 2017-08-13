#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.log import Logger
log = Logger("sound")


def get_x11_property(atom_name):
    from xpra.os_util import OSX, POSIX
    if not POSIX or OSX:
        return ""
    display = os.environ.get("DISPLAY")
    if not display:
        return ""
    try:
        from xpra.x11.bindings.posix_display_source import X11DisplayContext    #@UnresolvedImport
        from xpra.x11.bindings.window_bindings import X11WindowBindings
    except ImportError as e:
        log.error("Error: unable to query X11 property '%s':", atom_name)
        log.error(" %s", e)
        return ""
    try:
        with X11DisplayContext(display) as dc:
            X11Window = X11WindowBindings()
            root = X11Window.getDefaultRootWindow()
            log("getDefaultRootWindow()=%#x", root)
            try:
                prop = X11Window.XGetWindowProperty(root, atom_name, "STRING")
            except Exception as e:
                log("cannot get X11 property '%s': %s", atom_name, e)
                return ""
            log("XGetWindowProperty(..)=%s", prop)
            if prop:
                from xpra.x11.prop_conv import prop_decode
                v = prop_decode(dc.display, "latin1", prop)
                log("get_x11_property(%s)=%s", atom_name, v)
                return v
            return ""
    except Exception:
        log.error("Error: cannot get X11 property '%s'", atom_name, exc_info=True)
        log.error(" for python %s", sys.version_info)
        log.error(" xpra command=%s", sys.argv)
    return ""

def get_pulse_server_x11_property():
    return get_x11_property("PULSE_SERVER")

def get_pulse_id_x11_property():
    return get_x11_property("PULSE_ID")


def main():
    if "-v" in sys.argv:
        log.enable_debug()
    print("PULSE_SERVER=%s" % get_pulse_server_x11_property())
    print("PULSE_ID=%s" % get_pulse_id_x11_property())


if __name__ == "__main__":
    main()
