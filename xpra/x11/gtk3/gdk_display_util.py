# This file is part of Xpra.
# Copyright (C) 2017-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

def verify_gdk_display(display_name):
    # pylint: disable=import-outside-toplevel
    # Now we can safely load gtk and connect:
    import gi
    gi.require_version("Gdk", "3.0")  # @UndefinedVariable
    from gi.repository import Gdk  # @UnresolvedImport
    display = Gdk.Display.open(display_name)
    if not display:
        from xpra.scripts.config import InitException
        raise InitException(f"failed to open display {display_name!r}")
    manager = Gdk.DisplayManager.get()
    default_display = manager.get_default_display()
    if default_display is not None and default_display!=display:
        default_display.close()
    manager.set_default_display(display)
    return display
