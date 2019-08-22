# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common import gi_init
from gi.repository import GObject               #@UnresolvedImport @UnusedImport

from xpra.client.gl.gtk3.gl_client_window import GLClientWindowBase
from xpra.client.gl.gtk3.gl_window_backing import GLPixmapBacking
from xpra.client.gl.gtk_base.gtkgl_check import check_support

assert check_support
assert gi_init

class GLClientWindow(GLClientWindowBase):

    __gsignals__ = GLClientWindowBase.__common_gsignals__

    def get_backing_class(self):
        return GLPixmapBacking

GObject.type_register(GLClientWindow)
