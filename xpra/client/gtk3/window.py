# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.gtk3.window_base import GTKClientWindowBase, HAS_X11_BINDINGS
from xpra.gtk.widget import scaled_image
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.scripts.config import FALSE_OPTIONS
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.os_util import gi_import
from xpra.util.str_fn import bytestostr
from xpra.log import Logger

paintlog = Logger("paint")
metalog = Logger("metadata")
geomlog = Logger("geometry")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GdkPixbuf = gi_import("GdkPixbuf")
GObject = gi_import("GObject")
Gio = gi_import("Gio")

WINDOW_ICON = envbool("XPRA_WINDOW_ICON", True)
WINDOW_XPRA_MENU = envbool("XPRA_WINDOW_XPRA_MENU", True)
WINDOW_MENU = envbool("XPRA_WINDOW_MENU", True)


class ClientWindow(GTKClientWindowBase):
    """
    GTK3 version of the ClientWindow class
    """

    def init_window(self, metadata: typedict) -> None:
        super().init_window(metadata)
        self.menu_helper = None
        self.header_bar_image = None
        if self.can_use_header_bar(metadata):
            self.add_header_bar()

    def _icon_size(self) -> int:
        tb = self.get_titlebar()
        try:
            h = tb.get_preferred_size()[-1] - 8
        except Exception:
            h = 24
        return min(128, max(h, 24))

    def set_icon(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        super().set_icon(pixbuf)
        hbi = self.header_bar_image
        if hbi and WINDOW_ICON:
            h = self._icon_size()
            pixbuf = pixbuf.scale_simple(h, h, GdkPixbuf.InterpType.HYPER)
            hbi.set_from_pixbuf(pixbuf)

    def can_use_header_bar(self, metadata: typedict) -> bool:
        if self.is_OR() or not self.get_decorated():
            return False
        hbl = (self.headerbar or "").lower().strip()
        if hbl in FALSE_OPTIONS:
            return False
        if hbl == "force":
            return True
        # we can't enable it if there are size-constraints:
        sc = metadata.dictget("size-constraints")
        if sc is None:
            return True
        tsc = typedict(sc)
        maxs = tsc.intpair("maximum-size")
        if maxs:
            return False
        mins = tsc.intpair("minimum-size")
        if mins and mins != (0, 0):
            return False
        if tsc.intpair("increment", (0, 0)) != (0, 0):
            return False
        return True

    def add_header_bar(self) -> None:
        metalog("add_header_bar()")
        hb = Gtk.HeaderBar()
        hb.set_has_subtitle(False)
        hb.set_show_close_button(True)
        hb.props.title = self.get_title()
        if WINDOW_MENU:
            # the icon 'open-menu-symbolic' will be replaced with the window icon
            # when we receive it
            icon = Gio.ThemedIcon(name="preferences-system-windows")
            self.header_bar_image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
            button = Gtk.Button()
            button.add(self.header_bar_image)
            button.connect("clicked", self.show_window_menu)
            hb.pack_start(button)
        elif WINDOW_ICON:
            # just the icon, no menu:
            pixbuf = get_icon_pixbuf("transparent.png")
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

    def show_xpra_menu(self, *_args) -> None:
        mh = self._client.get_menu_helper()
        if mh:
            mh.build()
            mh.popup(0, 0)

    def show_window_menu(self, *_args) -> None:
        if not self.menu_helper:
            from xpra.client.gtk3.window_menu import WindowMenuHelper
            self.menu_helper = WindowMenuHelper(self._client, self)
            self.menu_helper.build()
        self.menu_helper.popup(0, 0)

    def get_backing_class(self) -> type:
        from xpra.client.gtk3.cairo_backing import CairoBacking
        return CairoBacking

    def xget_u32_property(self, target, name: str):
        if HAS_X11_BINDINGS:
            return GTKClientWindowBase.xget_u32_property(self, target, name)
        # pure Gdk lookup:
        try:
            name_atom = Gdk.Atom.intern(name, False)
            type_atom = Gdk.Atom.intern("CARDINAL", False)
            prop = Gdk.property_get(target, name_atom, type_atom, 0, 9999, False)
            if not prop or len(prop) != 3 or len(prop[2]) != 1:
                return None
            metalog("xget_u32_property(%s, %s)=%s", target, name, prop[2][0])
            return prop[2][0]
        except Exception as e:
            metalog.error("xget_u32_property error on %s / %s: %s", target, name, e)

    def get_drawing_area_geometry(self) -> tuple[int, int, int, int]:
        gdkwindow = self.drawing_area.get_window()
        if gdkwindow:
            x, y = gdkwindow.get_origin()[1:]
        else:
            x, y = self.get_position()
        w, h = self.get_size()
        return x, y, w, h

    def apply_geometry_hints(self, hints: typedict) -> None:
        """ we convert the hints as a dict into a gdk.Geometry + gdk.WindowHints """
        wh = Gdk.WindowHints
        name_to_hint = {
            "max_width": wh.MAX_SIZE,
            "max_height": wh.MAX_SIZE,
            "min_width": wh.MIN_SIZE,
            "min_height": wh.MIN_SIZE,
            "base_width": wh.BASE_SIZE,
            "base_height": wh.BASE_SIZE,
            "width_inc": wh.RESIZE_INC,
            "height_inc": wh.RESIZE_INC,
            "min_aspect_ratio": wh.ASPECT,
            "max_aspect_ratio": wh.ASPECT,
        }
        # these fields can be copied directly to the gdk.Geometry as ints:
        INT_FIELDS: list[str] = [
            "min_width", "min_height",
            "max_width", "max_height",
            "base_width", "base_height",
            "width_inc", "height_inc",
        ]
        ASPECT_FIELDS: dict[str, str] = {
            "min_aspect_ratio": "min_aspect",
            "max_aspect_ratio": "max_aspect",
        }
        thints = typedict(hints)
        if self.drawing_area:
            # apply min size to the drawing_area:
            # (for CSD mode, ie: headerbar)
            minw = thints.intget("min_width", 0)
            minh = thints.intget("min_height", 0)
            self.drawing_area.set_size_request(minw, minh)

        geom = Gdk.Geometry()
        mask = 0
        for k, v in hints.items():
            k = bytestostr(k)
            if k in INT_FIELDS:
                setattr(geom, k, v)
                mask |= int(name_to_hint.get(k, 0))
            elif k in ASPECT_FIELDS:
                field = ASPECT_FIELDS[k]
                setattr(geom, field, float(v))
                mask |= int(name_to_hint.get(k, 0))
        gdk_hints = Gdk.WindowHints(mask)
        geomlog("apply_geometry_hints(%s) geometry=%s, hints=%s", hints, geom, gdk_hints)
        self.set_geometry_hints(self.drawing_area, geom, gdk_hints)

    def can_maximize(self) -> bool:
        hints = self.geometry_hints
        if not hints:
            return True
        maxw = hints.intget("max_width", 32768)
        maxh = hints.intget("max_height", 32768)
        if maxw > 32000 and maxh > 32000:
            return True
        geom = self.get_drawing_area_geometry()
        dw, dh = geom[2], geom[3]
        return dw < maxw and dh < maxh

    def draw_widget(self, widget, context) -> bool:
        paintlog("draw_widget(%s, %s)", widget, context)
        if not self.get_mapped():
            return False
        backing = self._backing
        if not backing:
            return False
        context.save()
        self.paint_backing_offset_border(backing, context)
        self.clip_to_backing(backing, context)
        backing.cairo_draw(context)
        context.restore()
        self.cairo_paint_border(context, None)
        if not self._client.server_ok():
            self.paint_spinner(context)
        return True


GObject.type_register(ClientWindow)
