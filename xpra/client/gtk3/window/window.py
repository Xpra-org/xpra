# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.client.gtk3.window.base import HAS_X11_BINDINGS
from xpra.client.gtk3.window.factory import get_window_base_classes
from xpra.gtk.util import event_mask_strs
from xpra.util.objects import typedict
from xpra.os_util import gi_import
from xpra.util.str_fn import bytestostr
from xpra.log import Logger

log = Logger("window")
paintlog = Logger("paint")
metalog = Logger("metadata")
geomlog = Logger("geometry")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GdkPixbuf = gi_import("GdkPixbuf")
GObject = gi_import("GObject")
Gio = gi_import("Gio")

WINDOW_BASES = get_window_base_classes()
WindowBaseClass = type("WindowBaseClass", WINDOW_BASES, {})
log(f"WindowBaseClass: {WINDOW_BASES=}")


def get_all_gsignals() -> dict[str, Any]:
    all_gsignals = {}
    for bc in WINDOW_BASES:
        gsignals = getattr(bc, "__gsignals__", {})
        all_gsignals.update(gsignals)
    log(f"gsignals: {all_gsignals.keys()}")
    return all_gsignals


class ClientWindow(WindowBaseClass):
    """
    GTK3 version of the ClientWindow class
    """
    __gsignals__ = get_all_gsignals()

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        self.menu_helper = None
        for bc in WINDOW_BASES:
            bc.init_window(self, client, metadata, client_props)

    def destroy(self) -> None:  # pylint: disable=method-hidden
        for bc in WINDOW_BASES:
            bc.cleanup(self)
        super().destroy()

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {}
        for bc in WINDOW_BASES:
            info.update(bc.get_info(self))
        return info

    def get_window_event_mask(self) -> Gdk.EventMask:
        mask = 0
        for bc in WINDOW_BASES:
            if hasattr(bc, "get_window_event_mask"):
                mask |= bc.get_window_event_mask(self)
            log("%s.get_window_event_mask()=%s", bc, event_mask_strs(mask))
        log("get_window_event_mask()=%s", event_mask_strs(mask))
        return mask

    def init_widget_events(self, widget) -> None:
        for bc in WINDOW_BASES:
            if hasattr(bc, "init_widget_events"):
                bc.init_widget_events(self, widget)

    def set_icon(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        for bc in WINDOW_BASES:
            if hasattr(bc, "set_icon"):
                bc.set_icon(self, pixbuf)

    def show_xpra_menu(self, *_args) -> None:
        # this is called by the headerbar
        mh = self._client.get_window_menu_helper()
        if mh:
            mh.build()
            mh.popup(0, 0)

    def show_window_menu(self, *_args) -> None:
        if not self.menu_helper:
            from xpra.client.gtk3.window.menu import WindowMenuHelper
            self.menu_helper = WindowMenuHelper(self._client, self)
            self.menu_helper.build()
        self.menu_helper.popup(0, 0)

    def get_backing_class(self) -> type:
        from xpra.client.gtk3.cairo_backing import CairoBacking
        return CairoBacking

    def xget_u32_property(self, target, name: str, default_value=0) -> int:
        if HAS_X11_BINDINGS:
            from xpra.client.gtk3.window.base import GTKClientWindowBase
            return GTKClientWindowBase.xget_u32_property(self, target, name, default_value)
        # pure Gdk lookup:
        try:
            name_atom = Gdk.Atom.intern(name, False)
            type_atom = Gdk.Atom.intern("CARDINAL", False)
            prop = Gdk.property_get(target, name_atom, type_atom, 0, 9999, False)
            if not prop or len(prop) != 3 or len(prop[2]) != 1:
                return default_value
            metalog("xget_u32_property(%s, %s, %s)=%s", target, name, default_value, prop[2][0])
            return prop[2][0]
        except Exception as e:
            metalog.error("xget_u32_property error on %s / %s: %s", target, name, e)
            return default_value

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
        w, h = self.get_size()
        backing.cairo_draw(context, w, h)
        return True

    def get_map_client_properties(self) -> dict[str, Any]:
        props = {}
        for bc in WINDOW_BASES:
            props.update(bc.get_map_client_properties(self))
        return props

    def get_configure_client_properties(self) -> dict[str, Any]:
        props = {}
        for bc in WINDOW_BASES:
            props.update(bc.get_configure_client_properties(self))
        return props


GObject.type_register(ClientWindow)
