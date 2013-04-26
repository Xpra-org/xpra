# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from wimpiggy.gobject_compat import import_gobject3, import_gtk3, import_gdk3
gobject = import_gobject3()
gtk = import_gtk3()
gdk = import_gdk3()

from xpra.client.client_window_base import ClientWindowBase
from wimpiggy.log import Logger
log = Logger()


"""
GTK3 version of the ClientWindow class
"""
class ClientWindow(ClientWindowBase):

    WINDOW_POPUP = gtk.WindowType.POPUP
    WINDOW_TOPLEVEL = gtk.WindowType.TOPLEVEL
    #where have those values gone?
    #gi/pygtk3 docs are terrible for this
    WINDOW_EVENT_MASK = 0
    OR_TYPE_HINTS = []
    NAME_TO_HINT = { }
    SCROLL_MAP = {}

    def init_window(self):
        #TODO: no idea how to do this with gtk3
        #maybe not even possible..
        gtk.Window.__init__(self)

    def is_mapped(self):
        return self.get_mapped()

    def get_window_geometry(self):
        x, y = self.get_position()
        w, h = self.get_size()
        return (x, y, w, h)

    def apply_geometry_hints(self, hints):
        """ we convert the hints as a dict into a gdk.Geometry + gdk.WindowHints """
        wh = gdk.WindowHints
        name_to_hint = {"maximum-size"  : wh.MAX_SIZE,
                        "max_width"     : wh.MAX_SIZE,
                        "max_height"    : wh.MAX_SIZE,
                        "minimum-size"  : wh.MIN_SIZE,
                        "min_width"     : wh.MIN_SIZE,
                        "min_height"    : wh.MIN_SIZE,
                        "base-size"     : wh.BASE_SIZE,
                        "base_width"    : wh.BASE_SIZE,
                        "base_height"   : wh.BASE_SIZE,
                        "increment"     : wh.RESIZE_INC,
                        "width_inc"     : wh.RESIZE_INC,
                        "height_inc"    : wh.RESIZE_INC,
                        "min_aspect_ratio"  : wh.ASPECT,
                        "max_aspect_ratio"  : wh.ASPECT,
                        }
        #these fields can be copied directly to the gdk.Geometry as ints:
        INT_FIELDS= ["min_width",    "min_height",
                        "max_width",    "max_height",
                        "base_width",   "base_height",
                        "width_inc",    "height_inc"]
        ASPECT_FIELDS = {
                        "min_aspect_ratio"  : "min_aspect",
                        "max_aspect_ratio"  : "max_aspect",
                         }
        geom = gdk.Geometry()
        mask = 0
        for k,v in hints.items():
            if k in INT_FIELDS:
                setattr(geom, k, int(v))
                mask |= int(name_to_hint.get(k, 0))
            elif k in ASPECT_FIELDS:
                field = ASPECT_FIELDS.get(k)
                setattr(geom, field, float(v))
                mask |= int(name_to_hint.get(k, 0))
        hints = gdk.WindowHints(mask)
        self.set_geometry_hints(None, geom, hints)

    def queue_draw(self, x, y, width, height):
        self.queue_draw_area(x, y, width, height)


gobject.type_register(ClientWindow)
