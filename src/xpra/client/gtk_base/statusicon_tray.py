# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# A tray implemented using gtk.StatusIcon

import sys
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, is_gtk3
gtk = import_gtk()
gdk = import_gdk()

from xpra.client.tray_base import TrayBase, log
from xpra.gtk_common.gtk_util import get_icon_from_file, get_pixbuf_from_data, INTERP_HYPER

ORIENTATION = {}
if not is_gtk3():
    #where was this moved to??
    ORIENTATION[gtk.ORIENTATION_HORIZONTAL] = "HORIZONTAL"
    ORIENTATION[gtk.ORIENTATION_VERTICAL]   = "VERTICAL"

GUESS_GEOMETRY = sys.platform.startswith("win") or sys.platform.startswith("darwin")


class GTKStatusIconTray(TrayBase):

    def __init__(self, *args):
        TrayBase.__init__(self, *args)
        self.tray_widget = gtk.StatusIcon()
        self.tray_widget.set_tooltip_text(self.tooltip or "Xpra")
        self.tray_widget.connect('activate', self.activate_menu)
        self.tray_widget.connect('popup-menu', self.popup_menu)
        if self.size_changed_cb:
            self.tray_widget.connect('size-changed', self.size_changed_cb)
        filename = self.get_tray_icon_filename(self.default_icon_filename)
        if filename:
            self.set_icon_from_file(filename)
        self.tray_widget.set_visible(True)

    def may_guess(self):
        log("may_guess() GUESS_GEOMETRY=%s, current guess=%s", GUESS_GEOMETRY, self.geometry_guess)
        if GUESS_GEOMETRY:
            x, y = gdk.get_default_root_window().get_pointer()[:2]
            w, h = self.get_size()
            self.recalculate_geometry(x, y, w, h)

    def activate_menu(self, widget, *args):
        log("activate_menu(%s, %s)", widget, args)
        self.may_guess()
        self.click_cb(1, 1)
        self.click_cb(1, 0)

    def popup_menu(self, widget, button, time, *args):
        log("popup_menu(%s, %s, %s, %s)", widget, button, time, args)
        self.may_guess()
        self.click_cb(button, 1, 0)
        self.click_cb(button, 0, 0)


    def hide(self, *args):
        log("%s.set_visible(False)", self.tray_widget)
        if self.tray_widget:
            self.tray_widget.set_visible(False)

    def show(self, *args):
        log("%s.set_visible(True)", self.tray_widget)
        if self.tray_widget:
            self.tray_widget.set_visible(True)


    def get_screen(self):
        if not self.tray_widget:
            return -1
        ag = self.tray_widget.get_geometry()
        if ag is None:
            return -1
        screen, _, _ = ag[-3:]
        if not screen:
            return -1
        return screen.get_number()

    def get_orientation(self):
        if not self.tray_widget:
            return None
        ag = self.tray_widget.get_geometry()
        if ag is None:
            return None
        _, _, gtk_orientation = ag[-3:]
        return ORIENTATION.get(gtk_orientation)

    def get_geometry(self):
        assert self.tray_widget
        ag = self.tray_widget.get_geometry()
        log("GTKStatusIconTray.get_geometry() %s.get_geometry()=%s", self.tray_widget, ag)
        if ag is None:
            #probably win32 or OSX...
            self.may_guess()
            log("GTKStatusIconTray.get_geometry() returning guess: %s", self.geometry_guess)
            return self.geometry_guess
        #gtk3 adds an extra argument.. at the beginning!
        _, geom, _ = ag[-3:]
        return geom.x, geom.y, geom.width, geom.height

    def get_size(self):
        s = max(8, min(256, self.tray_widget.get_size()))
        return [s, s]


    def set_tooltip(self, text=None):
        self.tray_widget.set_tooltip_text(text or "Xpra")

    def set_blinking(self, on):
        if hasattr(self.tray_widget, "set_blinking"):
            self.tray_widget.set_blinking(on)


    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride):
        tray_icon = get_pixbuf_from_data(pixels, has_alpha, w, h, rowstride)
        self.set_icon_from_pixbuf(tray_icon)

    def do_set_icon_from_file(self, filename):
        tray_icon = get_icon_from_file(filename)
        self.set_icon_from_pixbuf(tray_icon)

    def set_icon_from_pixbuf(self, tray_icon):
        assert self.tray_widget
        if not tray_icon:
            return
        tw, th = self.get_geometry()[2:]
        w = tray_icon.get_width()
        h = tray_icon.get_height()
        log("set_icon_from_pixbuf(%s) geometry=%s, icon size=%s", tray_icon, self.get_geometry(), (w, h))
        if tw!=w or th!=h:
            tray_icon = tray_icon.scale_simple(tw, th, INTERP_HYPER)
        self.tray_widget.set_from_pixbuf(tray_icon)


def main():
    log.enable_debug()
    from xpra.gtk_common.gobject_compat import import_gobject
    gobject = import_gobject()
    s = GTKStatusIconTray(None, "test", "xpra.png", None, None, None, gtk.main_quit)
    gobject.timeout_add(1000*2, s.set_blinking, True)
    gobject.timeout_add(1000*5, s.set_blinking, False)
    gobject.timeout_add(1000*10, gtk.main_quit)
    gtk.main()


if __name__ == "__main__":
    main()
