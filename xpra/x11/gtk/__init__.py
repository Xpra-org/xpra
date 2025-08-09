# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.env import envbool

if not envbool("XPRA_GTK", True):
    raise ImportError("gtk is disabled")

from xpra.x11.gtk.error import inject_gdk
inject_gdk()
