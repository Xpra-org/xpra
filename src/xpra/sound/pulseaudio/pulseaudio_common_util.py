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
        from xpra.x11.gtk_x11.gdk_display_source import init_display_source
        init_display_source()
        from xpra.gtk_common.gobject_compat import import_gdk
        root = import_gdk().get_default_root_window()
        from xpra.x11.gtk_x11.prop import prop_get
        v = prop_get(root, atom_name, "latin1", ignore_errors=True, raise_xerrors=False)
        log("get_x11_property(%s)=%s", atom_name, v)
        return v
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
