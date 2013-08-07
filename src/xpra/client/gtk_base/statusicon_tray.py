# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# A tray implemented using gtk.StatusIcon

import os
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk, is_gtk3
gtk = import_gtk()
gdk = import_gdk()

from xpra.client.tray_base import TrayBase, debug
from xpra.gtk_common.gtk_util import set_tooltip_text
from xpra.platform.paths import get_icon_dir

ORIENTATION = {}
if not is_gtk3():
    #where was this moved to??
    ORIENTATION[gtk.ORIENTATION_HORIZONTAL] = "HORIZONTAL"
    ORIENTATION[gtk.ORIENTATION_VERTICAL]   = "VERTICAL"


class GTKStatusIconTray(TrayBase):

    def __init__(self, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb):
        TrayBase.__init__(self, menu, tooltip, icon_filename, size_changed_cb, click_cb, mouseover_cb, exit_cb)
        self.tray_widget = gtk.StatusIcon()
        set_tooltip_text(self.tray_widget, tooltip or "Xpra")
        self.tray_widget.connect('activate', self.activate_menu)
        self.tray_widget.connect('popup-menu', self.popup_menu)
        if self.size_changed_cb:
            self.tray_widget.connect('size-changed', self.size_changed_cb)
        filename = self.get_tray_icon_filename(icon_filename)
        if filename:
            self.set_icon_from_file(filename)

    def activate_menu(self, widget, *args):
        debug("activate_menu(%s, %s)", widget, args)
        self.click_cb(1, 1)
        self.click_cb(1, 0)

    def popup_menu(self, widget, button, time, *args):
        debug("popup_menu(%s, %s, %s, %s)", widget, button, time, args)
        self.click_cb(button, 1, 0)
        self.click_cb(button, 0, 0)


    def hide(self, *args):
        self.tray_widget.set_visible(False)

    def show(self, *args):
        self.tray_widget.set_visible(True)


    def get_screen(self):
        ag = self.tray_widget.get_geometry()
        if ag is None:
            return -1
        screen, _, _ = ag
        return screen
    
    def get_orientation(self):
        ag = self.tray_widget.get_geometry()
        if ag is None:
            return None
        _, _, gtk_orientation = ag
        return ORIENTATION.get(gtk_orientation)

    def get_geometry(self):
        ag = self.tray_widget.get_geometry()
        debug("GTKStatusIconTray.get_geometry() %s.get_geometry()=%s", self.tray_widget, ag)
        if ag is None:
            return None
        _, geom, _ = ag
        return geom.x, geom.y, geom.width, geom.height

    def get_size(self):
        s = self.tray_widget.get_size()
        return [s, s]


    def set_tooltip(self, text=None):
        set_tooltip_text(self.tray_widget, text or "Xpra")

    def set_blinking(self, on):
        if hasattr(self.tray_widget, "set_blinking"):
            self.tray_widget.set_blinking(on)


    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride):
        tray_icon = gdk.pixbuf_new_from_data(pixels, gdk.COLORSPACE_RGB, has_alpha, 8, w, h, rowstride)
        self.tray_widget.set_from_pixbuf(tray_icon)


    def set_icon(self, basefilename):
        with_ext = "%s.png" % basefilename
        icon_dir = get_icon_dir()
        filename = os.path.join(icon_dir, with_ext)
        self.set_icon_from_file(filename)

    def do_set_icon_from_file(self, filename):
        if hasattr(self.tray_widget, "set_from_file"):
            self.tray_widget.set_from_file(filename)
        else:
            pixbuf = gdk.pixbuf_new_from_file(filename)
            self.tray_widget.set_from_pixbuf(pixbuf)
