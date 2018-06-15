# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from gi.repository import GObject               #@UnresolvedImport @UnusedImport
from gi.repository import Gtk                   #@UnresolvedImport @UnusedImport
from gi.repository import Gdk                   #@UnresolvedImport @UnusedImport
from gi.repository import GdkPixbuf             #@UnresolvedImport @UnusedImport

from xpra.client.gtk3.cairo_backing import CairoBacking
from xpra.client.gtk_base.gtk_client_window_base import GTKClientWindowBase, HAS_X11_BINDINGS
from xpra.gtk_common.gtk_util import WINDOW_NAME_TO_HINT, WINDOW_EVENT_MASK, BUTTON_MASK
from xpra.os_util import bytestostr, WIN32
from xpra.log import Logger
log = Logger("gtk", "window")
paintlog = Logger("paint")
metalog = Logger("metadata")


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
class ClientWindow(GTKClientWindowBase):

    __gsignals__ = GTKClientWindowBase.__common_gsignals__


    WINDOW_EVENT_MASK   = WINDOW_EVENT_MASK
    BUTTON_MASK         = BUTTON_MASK
    OR_TYPE_HINTS       = GTK3_OR_TYPE_HINTS
    NAME_TO_HINT        = WINDOW_NAME_TO_HINT

    WINDOW_STATE_FULLSCREEN = Gdk.WindowState.FULLSCREEN
    WINDOW_STATE_MAXIMIZED  = Gdk.WindowState.MAXIMIZED
    WINDOW_STATE_ICONIFIED  = Gdk.WindowState.ICONIFIED
    WINDOW_STATE_ABOVE      = Gdk.WindowState.ABOVE
    WINDOW_STATE_BELOW      = Gdk.WindowState.BELOW
    WINDOW_STATE_STICKY     = Gdk.WindowState.STICKY


    def do_init_window(self, window_type):
        Gtk.Window.__init__(self, type = window_type)
        # tell KDE/oxygen not to intercept clicks
        # see: https://bugs.kde.org/show_bug.cgi?id=274485
        # does not work with gtk3? what the??
        # they moved it gobject, then removed it, unbelievable:
        # https://bugzilla.gnome.org/show_bug.cgi?id=641944
        #self.set_data("_kde_no_window_grab", 1)
        def motion(_w, event):
            self.do_motion_notify_event(event)
            return True
        self.connect("motion-notify-event", motion)
        def press(_w, event):
            self.do_button_press_event(event)
            return True
        self.connect("button-press-event", press)
        def release(_w, event):
            self.do_button_release_event(event)
            return True
        self.connect("button-release-event", release)
        def scroll(_w, event):
            self.do_scroll_event(event)
            return True
        self.connect("scroll-event", scroll)

    def get_backing_class(self):
        return CairoBacking

    def enable_alpha(self):
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        #we can't do alpha on win32 with plain GTK,
        #(though we handle it in the opengl backend)
        if WIN32:
            l = log
        else:
            l = log.error
        if visual is None or not screen.is_composited():
            l("Error: cannot handle window transparency")
            if visual is None:
                l(" no RGBA visual")
            else:
                assert not screen.is_composited()
                l(" screen is not composited")
            return False
        log("enable_alpha() using rgba visual %s for wid %s", visual, self._id)
        self.set_visual(visual)
        return True


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

    def get_window_geometry(self):
        gdkwindow = self.get_window()
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
        self.set_geometry_hints(None, geom, gdk_hints)


    def queue_draw(self, x, y, width, height):
        self.queue_draw_area(x, y, width, height)

    def do_draw(self, context):
        paintlog("do_draw(%s)", context)
        backing = self._backing
        if self.get_mapped() and backing:
            self.paint_backing_offset_border(backing, context)
            self.clip_to_backing(backing, context)
            backing.cairo_draw(context)
        self.cairo_paint_border(context, None)


GObject.type_register(ClientWindow)
