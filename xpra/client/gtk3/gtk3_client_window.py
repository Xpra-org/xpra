# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=ungrouped-imports
#pylint: disable=wrong-import-order

from xpra.gtk_common import gi_init
from gi.repository import GObject               #@UnresolvedImport @UnusedImport
from gi.repository import Gtk                   #@UnresolvedImport @UnusedImport
from gi.repository import Gdk                   #@UnresolvedImport @UnusedImport

from xpra.client.gtk_base.gtk_client_window_base import GTKClientWindowBase, HAS_X11_BINDINGS
from xpra.gtk_common.gtk_util import WINDOW_NAME_TO_HINT, BUTTON_MASK
from xpra.os_util import bytestostr
from xpra.log import Logger

log = Logger("gtk", "window")
paintlog = Logger("paint")
metalog = Logger("metadata")


assert gi_init
GTK3_OR_TYPE_HINTS = (Gdk.WindowTypeHint.DIALOG,
                      Gdk.WindowTypeHint.MENU,
                      Gdk.WindowTypeHint.TOOLBAR,
                      #Gdk.WindowTypeHint.SPLASHSCREEN,
                      #Gdk.WindowTypeHint.UTILITY,
                      #Gdk.WindowTypeHint.DOCK,
                      #Gdk.WindowTypeHint.DESKTOP,
                      Gdk.WindowTypeHint.DROPDOWN_MENU,
                      Gdk.WindowTypeHint.POPUP_MENU,
                      Gdk.WindowTypeHint.TOOLTIP,
                      #Gdk.WindowTypeHint.NOTIFICATION,
                      Gdk.WindowTypeHint.COMBO,
                      Gdk.WindowTypeHint.DND)


"""
GTK3 version of the ClientWindow class
"""
class GTK3ClientWindow(GTKClientWindowBase):

    BUTTON_MASK         = BUTTON_MASK
    OR_TYPE_HINTS       = GTK3_OR_TYPE_HINTS
    NAME_TO_HINT        = WINDOW_NAME_TO_HINT

    WINDOW_STATE_FULLSCREEN = Gdk.WindowState.FULLSCREEN
    WINDOW_STATE_MAXIMIZED  = Gdk.WindowState.MAXIMIZED
    WINDOW_STATE_ICONIFIED  = Gdk.WindowState.ICONIFIED
    WINDOW_STATE_ABOVE      = Gdk.WindowState.ABOVE
    WINDOW_STATE_BELOW      = Gdk.WindowState.BELOW
    WINDOW_STATE_STICKY     = Gdk.WindowState.STICKY
    WINDOW_STATE_FOCUSED    = Gdk.WindowState.FOCUSED


    def do_init_window(self, window_type):
        Gtk.Window.__init__(self, type = window_type)

    def init_widget_events(self, widget):
        GTKClientWindowBase.init_widget_events(self, widget)
        widget.connect("draw", self.drawing_area_draw)

    def get_backing_class(self):
        raise NotImplementedError()


    def xget_u32_property(self, target, name):
        if HAS_X11_BINDINGS:
            return GTKClientWindowBase.xget_u32_property(self, target, name)
        #pure Gdk lookup:
        try:
            name_atom = Gdk.Atom.intern(name, False)
            type_atom = Gdk.Atom.intern("CARDINAL", False)
            prop = Gdk.property_get(target, name_atom, type_atom, 0, 9999, False)
            if not prop or len(prop)!=3 or len(prop[2])!=1:
                return  None
            metalog("xget_u32_property(%s, %s)=%s", target, name, prop[2][0])
            return prop[2][0]
        except Exception as e:
            metalog.error("xget_u32_property error on %s / %s: %s", target, name, e)

    def is_mapped(self):
        return self.get_mapped()

    def get_drawing_area_geometry(self):
        gdkwindow = self.drawing_area.get_window()
        x, y = gdkwindow.get_origin()[1:]
        w, h = self.get_size()
        return (x, y, w, h)

    def apply_geometry_hints(self, hints):
        """ we convert the hints as a dict into a gdk.Geometry + gdk.WindowHints """
        wh = Gdk.WindowHints
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
        geom = Gdk.Geometry()
        mask = 0
        for k,v in hints.items():
            k = bytestostr(k)
            if k in INT_FIELDS:
                setattr(geom, k, v)
                mask |= int(name_to_hint.get(k, 0))
            elif k in ASPECT_FIELDS:
                field = ASPECT_FIELDS.get(k)
                setattr(geom, field, float(v))
                mask |= int(name_to_hint.get(k, 0))
        gdk_hints = Gdk.WindowHints(mask)
        metalog("apply_geometry_hints(%s) geometry=%s, hints=%s", hints, geom, gdk_hints)
        self.set_geometry_hints(self.drawing_area, geom, gdk_hints)

    def queue_draw_area(self, x, y, width, height):
        window = self.get_window()
        if not window:
            log.warn("Warning: ignoring draw packet,")
            log.warn(" received for a window which is not realized yet or gone already")
            return
        rect = Gdk.Rectangle()
        rect.x = x
        rect.y = y
        rect.width = width
        rect.height = height
        self.drawing_area.get_window().invalidate_rect(rect, False)

    def do_draw(self, context):
        paintlog("do_draw(%s)", context)
        Gtk.Window.do_draw(self, context)

    def drawing_area_draw(self, widget, context):
        paintlog("drawing_area_draw(%s, %s)", widget, context)
        backing = self._backing
        if self.get_mapped() and backing:
            self.paint_backing_offset_border(backing, context)
            self.clip_to_backing(backing, context)
            backing.cairo_draw(context)
        self.cairo_paint_border(context, None)
        if not self._client.server_ok():
            self.paint_spinner(context)
