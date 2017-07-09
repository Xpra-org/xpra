# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def init_display_source():
    from xpra.gtk_common.gobject_compat import is_gtk3
    if is_gtk3():
        from xpra.x11.gtk3.gdk_display_source import init_gdk_display_source    #@UnresolvedImport @UnusedImport
    else:
        from xpra.x11.gtk2.gdk_display_source import init_gdk_display_source    #@UnresolvedImport @Reimport
    init_gdk_display_source()
