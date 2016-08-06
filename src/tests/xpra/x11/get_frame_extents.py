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
            xid = 0
            if len(sys.argv)>1:
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
            import gtk
            from gtk import gdk
            def get_frame_extents(window):
                from xpra.x11.gtk_x11.prop import prop_get, log as x11log
                x11log.enable_debug()
                def pget(key, etype):
                    return prop_get(window, key, etype, ignore_errors=False, raise_xerrors=True)
                return pget("_NET_FRAME_EXTENTS", ["u32"])
            if xid>0:
                #show for an existing window:
                w = gdk.window_foreign_new(xid)
                log.info("_NET_FRAME_EXTENTS=%s", get_frame_extents(w))
            else:
                #create a window an send the request:
                root = gdk.get_default_root_window()
                from xpra.gtk_common.gtk_util import WINDOW_TOPLEVEL, get_xwindow
                #code ripped from gtk_client_base:
                from xpra.gtk_common.error import xsync
                from xpra.x11.gtk_x11.send_wm import send_wm_request_frame_extents
                window = gtk.Window(WINDOW_TOPLEVEL)
                window.set_title("Xpra-FRAME_EXTENTS")
                window.connect("destroy", gtk.main_quit)
                window.realize()
                win = window.get_window()
                vbox = gtk.VBox(False, 0)
                btn = gtk.Button("request frame extents")
                def request_frame_extents(*args):
                    with xsync:
                        log("request_frame_extents() window=%#x", get_xwindow(win))
                        send_wm_request_frame_extents(root, win)
                btn.connect("clicked", request_frame_extents)
                vbox.pack_start(btn, expand=False, fill=False, padding=10)
                label = gtk.Label()
                vbox.add(label)
                window.add(vbox)
                label.set_text(str(get_frame_extents(win)))
                import glib
                def refresh_label():
                    v = get_frame_extents(win)
                    label.set_text(str(v))
                    log.info("_NET_FRAME_EXTENTS=%s", v)
                    return True
                window.realize()
                request_frame_extents()
                glib.timeout_add(5000, window.show_all)
                glib.timeout_add(1000, refresh_label)
                gtk.main()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
