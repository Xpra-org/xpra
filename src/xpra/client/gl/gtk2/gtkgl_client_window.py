# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject

from xpra.client.gl.gtk2.gl_client_window import GLClientWindowBase
from xpra.client.gl.gtk2.gl_window_backing import GLPixmapBacking
from xpra.client.gl.gtk_base.gtkgl_check import check_support
assert check_support


class GLClientWindow(GLClientWindowBase):

    __gsignals__ = GLClientWindowBase.__common_gsignals__

    def get_backing_class(self):
        return GLPixmapBacking


gobject.type_register(GLClientWindow)
