# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import gtk.gdk

from xpra.platform.paths import get_icon_dir
from xpra.log import Logger
log = Logger()

#for attention_request:
CRITICAL_REQUEST = 0
INFO_REQUEST = 10


class OSXTray(object):

    def __init__(self, menu_helper, tray_icon):
        from xpra.platform.darwin.gui import get_OSXApplication
        self.menu_helper = menu_helper
        self.macapp = get_OSXApplication()
        self.icon_filename = tray_icon
        self.last_attention_request_id = -1

        self.set_dock_menu()
        self.set_dock_icon()
        menu = self.menu_helper.build()
        if menu:
            self.macapp.set_menu_bar(menu)
        #not needed?:
        #self.macapp.connect("NSApplicationBlockTermination", self.quit)

    def cleanup(self):
        pass

    def quit(self, *args):
        self.menu_helper.quit()

    def ready(self):
        self.macapp.ready()

    def set_tooltip(self, text=None):
        #label cannot be set on the dock icon?
        pass

    def set_blinking(self, on):
        if on:
            if self.last_attention_request_id<0:
                self.last_attention_request_id = self.macapp.attention_request(INFO_REQUEST)
        else:
            if self.last_attention_request_id>=0:
                self.macapp.cancel_attention_request(self.last_attention_request_id)
                self.last_attention_request_id = -1

    def set_icon(self, basefilename):
        if not self.macapp:
            return
        with_ext = "%s.png" % basefilename
        icon_dir = get_icon_dir()
        filename = os.path.join(icon_dir, with_ext)
        if not os.path.exists(filename):
            log.error("could not find icon '%s' in osx icon dir: %s", with_ext, icon_dir)
            return
        pixbuf = gtk.gdk.pixbuf_new_from_file(filename)
        self.macapp.set_dock_icon_pixbuf(pixbuf)

    def set_dock_menu(self):
        #dock menu
        self.dock_menu = gtk.Menu()
        self.disconnect_dock_item = gtk.MenuItem("Disconnect")
        self.disconnect_dock_item.connect("activate", self.quit)
        self.dock_menu.add(self.disconnect_dock_item)
        self.dock_menu.show_all()
        self.macapp.set_dock_menu(self.dock_menu)

    def set_dock_icon(self):
        if self.icon_filename:
            log("setup_macdock() loading icon from %s", self.icon_filename)
            pixbuf = gtk.gdk.pixbuf_new_from_file(self.icon_filename)
            self.macapp.set_dock_icon_pixbuf(pixbuf)
