# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gi

from xpra.os_util import is_X11

gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')

if is_X11():
    try:
        from xpra.x11.gtk3.gdk_display_source import init_gdk_display_source
        init_gdk_display_source()
    except ImportError:
        from xpra.log import Logger
        log = Logger("gtk", "client")
        log.warn("Warning: cannot import gtk3 x11 display source", exc_info=True)
