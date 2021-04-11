# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def verify_gdk_display(display_name):
    # Now we can safely load gtk and connect:
    from xpra.gtk_common.gobject_compat import import_gdk3
    gdk = import_gdk3()
    display = gdk.Display.open(display_name)
    if not display:
        from xpra.scripts.config import InitException
        raise InitException("failed to open display %s" % display_name)
    manager = gdk.DisplayManager.get()
    default_display = manager.get_default_display()
    if default_display is not None and default_display!=display:
        default_display.close()
    manager.set_default_display(display)
    return display
