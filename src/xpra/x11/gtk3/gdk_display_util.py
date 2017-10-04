# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def verify_gdk_display(display_name):
    # Now we can safely load gtk and connect:
    from xpra.scripts.main import no_gtk
    no_gtk()
    from xpra.gtk_common.gobject_compat import import_gdk3, import_glib
    gdk = import_gdk3()
    glib = import_glib()
    glib.threads_init()
    display = gdk.Display.open(display_name)
    assert display, "failed to open display %s" % display_name
    manager = gdk.DisplayManager.get()
    default_display = manager.get_default_display()
    if default_display is not None and default_display!=display:
        default_display.close()
    manager.set_default_display(display)
    return display
