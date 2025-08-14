#!/usr/bin/env python3

from xpra.os_util import gi_import

from xpra.x11.gtk.display_source import init_gdk_display_source
from xpra.x11.prop import prop_get
from xpra.x11.bindings.core import constants
from xpra.x11.bindings.window import X11WindowBindings
from xpra.x11.error import xsync


CurrentTime = 0


def main():
    init_gdk_display_source()

    gi_import("GdkX11")
    Gtk = gi_import("Gtk")
    Gdk = gi_import("Gdk")
    GLib = gi_import("GLib")

    root = Gdk.get_default_root_window()

    win = Gtk.Window()
    win.realize()
    X11Window = X11WindowBindings()

    def print_extents():
        v = prop_get(win.get_window(), "_NET_FRAME_EXTENTS", ["u32"], ignore_errors=False)
        print("_NET_FRAME_EXTENTS: %s" % str(v))
        with xsync:
            SubstructureNotifyMask = constants["SubstructureNotifyMask"]
            SubstructureRedirectMask = constants["SubstructureRedirectMask"]
            event_mask = SubstructureNotifyMask | SubstructureRedirectMask
            X11Window.sendClientMessage(root.get_xid(), win.get_window().get_xid(), False, event_mask,
                                        "_NET_REQUEST_FRAME_EXTENTS")
            print("sending _NET_REQUEST_FRAME_EXTENTS to %#x for %#x" % (root.get_xid(), win.get_window().get_xid()))
        return v is None
    print_extents()
    GLib.timeout_add(1000, print_extents)
    Gtk.main()
    return 0


if __name__ == '__main__':
    main()
