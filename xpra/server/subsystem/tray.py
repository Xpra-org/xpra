# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Callable

from xpra.server import features
from xpra.server.subsystem.stub import StubSubsystem
from xpra.util.env import SilenceWarningsContext
from xpra.common import noop
from xpra.constants import XPRA_APP_ID
from xpra.os_util import POSIX, OSX, gi_import, WIN32
from xpra.util.i18n import _
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


class TrayMenu(StubSubsystem):
    """
    This server module adds a system tray menu,
    typically used with shadow servers to be able to exit the server.
    """
    PREFIX = "tray"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.menu = None
        self.menu_shown = False
        self.widget = None
        self.enabled = False
        self.icon = None

    def init(self, opts) -> None:
        self.enabled = opts.tray
        self.icon = opts.tray_icon

    def setup(self) -> None:
        if self.enabled:
            self.setup_tray()
            self.server.connect("last-client-exited", self.tray_not_connected)

    def tray_not_connected(self, *args) -> None:
        log("tray_not_connected%s", args)
        # revert to default icon:
        if not self.icon:
            self.set_tray_icon("server-notconnected")

    def cleanup(self) -> None:
        self.cleanup_tray()

    def add_new_client(self, *_args) -> None:
        if not self.icon:
            self.set_tray_icon("server-connected")

    def cleanup_tray(self) -> None:
        tw = self.widget
        log("cleanup_tray() tray_widget=%s", tw)
        if tw:
            self.widget = None
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
            self.menu = self.make_tray_menu()
            self.widget = self.make_tray_widget()
            self.set_tray_icon(self.icon or "server-notconnected")
        except ImportError as e:
            log("setup_tray()", exc_info=True)
            log.warn("Warning: failed to load systemtray:")
            log.warn(" %s", e)
        except Exception as e:
            log("error setting up %s", self.widget, exc_info=True)
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

        tray_menu.append(traymenuitem(_("About Xpra"), "information.png", cb=show_about))
        self.add_tray_menu_items(tray_menu)
        tray_menu.append(traymenuitem(_("Exit"), "quit.png", cb=self.tray_exit_callback))
        tray_menu.append(traymenuitem(_("Close Menu"), "close.png", cb=self.close_tray_menu))
        if WIN32 and not self.parsec_vdd_installed():
            # parsec-vdd provides virtual monitor support on win32,
            # if it is not installed offer a menu entry pointing to its releases page:
            def open_parsec_vdd(*_args) -> None:
                import webbrowser  # pylint: disable=import-outside-toplevel
                webbrowser.open_new_tab("https://github.com/nomi-san/parsec-vdd/releases")
            tray_menu.append(traymenuitem(_("Add Virtual Monitor Support"), "display.png",
                                          tooltip=_("Install parsec-vdd to enable virtual monitors"),
                                          cb=open_parsec_vdd))
        # maybe add: session info, clipboard, sharing, etc
        # control: disconnect clients
        tray_menu.connect("deactivate", self.tray_menu_deactivated)
        return tray_menu

    def parsec_vdd_installed(self) -> bool:
        # pylint: disable=import-outside-toplevel
        try:
            from xpra.platform.win32.parsecvdd import query_device_status, DeviceStatus
            status = query_device_status()
            log("parsec-vdd device status=%s", status)
            return status != DeviceStatus.NOT_INSTALLED
        except Exception:
            log("failed to query parsec-vdd device status", exc_info=True)
            # assume it is installed so we don't show a misleading menu entry:
            return True

    def add_tray_menu_items(self, tray_menu):
        if not features.window:
            return

        def readonly_toggled(menuitem) -> None:
            log("readonly_toggled(%s)", menuitem)
            ro = menuitem.get_active()
            if ro != self.server.readonly:
                self.server.readonly = ro
                self.server.setting_changed("readonly", ro)

        from xpra.gtk.widget import checkitem
        tray_menu.append(checkitem(_("Read-only"), cb=readonly_toggled, active=self.server.readonly))

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
                w = c(self, XPRA_APP_ID, self.menu, "Xpra Shadow Server",
                      icon_filename="server-notconnected",
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
        if not self.widget:
            return
        try:
            self.widget.set_icon(filename)
        except Exception as e:
            log.warn("Warning: failed to set tray icon to %s", filename)
            log.warn(" %s", e)

    def tray_menu_deactivated(self, *_args) -> None:
        self.menu_shown = False

    def tray_click_callback(self, button: int, pressed: int, time=0) -> None:
        log("tray_click_callback(%s, %s, %i) tray menu=%s, shown=%s",
            button, pressed, time, self.menu, self.menu_shown)
        if pressed:
            self.close_tray_menu()
        else:
            # status icon can give us a position function:
            # except this doesn't work and nothing happens!
            # position_menu = self.widget.tray_widget.position_menu
            # pos = position_menu(self.menu, x, y, self.widget.tray_widget)
            if POSIX and not OSX:
                self.menu.popup_at_pointer()
            else:
                with SilenceWarningsContext(DeprecationWarning):
                    self.menu.popup(None, None, None, None, button, time)
            self.menu_shown = True

    def tray_exit_callback(self, *_args) -> None:
        self.close_tray_menu()
        GLib.idle_add(self.server.clean_quit, False)

    def close_tray_menu(self, *_args) -> None:
        if self.menu_shown:
            self.menu.popdown()
            self.menu_shown = False
