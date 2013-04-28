# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from PyQt4 import QtGui

from xpra.client.client_window_base import ClientWindowBase
from xpra.log import Logger
log = Logger()


"""
Qt4 version of the ClientWindow class
"""
class ClientWindow(QtGui.QMainWindow, ClientWindowBase):

    NAME_TO_HINT = { }

    def __init__(self, *args):
        ClientWindowBase.__init__(self, *args)

    def init_window(self, metadata):
        QtGui.QWidget.__init__(self, None)
        ClientWindowBase.init_window(self, metadata)

    def show_all(self):
        pass

    def is_mapped(self):
        return self.isVisible()

    def is_realized(self):
        return self.isVisible()

    def set_modal(self, modal):
        pass

    def set_wmclass(self, *wmclass):
        pass

    def gdk_window(self):
        return  None

    def set_title(self, title):
        pass

    def new_backing(self, w, h):
        return object()

    def get_window_geometry(self):
        qrect = self.geometry()
        return qrect.getRect()

    def apply_geometry_hints(self, hints):
        pass
        #self.set_geometry_hints(None, **hints)

    def queue_draw(self, x, y, width, height):
        pass

    def do_expose_event(self, event):
        log.info("do_expose_event(%s) area=%s", event, event.area)
