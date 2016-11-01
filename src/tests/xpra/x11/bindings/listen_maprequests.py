# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore
import sys
import gobject
import gtk.gdk
from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.x11.bindings.window_bindings import X11WindowBindings #@UnresolvedImport

class receiver(gobject.GObject):
    __gsignals__ = {"xpra-create-event": one_arg_signal}
    def do_xpra_create_event(self, event):
        print("create-event: %s" % event)
gobject.type_register(receiver)

def main():
    from xpra.x11.gtk2 import gdk_display_source
    assert gdk_display_source
    from xpra.x11.gtk2.gdk_bindings import init_x11_filter, add_catchall_receiver #@UnresolvedImport
    init_x11_filter()

    root_window = gtk.gdk.get_default_root_window()
    root_window.set_events(root_window.get_events() | gtk.gdk.SUBSTRUCTURE_MASK)
    r = receiver()
    add_catchall_receiver("xpra-create-event", r)
    X11WindowBindings().substructureRedirect(root_window.xid)
    gtk.main()


if __name__ == "__main__":
    sys.exit(main())
