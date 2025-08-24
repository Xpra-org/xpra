# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Callable

from xpra.util.objects import typedict
from xpra.server.subsystem.stub import StubServerMixin
from xpra.util.env import SilenceWarningsContext
from xpra.common import XPRA_APP_ID, noop
from xpra.os_util import POSIX, OSX, gi_import
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("tray")


def get_icon_image(icon_name: str):
    from xpra.platform.gui import get_icon_size
    size = get_icon_size()
    from xpra.gtk.widget import scaled_image
    with log.trap_error(f"Error loading image from icon {icon_name!r} with size {size}"):
        from xpra.gtk.pixbuf import get_icon_pixbuf
        pixbuf = get_icon_pixbuf(icon_name)
        log("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
        if not pixbuf:
            return None
        return scaled_image(pixbuf, size)


def traymenuitem(title: str, icon_name="", tooltip="", cb: Callable = noop):  # -> Gtk.ImageMenuItem:
    """ Utility method for easily creating an ImageMenuItem """
    # pylint: disable=import-outside-toplevel
    from xpra.gtk.widget import menuitem
    image = None
    if icon_name:
        image = get_icon_image(icon_name)
    return menuitem(title, image, tooltip, cb)


class TrayMenu(StubServerMixin):

    def __init__(self):
        StubServerMixin.__init__(self)
        self.tray_menu = None
        self.tray_menu_shown = False
        self.tray_widget = None
        self.tray = False
        self.tray_icon = None

    def init(self, opts) -> None:
        self.tray = opts.tray
        self.tray_icon = opts.tray_icon

    def setup(self) -> None:
        if self.tray:
            self.setup_tray()

    def cleanup(self) -> None:
        self.cleanup_tray()

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        if not self.tray_icon:
            self.set_tray_icon("server-connected")

    def last_client_exited(self) -> None:
        # revert to default icon:
        if not self.tray_icon:
            self.set_tray_icon("server-notconnected")

    def cleanup_tray(self) -> None:
        tw = self.tray_widget
        log("cleanup_tray() tray_widget=%s", tw)
        if tw:
            self.tray_widget = None
            tw.cleanup()

    def setup_tray(self) -> None:
        if OSX:
            return
        Gdk = gi_import("Gdk")
        display = Gdk.Display.get_default()
        if not display:
            # usually this is wayland shadow server:
            log("no access to the display, cannot setup tray")
            return
        try:
            self.tray_menu = self.make_tray_menu()
            self.tray_widget = self.make_tray_widget()
            self.set_tray_icon(self.tray_icon or "server-notconnected")
        except ImportError as e:
            log("setup_tray()", exc_info=True)
            log.warn("Warning: failed to load systemtray:")
            log.warn(" %s", e)
        except Exception as e:
            log("error setting up %s", self.tray_widget, exc_info=True)
            log.error("Error setting up system tray:")
            log.estr(e)

    def make_tray_menu(self):
        Gtk = gi_import("Gtk")
        tray_menu = Gtk.Menu()
        with SilenceWarningsContext(DeprecationWarning):
            label = "Xpra Shadow Server"
            display = os.environ.get("DISPLAY", "")
            if POSIX and display:
                label = f"Xpra {display} Shadow Server"
            tray_menu.set_title(label)
        title_item = Gtk.MenuItem()
        title_item.set_label(label)
        title_item.set_sensitive(False)
        title_item.show()
        tray_menu.append(title_item)

        def show_about(*_args):
            from xpra.gtk.dialogs.about import about  # pylint: disable=import-outside-toplevel
            about()

        tray_menu.append(traymenuitem("About Xpra", "information.png", cb=show_about))
        self.add_tray_menu_items(tray_menu)
        tray_menu.append(traymenuitem("Exit", "quit.png", cb=self.tray_exit_callback))
        tray_menu.append(traymenuitem("Close Menu", "close.png", cb=self.close_tray_menu))
        # maybe add: session info, clipboard, sharing, etc
        # control: disconnect clients
        tray_menu.connect("deactivate", self.tray_menu_deactivated)
        return tray_menu

    def add_tray_menu_items(self, tray_menu):
        """ subclasses will add their menu items here """

    def make_tray_widget(self):
        # pylint: disable=import-outside-toplevel
        from xpra.platform.systray import get_backends
        classes = get_backends()
        try:
            from xpra.gtk.statusicon_tray import GTKStatusIconTray
            classes.append(GTKStatusIconTray)
        except ImportError:
            log("no GTKStatusIconTray", exc_info=True)
        log("tray classes: %s", classes)
        if not classes:
            log.error("Error: no system tray implementation available")
            return None
        errs = []
        for c in classes:
            try:
                w = c(self, XPRA_APP_ID, self.tray_menu, "Xpra Shadow Server",
                      icon_filename="server-notconnected.png",
                      click_cb=self.tray_click_callback, exit_cb=self.tray_exit_callback)
                if w:
                    log(f"server system tray widget using {c}(..)={w}")
                    return w
                log(f"{c}(..) returned None")
                errs.append((c, "returned None"))
            except Exception as e:
                log(f"{c}(..)", exc_info=True)
                errs.append((c, e))
        log.error("Error: all system tray implementations have failed")
        for c, err in errs:
            log.error(" %s: %s", c, err)
        return None

    def set_tray_icon(self, filename: str) -> None:
        if not self.tray_widget:
            return
        try:
            self.tray_widget.set_icon(filename)
        except Exception as e:
            log.warn("Warning: failed to set tray icon to %s", filename)
            log.warn(" %s", e)

    def tray_menu_deactivated(self, *_args) -> None:
        self.tray_menu_shown = False

    def tray_click_callback(self, button: int, pressed: int, time=0) -> None:
        log("tray_click_callback(%s, %s, %i) tray menu=%s, shown=%s",
            button, pressed, time, self.tray_menu, self.tray_menu_shown)
        if pressed:
            self.close_tray_menu()
        else:
            # status icon can give us a position function:
            # except this doesn't work and nothing happens!
            # position_menu = self.tray_widget.tray_widget.position_menu
            # pos = position_menu(self.tray_menu, x, y, self.tray_widget.tray_widget)
            if POSIX and not OSX:
                self.tray_menu.popup_at_pointer()
            else:
                with SilenceWarningsContext(DeprecationWarning):
                    self.tray_menu.popup(None, None, None, None, button, time)
            self.tray_menu_shown = True

    def tray_exit_callback(self, *_args) -> None:
        self.close_tray_menu()
        GLib.idle_add(self.clean_quit, False)

    def close_tray_menu(self, *_args) -> None:
        if self.tray_menu_shown:
            self.tray_menu.popdown()
            self.tray_menu_shown = False
