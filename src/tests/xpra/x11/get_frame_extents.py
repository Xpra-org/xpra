#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.log import Logger
log = Logger("dbus")


def main(args):
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("GTK-Menu Info"):
        enable_color()
        log.enable_debug()
        try:
            from xpra.x11.gtk2.gdk_display_source import display    #@UnresolvedImport
            assert display
            wid = sys.argv[1]
            if wid.startswith("0x"):
                xid = int(wid[2:], 16)
            else:
                xid = int(wid)
        except Exception as e:
            log.error("Error: invalid window id: %s", e)
            log.error("usage:")
            log.error(" %s WINDOWID", sys.argv[0])
        else:
            from gtk import gdk
            w = gdk.window_foreign_new(xid)
            from xpra.x11.gtk_x11.prop import prop_get, log as x11log
            x11log.enable_debug()
            def pget(key, etype):
                return prop_get(w, key, etype, ignore_errors=False, raise_xerrors=True)
            log.info("_NET_FRAME_EXTENTS=%s", pget("_NET_FRAME_EXTENTS", ["u32"]))


if __name__ == '__main__':
    sys.exit(main(sys.argv))
