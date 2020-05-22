# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import Gdk, Gtk, Gio, GdkPixbuf

from xpra.client.gtk_base.gtk_client_window_base import GTKClientWindowBase, HAS_X11_BINDINGS
from xpra.client.gtk3.window_menu import WindowMenuHelper
from xpra.gtk_common.gtk_util import WINDOW_NAME_TO_HINT, scaled_image
from xpra.util import envbool
from xpra.os_util import bytestostr, is_gnome, OSX
from xpra.log import Logger

paintlog = Logger("paint")
metalog = Logger("metadata")
geomlog = Logger("geometry")

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


CUSTOM_TITLE_BAR = envbool("XPRA_CUSTOM_TITLE_BAR", True)
WINDOW_ICON = CUSTOM_TITLE_BAR and envbool("XPRA_WINDOW_ICON", not OSX)
WINDOW_XPRA_MENU = CUSTOM_TITLE_BAR and envbool("XPRA_WINDOW_XPRA_MENU", is_gnome())
WINDOW_MENU = CUSTOM_TITLE_BAR and envbool("XPRA_WINDOW_MENU", not OSX)


"""
GTK3 version of the ClientWindow class
"""
class GTK3ClientWindow(GTKClientWindowBase):

    OR_TYPE_HINTS       = GTK3_OR_TYPE_HINTS
    NAME_TO_HINT        = WINDOW_NAME_TO_HINT

    def init_window(self, metadata):
        super().init_window(metadata)
        self.header_bar_image = None
        if CUSTOM_TITLE_BAR and self.get_decorated() and not self.is_OR():
            self.add_header_bar()

    def _icon_size(self):
        tb = self.get_titlebar()
        try:
            h = tb.get_preferred_size()[-1]-8
        except Exception:
            h = 24
        return min(128, max(h, 24))

    def set_icon(self, pixbuf):
        super().set_icon(pixbuf)
        hbi = self.header_bar_image
        if hbi and WINDOW_ICON:
            h = self._icon_size()
            pixbuf = pixbuf.scale_simple(h, h, GdkPixbuf.InterpType.HYPER)
            hbi.set_from_pixbuf(pixbuf)

    def add_header_bar(self):
        self.menu_helper = WindowMenuHelper(self._client, self)
        hb = Gtk.HeaderBar()
        hb.set_has_subtitle(False)
        hb.set_show_close_button(True)
        hb.props.title = self.get_title()
        if WINDOW_MENU:
            #the icon 'open-menu-symbolic' will be replaced with the window icon
            #when we receive it
            icon = Gio.ThemedIcon(name="preferences-system-windows")
            self.header_bar_image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
            button = Gtk.Button()
            button.add(self.header_bar_image)
            button.connect("clicked", self.show_window_menu)
            hb.pack_start(button)
        elif WINDOW_ICON:
            #just the icon, no menu:
            pixbuf = self._client.get_pixbuf("transparent.png")
            self.header_bar_image = scaled_image(pixbuf, self._icon_size())
            hb.pack_start(self.header_bar_image)
        if WINDOW_XPRA_MENU:
            icon = Gio.ThemedIcon(name="open-menu-symbolic")
            image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
            button = Gtk.Button()
            button.add(image)
            button.connect("clicked", self.show_xpra_menu)
            hb.pack_end(button)
        self.set_titlebar(hb)

    def show_xpra_menu(self, *args):
        mh = getattr(self._client, "menu_helper", None)
        if not mh:
            from xpra.client.gtk3.tray_menu import GTK3TrayMenu
            mh = GTK3TrayMenu(self._client)
        mh.popup(0, 0)

    def show_window_menu(self, *args):
        self.menu_helper.build()
        self.menu_helper.popup(0, 0)

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

    def get_drawing_area_geometry(self):
        gdkwindow = self.drawing_area.get_window()
        if gdkwindow:
            x, y = gdkwindow.get_origin()[1:]
        else:
            x, y = self.get_position()
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
        geomlog("apply_geometry_hints(%s) geometry=%s, hints=%s", hints, geom, gdk_hints)
        self.set_geometry_hints(self.drawing_area, geom, gdk_hints)

    def can_maximize(self):
        hints = self.geometry_hints
        if not hints:
            return True
        maxw = hints.intget(b"max_width", 32768)
        maxh = hints.intget(b"max_height", 32768)
        if maxw>32000 and maxh>32000:
            return True
        geom = self.get_drawing_area_geometry()
        dw, dh = geom[2], geom[3]
        return dw<maxw and dh<maxh 

    def draw_widget(self, widget, context):
        paintlog("draw_widget(%s, %s)", widget, context)
        if not self.get_mapped():
            return False
        backing = self._backing
        if not backing:
            return False
        self.paint_backing_offset_border(backing, context)
        self.clip_to_backing(backing, context)
        backing.cairo_draw(context)
        self.cairo_paint_border(context, None)
        if not self._client.server_ok():
            self.paint_spinner(context)
        return True
