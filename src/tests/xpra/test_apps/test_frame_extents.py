#!/usr/bin/env python

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib

from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
from xpra.x11.gtk_x11.prop import prop_get
from xpra.x11.bindings.window_bindings import constants, X11WindowBindings  #@UnresolvedImport
from xpra.gtk_common.error import xsync
X11Window = X11WindowBindings()

SubstructureNotifyMask = constants["SubstructureNotifyMask"]
SubstructureRedirectMask = constants["SubstructureRedirectMask"]
CurrentTime = 0
root = Gdk.get_default_root_window()


def main():
    init_gdk_display_source()
    win = Gtk.Window()
    win.realize()
    def print_extents():
        v = prop_get(win.get_window(), "_NET_FRAME_EXTENTS", ["u32"], ignore_errors=False)
        print("_NET_FRAME_EXTENTS: %s" % str(v))
        with xsync:
            event_mask = SubstructureNotifyMask | SubstructureRedirectMask
            X11Window.sendClientMessage(root.xid, win.get_window().xid, False, event_mask,
                      "_NET_REQUEST_FRAME_EXTENTS")
            print("sending _NET_REQUEST_FRAME_EXTENTS to %#x for %#x" % (root.xid, win.get_window().xid))
        return v is None
    print_extents()
    GLib.timeout_add(1000, print_extents)
    Gtk.main()
    return 0


if __name__ == '__main__':
    main()
