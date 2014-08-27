# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from gi.repository import GObject               #@UnresolvedImport @UnusedImport
from gi.repository import Gtk                   #@UnresolvedImport @UnusedImport
from gi.repository import Gdk                   #@UnresolvedImport @UnusedImport
from gi.repository import GdkPixbuf             #@UnresolvedImport @UnusedImport

from xpra.client.gtk_base.cairo_backing import CairoBacking
from xpra.client.gtk_base.gtk_client_window_base import GTKClientWindowBase, HAS_X11_BINDINGS
from xpra.log import Logger
log = Logger("gtk", "window")
paintlog = Logger("paint")


GTK3_WINDOW_EVENT_MASK = Gdk.EventMask.STRUCTURE_MASK | Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.KEY_RELEASE_MASK \
            | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK \
            | Gdk.EventMask.PROPERTY_CHANGE_MASK | Gdk.EventMask.SCROLL_MASK

GTK3_BUTTON_MASK = {Gdk.ModifierType.BUTTON1_MASK : 1,
                    Gdk.ModifierType.BUTTON2_MASK : 2,
                    Gdk.ModifierType.BUTTON3_MASK : 3,
                    Gdk.ModifierType.BUTTON4_MASK : 4,
                    Gdk.ModifierType.BUTTON5_MASK : 5}

GTK3_SCROLL_MAP = {
                   Gdk.ScrollDirection.UP   : 4,
                   Gdk.ScrollDirection.DOWN : 5,
                   Gdk.ScrollDirection.LEFT : 6,
                   Gdk.ScrollDirection.RIGHT: 7,
                   #Gdk.ScrollDirection.SMOOTH would require special handling
                   # calling gdk_event_get_scroll_deltas()
                  }

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


GTK3_NAME_TO_HINT = {
                "NORMAL"        : Gdk.WindowTypeHint.NORMAL,
                "DIALOG"        : Gdk.WindowTypeHint.DIALOG,
                "MENU"          : Gdk.WindowTypeHint.MENU,
                "TOOLBAR"       : Gdk.WindowTypeHint.TOOLBAR,
                "SPLASH"        : Gdk.WindowTypeHint.SPLASHSCREEN,
                "UTILITY"       : Gdk.WindowTypeHint.UTILITY,
                "DOCK"          : Gdk.WindowTypeHint.DOCK,
                "DESKTOP"       : Gdk.WindowTypeHint.DESKTOP,
                "DROPDOWN_MENU" : Gdk.WindowTypeHint.DROPDOWN_MENU,
                "POPUP_MENU"    : Gdk.WindowTypeHint.POPUP_MENU,
                "TOOLTIP"       : Gdk.WindowTypeHint.TOOLTIP,
                "NOTIFICATION"  : Gdk.WindowTypeHint.NOTIFICATION,
                "COMBO"         : Gdk.WindowTypeHint.COMBO,
                "DND"           : Gdk.WindowTypeHint.DND
                }


"""
GTK3 version of the ClientWindow class
"""
class ClientWindow(GTKClientWindowBase):

    #WINDOW_POPUP        = Gtk.WindowType.POPUP
    #WINDOW_TOPLEVEL     = Gtk.WindowType.TOPLEVEL
    WINDOW_EVENT_MASK   = GTK3_WINDOW_EVENT_MASK
    BUTTON_MASK         = GTK3_BUTTON_MASK
    SCROLL_MAP          = GTK3_SCROLL_MAP
    OR_TYPE_HINTS       = GTK3_OR_TYPE_HINTS
    NAME_TO_HINT        = GTK3_NAME_TO_HINT

    WINDOW_STATE_FULLSCREEN = Gdk.WindowState.FULLSCREEN
    WINDOW_STATE_MAXIMIZED  = Gdk.WindowState.MAXIMIZED
    WINDOW_STATE_ICONIFIED  = Gdk.WindowState.ICONIFIED


    def init_window(self, metadata):
        #TODO: no idea how to do the window-type with gtk3
        #maybe not even be possible..
        if self._is_popup(metadata):
            window_type = Gtk.WindowType.POPUP
        else:
            window_type = Gtk.WindowType.TOPLEVEL
        Gtk.Window.__init__(self,
                            type = window_type,
                            decorated = not self._override_redirect,
                            app_paintable = True)
        GTKClientWindowBase.init_window(self, metadata)
        # tell KDE/oxygen not to intercept clicks
        # see: https://bugs.kde.org/show_bug.cgi?id=274485
        # does not work with gtk3? what the??
        #self.set_data(strtobytes("_kde_no_window_grab"), 1)
        def motion(w, event):
            self.do_motion_notify_event(event)
        self.connect("motion-notify-event", motion)
        def press(w, event):
            self.do_button_press_event(event)
        self.connect("button-press-event", press)
        def release(w, event):
            self.do_button_release_event(event)
        self.connect("button-release-event", release)
        def scroll(w, event):
            self.do_scroll_event(event)
        self.connect("scroll-event", scroll)

    def get_backing_class(self):
        return CairoBacking

    def xget_u32_property(self, target, name):
        try:
            if not HAS_X11_BINDINGS:
                name_atom = Gdk.Atom.intern(name, False)
                type_atom = Gdk.Atom.intern("CARDINAL", False)
                prop = Gdk.property_get(target, name_atom, type_atom, 0, 9999, False)
                if not prop or len(prop)!=3 or len(prop[2])!=1:
                    return  None
                log("xget_u32_property(%s, %s)=%s", target, name, prop[2][0])
                return prop[2][0]
        except Exception as e:
            log.error("xget_u32_property error on %s / %s: %s", target, name, e)
        return GTKClientWindowBase.xget_u32_property(self, target, name)

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
            if k in INT_FIELDS:
                setattr(geom, k, int(v))
                mask |= int(name_to_hint.get(k, 0))
            elif k in ASPECT_FIELDS:
                field = ASPECT_FIELDS.get(k)
                setattr(geom, field, float(v))
                mask |= int(name_to_hint.get(k, 0))
        hints = Gdk.WindowHints(mask)
        self.set_geometry_hints(None, geom, hints)


    def queue_draw(self, x, y, width, height):
        self.queue_draw_area(x, y, width, height)

    def do_draw(self, context):
        paintlog("do_draw(%s)", context)
        if self.get_mapped() and self._backing:
            self._backing.cairo_draw(context)


GObject.type_register(ClientWindow)
