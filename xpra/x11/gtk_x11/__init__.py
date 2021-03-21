# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GdkX11', '3.0')

from gi.repository import GdkX11  #pylint: disable=wrong-import-position
assert GdkX11

def GDKX11Window(*args, **kwargs) -> GdkX11.X11Window:
    from xpra.gtk_common.gtk_util import new_GDKWindow
    return new_GDKWindow(GdkX11.X11Window, *args, **kwargs)
