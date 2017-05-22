#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

def pam_open(xdisplay, xauth_data=None):
    try:
        from xpra.server.pam import pam_session
    except ImportError as e:
        sys.stderr.write("No pam support: %s\n" % e)
        return False
    items = {
           "XDISPLAY" : xdisplay
           }
    if xauth_data:
        items["XAUTHDATA"] = xauth_data
    env = {
           #"XDG_SEAT"               : "seat1",
           #"XDG_VTNR"               : "0",
           "XDG_SESSION_TYPE"       : "x11",
           #"XDG_SESSION_CLASS"      : "user",
           "XDG_SESSION_DESKTOP"    : "xpra",
           }
    ps = pam_session()
    ps.start()
    ps.set_env(env)
    ps.set_items(items)
    ps.open()
    ps.close()

def main():
    assert len(sys.argv)==3
    display_name = sys.argv[1]
    xauth_data = sys.argv[2]
    pam_open(display_name, xauth_data)


if __name__ == "__main__":
    main()
