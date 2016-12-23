#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.log import Logger
log = Logger("sound")


def get_x11_property(atom_name):
    from xpra.os_util import WIN32, OSX
    if WIN32 or OSX:
        return ""
    try:
        from gtk import gdk
        root = gdk.get_default_root_window()
        atom = gdk.atom_intern(atom_name)
        p = root.property_get(atom)
        if p is None:
            return ""
        v = p[2]
        log("get_x11_property(%s)=%s", atom_name, v)
        return v
    except:
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
