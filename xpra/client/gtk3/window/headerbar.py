# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.gtk.widget import scaled_image
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.client.gtk3.window.stub_window import GtkStubWindow
from xpra.util.parsing import FALSE_OPTIONS
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.common import noop
from xpra.os_util import gi_import, OSX
from xpra.log import Logger

log = Logger("window", "metadata")

Gtk = gi_import("Gtk")
GdkPixbuf = gi_import("GdkPixbuf")
Gio = gi_import("Gio")

WINDOW_ICON = envbool("XPRA_WINDOW_ICON", True)
WINDOW_XPRA_MENU = envbool("XPRA_WINDOW_XPRA_MENU", True)
WINDOW_MENU = envbool("XPRA_WINDOW_MENU", True)


class HeaderBarWindow(GtkStubWindow):

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        self.header_bar_image: Gtk.Image | None = None
        if self.can_use_header_bar(metadata):
            self.add_header_bar()

    def can_use_header_bar(self, metadata: typedict) -> bool:
        if self.is_OR() or not self.get_decorated() or OSX:
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
        log("add_header_bar()")
        hb = Gtk.HeaderBar()
        hb.set_has_subtitle(False)
        hb.set_show_close_button(True)
        hb.props.title = self.get_title()
        if WINDOW_MENU:
            # defined in window:
            show_window_menu = getattr(self, "show_window_menu", noop)
            # the icon 'open-menu-symbolic' will be replaced with the window icon
            # when we receive it
            icon = Gio.ThemedIcon(name="preferences-system-windows")
            self.header_bar_image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
            button = Gtk.Button()
            button.add(self.header_bar_image)
            button.connect("clicked", show_window_menu)
            hb.pack_start(button)
        elif WINDOW_ICON:
            # just the icon, no menu:
            pixbuf = get_icon_pixbuf("transparent.png")
            self.header_bar_image = scaled_image(pixbuf, self._icon_size())
            hb.pack_start(self.header_bar_image)
        show_xpra_menu = getattr(self, "show_xpra_menu", noop)
        if WINDOW_XPRA_MENU and show_xpra_menu != noop:
            # defined in window:
            icon = Gio.ThemedIcon(name="open-menu-symbolic")
            image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
            button = Gtk.Button()
            button.add(image)
            button.connect("clicked", show_xpra_menu)
            hb.pack_end(button)
        self.set_titlebar(hb)

    def _icon_size(self) -> int:
        tb = self.get_titlebar()
        try:
            h = tb.get_preferred_size()[-1] - 8
        except Exception:
            h = 24
        return min(128, max(h, 24))

    def set_icon(self, pixbuf: GdkPixbuf.Pixbuf) -> None:
        hbi = self.header_bar_image
        if hbi and WINDOW_ICON:
            h = self._icon_size()
            pixbuf = pixbuf.scale_simple(h, h, GdkPixbuf.InterpType.HYPER)
            hbi.set_from_pixbuf(pixbuf)
