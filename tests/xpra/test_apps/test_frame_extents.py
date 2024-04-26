#!/usr/bin/env python3

import gi
gi.require_version('Gtk', '3.0')  # @UndefinedVariable
gi.require_version('Gdk', '3.0')  # @UndefinedVariable
from gi.repository import Gtk, Gdk, GLib, GdkX11  # @UnresolvedImport
assert GdkX11   #this import has side-effects!

from xpra.x11.gtk.display_source import init_gdk_display_source
init_gdk_display_source()
from xpra.x11.gtk.prop import prop_get
from xpra.x11.bindings.window import constants, X11WindowBindings  #@UnresolvedImport
from xpra.gtk.error import xsync
X11Window = X11WindowBindings()

SubstructureNotifyMask = constants["SubstructureNotifyMask"]
SubstructureRedirectMask = constants["SubstructureRedirectMask"]
CurrentTime = 0
root = Gdk.get_default_root_window()


def main():
    win = Gtk.Window()
    win.realize()
    def print_extents():
        v = prop_get(win.get_window(), "_NET_FRAME_EXTENTS", ["u32"], ignore_errors=False)
        print("_NET_FRAME_EXTENTS: %s" % str(v))
        with xsync:
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
