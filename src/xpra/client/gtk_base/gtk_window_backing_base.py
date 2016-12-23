# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


#pygtk3 vs pygtk2 (sigh)
from xpra.gtk_common.gobject_compat import import_glib, import_cairo, is_gtk3
glib = import_glib()
cairo   = import_cairo()

from xpra.util import envbool
from xpra.os_util import WIN32, OSX
from xpra.client.window_backing_base import WindowBackingBase
from xpra.log import Logger
log = Logger("paint")

#transparency with GTK:
# - on MS Windows: not supported
# - on OSX: only with gtk3
DEFAULT_HAS_ALPHA = not WIN32 and (not OSX or is_gtk3())
GTK_ALPHA_SUPPORTED = envbool("XPRA_ALPHA", DEFAULT_HAS_ALPHA)


"""
Generic GTK superclass for Backing code (for both GTK2 and GTK3),
see CairoBacking, PixmapBacking and TrayBacking for actual implementations.
(some may override HAS_ALPHA, TrayBacking does)
"""
class GTKWindowBacking(WindowBackingBase):

    HAS_ALPHA = GTK_ALPHA_SUPPORTED

    def __init__(self, wid, window_alpha):
        WindowBackingBase.__init__(self, wid, window_alpha and self.HAS_ALPHA, glib.idle_add)
