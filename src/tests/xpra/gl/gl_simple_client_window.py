# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pygtk
pygtk.require('2.0')
import gtk

from xpra.log import Logger
log = Logger()

from tests.xpra.gl.gl_simple_backing import GLTestBacking


class GLSimpleClientWindow(gtk.Window):

    def __init__(self, client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay):
        log("GLSimpleClientWindow(..)")
        gtk.Window.__init__(self)
        self.set_reallocate_redraws(True)
        self._backing = GLTestBacking(wid, w, h, False, None)
        self.add(self._backing.glarea)
