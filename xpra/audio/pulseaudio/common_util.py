#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.util.env import envbool, first_time
from xpra.log import Logger

log = Logger("audio")


def get_x11_property(atom_name: str) -> str:
    from xpra.os_util import OSX, POSIX
    if envbool("XPRA_NOX11", not POSIX or OSX):
        return ""
    display = os.environ.get("DISPLAY")
    if not display:
        return ""
    try:
        from xpra.x11 import bindings
        assert bindings
    except ImportError:
        from xpra.util.env import envint
        if first_time("pulse-x11-bindings") and not envint("XPRA_SKIP_UI", 0):
            log.info("unable to query display properties without the X11 bindings")
        return ""
    try:
        from xpra.gtk.error import xswallow
        from xpra.x11.bindings.posix_display_source import X11DisplayContext
        from xpra.x11.bindings.window import X11WindowBindingsInstance
    except ImportError as e:
        log("get_x11_property(%s)", atom_name, exc_info=True)
        log.error("Error: unable to query X11 property '%s':", atom_name)
        log.estr(e)
        return ""
    try:
        with X11DisplayContext(display):
            with xswallow:
                X11Window = X11WindowBindingsInstance()
                root = X11Window.get_root_xid()
                log("getDefaultRootWindow()=%#x", root)
                try:
                    prop = X11Window.XGetWindowProperty(root, atom_name, "STRING")
                except Exception as e:
                    log("cannot get X11 property '%s': %s", atom_name, e)
                    return ""
                log("XGetWindowProperty(..)=%s", prop)
                if prop:
                    from xpra.x11.prop_conv import prop_decode
                    v = prop_decode("latin1", prop)
                    log("get_x11_property(%s)=%s", atom_name, v)
                    return v
                return ""
    except Exception as e:
        log("get_x11_property(%s)", atom_name, exc_info=True)
        if not os.environ.get("WAYLAND_DISPLAY"):
            log.error("Error: cannot get X11 property '%s'", atom_name)
            log.estr(e)
    return ""


def get_pulse_server_x11_property() -> str:
    return get_x11_property("PULSE_SERVER")


def get_pulse_id_x11_property() -> str:
    return get_x11_property("PULSE_ID")


def main():
    if "-v" in sys.argv:
        log.enable_debug()
    print("PULSE_SERVER=%r" % get_pulse_server_x11_property())
    print("PULSE_ID=%r" % get_pulse_id_x11_property())


if __name__ == "__main__":
    main()
