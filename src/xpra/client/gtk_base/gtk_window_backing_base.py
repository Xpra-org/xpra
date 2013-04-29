# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pygtk3 vs pygtk2 (sigh)
from xpra.gtk_common.gobject_compat import import_gobject
gobject = import_gobject()

from xpra.client.window_backing_base import WindowBackingBase
from xpra.log import Logger
log = Logger()


"""
Generic superclass for Backing code,
see CairoBacking and PixmapBacking for actual implementations
"""
class GTKWindowBacking(WindowBackingBase):
    def __init__(self, wid):
        WindowBackingBase.__init__(self, wid, gobject.idle_add)


    def cairo_draw(self, context):
        self.cairo_draw_from_drawable(context, self._backing)

    def cairo_draw_from_drawable(self, context, drawable):
        import cairo
        try:
            context.set_source_pixmap(drawable, 0, 0)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
            return True
        except KeyboardInterrupt:
            raise
        except:
            log.error("cairo_draw(%s)", context, exc_info=True)
            return False
