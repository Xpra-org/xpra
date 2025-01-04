# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.gtk import gdk_display_source

gdk_display_source.init_gdk_display_source()

from xpra.x11.bindings.window import X11WindowBindings

X11Window = X11WindowBindings()

from xpra.x11.server.server_uuid import get_mode, get_uuid

print(f"mode={get_mode()}")
print(f"uuid={get_uuid()}")
