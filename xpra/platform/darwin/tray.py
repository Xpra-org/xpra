# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from xpra.os_util import gi_import
from xpra.client.gui.tray_base import TrayBase
from xpra.gtk.pixbuf import get_pixbuf_from_data
from xpra.platform.darwin.menu import getOSXMenuHelper
from xpra.platform.darwin import set_exit_cb
from xpra.platform.gui import ready as gui_ready
from xpra.log import Logger

GdkPixbuf = gi_import("GdkPixbuf")

log = Logger("tray", "osx")

# constants for attention_request:
CRITICAL_REQUEST = 0
INFO_REQUEST = 10


class OSXTray(TrayBase):

    def __init__(self, *args):
        super().__init__(*args)
        from xpra.platform.darwin import get_OSXApplication
        self.macapp = get_OSXApplication()
        assert self.macapp, "cannot use OSX Tray without the native gtkosx_application bindings"
        self.last_attention_request_id = -1

        self.set_global_menu()
        self.set_dock_menu()
        self.set_dock_icon()
        set_exit_cb(self.quit)

    def get_geometry(self):
        return None

    def show(self) -> None:
        """
        This cannot be implemented on MacOS,
        as the dock icon is always shown
        """

    def hide(self) -> None:
        """ Unfortunately, the dock icon cannot be hidden """

    def quit(self, *args) -> bool:
        log("quit(%s) exit_cb=%s", args, self.exit_cb)
        if self.exit_cb:
            self.exit_cb()
            return True  # we've handled the quit request ourselves - I hope..
        return False

    def ready(self) -> None:
        gui_ready()

    def set_tooltip(self, tooltip: str = "") -> None:
        # label cannot be set on the dock icon?
        pass

    def set_blinking(self, on: bool) -> None:
        if on:
            if self.last_attention_request_id < 0:
                self.last_attention_request_id = self.macapp.attention_request(INFO_REQUEST)
        else:
            if self.last_attention_request_id >= 0:
                self.macapp.cancel_attention_request(self.last_attention_request_id)
                self.last_attention_request_id = -1

    def set_icon_from_data(self, pixels, has_alpha: bool, w: int, h: int, rowstride: int, options=None) -> None:
        tray_icon = get_pixbuf_from_data(pixels, has_alpha, w, h, rowstride)
        self.macapp.set_dock_icon_pixbuf(tray_icon)
        self.icon_timestamp = monotonic()

    def do_set_icon_from_file(self, filename: str) -> None:
        if not self.macapp:
            return
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(filename=filename)
        self.macapp.set_dock_icon_pixbuf(pixbuf)
        self.icon_timestamp = monotonic()

    def set_global_menu(self) -> None:
        mh = getOSXMenuHelper()
        if mh.build() != self.menu:
            log.error("the menu (%s) is not from the menu helper!", self.menu)
            return
        # redundant: the menu bar has already been set during gui init
        # using the basic the simple menu from build_menu_bar()
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*invalid cast from 'GtkMenuBar'")
            self.macapp.set_menu_bar(self.menu)
        mh.add_full_menu()
        log("OSXTray.set_global_menu() done")

    def set_dock_menu(self) -> None:
        # dock menu
        log("OSXTray.set_dock_menu()")
        Gtk = gi_import("Gtk")
        self.dock_menu = Gtk.Menu()
        self.disconnect_dock_item = Gtk.MenuItem(label="Disconnect")
        self.disconnect_dock_item.connect("activate", self.quit)
        self.dock_menu.add(self.disconnect_dock_item)
        self.dock_menu.show_all()
        self.macapp.set_dock_menu(self.dock_menu)
        log("OSXTray.set_dock_menu() done")

    def set_dock_icon(self) -> None:
        filename = self.get_icon_filename()
        if not filename:
            log.warn("Warning: cannot set dock icon, file not found!")
            return
        log("OSXTray.set_dock_icon() loading icon from %s", filename)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(filename=filename)
        self.macapp.set_dock_icon_pixbuf(pixbuf)
