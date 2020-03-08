# This file is part of Xpra.
# Copyright (C) 2017-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def verify_gdk_display(display_name):
    # Now we can safely load gtk and connect:
    import gi
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk
    display = Gdk.Display.open(display_name)
    if not display:
        from xpra.scripts.config import InitException
        raise InitException("failed to open display %s" % display_name)
    manager = Gdk.DisplayManager.get()
    default_display = manager.get_default_display()
    if default_display is not None and default_display!=display:
        default_display.close()
    manager.set_default_display(display)
    return display
