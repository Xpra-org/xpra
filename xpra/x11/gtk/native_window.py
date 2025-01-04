# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import

GdkX11 = gi_import("GdkX11")


def GDKX11Window(*args, **kwargs) -> GdkX11.X11Window:
    # pylint: disable=import-outside-toplevel
    from xpra.gtk.window import new_GDKWindow
    return new_GDKWindow(GdkX11.X11Window, *args, **kwargs)
