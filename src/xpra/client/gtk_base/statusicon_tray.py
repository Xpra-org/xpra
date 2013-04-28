# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Posix systems with X11 display -- the parts that
# may import gtk.

import os
from xpra.gtk_common.gobject_compat import import_gtk, import_gdk
gtk = import_gtk()
gdk = import_gdk()

from xpra.client.tray_base import TrayBase
from xpra.gtk_common.gtk_util import set_tooltip_text
from xpra.platform.paths import get_icon_dir

from xpra.log import Logger
log = Logger()


class GTKStatusIconTray(TrayBase):

    def __init__(self, popup_cb, activate_cb, delay_tray, tray_icon_filename, tooltip=None):
        TrayBase.__init__(self, popup_cb, activate_cb, delay_tray, tray_icon_filename)
        self.tray_widget = gtk.StatusIcon()
        set_tooltip_text(self.tray_widget, tooltip or "Xpra")
        self.tray_widget.connect('popup-menu', popup_cb)
        self.tray_widget.connect('activate', activate_cb)
        filename = self.get_tray_icon_filename(tray_icon_filename)
        if filename:
            self.set_icon_from_file(filename)
        if delay_tray:
            self.hide()
            self.client.connect("first-ui-received", self.show)
        else:
            self.show()

    def hide(self, *args):
        self.tray_widget.set_visible(False)

    def show(self, *args):
        self.tray_widget.set_visible(True)

    def set_tooltip(self, text=None):
        set_tooltip_text(self.tray_widget, text or "Xpra")

    def set_blinking(self, on):
        if hasattr(self.tray_widget, "set_blinking"):
            self.tray_widget.set_blinking(on)

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
