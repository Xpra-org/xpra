# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()

from PyQt4.QtGui import QPixmap, QImage
from xpra.client.qt4.scheduler import getQtScheduler
from xpra.client.window_backing_base import WindowBackingBase


"""
This is the gtk2 version.
(works much better than gtk3!)
Superclass for PixmapBacking and GLBacking
"""
class QtPixmapBacking(WindowBackingBase):

    def __init__(self, wid, w, h):
        WindowBackingBase.__init__(self, wid, getQtScheduler().idle_add)

    def init(self, w, h):
        #TODO: repaint from old backing!
        #old_backing = self._backing
        assert w<32768 and h<32768, "dimensions too big: %sx%s" % (w, h)
        self._backing = QPixmap(w, h)
        self._backing.fill()
        #QPixmap.copy(...)

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        image = QImage(img_data, width, height, rowstride, QImage.Format_RGB888)
        log.info("do_paint_rgb24(..) image=%s", image)
        return True
