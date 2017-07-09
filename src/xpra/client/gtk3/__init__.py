# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("gtk", "client")

from xpra.os_util import OSX, POSIX
if POSIX and not OSX:
    try:
        from xpra.x11.gtk3.gdk_display_source import init_gdk_display_source
        init_gdk_display_source()
    except ImportError:
        log.warn("cannot import gtk3 x11 display source", exc_info=True)
