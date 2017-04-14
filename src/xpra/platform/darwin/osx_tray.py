# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import gtk.gdk

from xpra.log import Logger
log = Logger("tray", "osx")

from xpra.client.tray_base import TrayBase
from xpra.platform.darwin.osx_menu import getOSXMenuHelper
from xpra.platform.darwin.gui import set_exit_cb
from xpra.platform.gui import ready as gui_ready

#constants for attention_request:
CRITICAL_REQUEST = 0
INFO_REQUEST = 10


class OSXTray(TrayBase):

    def __init__(self, *args):
        TrayBase.__init__(self, *args)
        from xpra.platform.darwin.gui import get_OSXApplication
        self.macapp = get_OSXApplication()
        assert self.macapp, "cannot use OSX Tray without the native gtkosx_application bindings"
        self.last_attention_request_id = -1

        self.set_global_menu()
        self.set_dock_menu()
        self.set_dock_icon()
        set_exit_cb(self.quit)


    def show(self):
        pass

    def hide(self):
        pass

    def quit(self, *args):
        log("quit(%s) exit_cb=%s", args, self.exit_cb)
        if self.exit_cb:
            self.exit_cb()
            return True     #we've handled the quit request ourselves - I hope..
        return False

    def ready(self):
        gui_ready()

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

    def set_icon_from_data(self, pixels, has_alpha, w, h, rowstride):
        tray_icon = gtk.gdk.pixbuf_new_from_data(pixels, gtk.gdk.COLORSPACE_RGB, has_alpha, 8, w, h, rowstride)
        self.macapp.set_dock_icon_pixbuf(tray_icon)

    def do_set_icon_from_file(self, filename):
        if not self.macapp:
            return
        pixbuf = gtk.gdk.pixbuf_new_from_file(filename)
        self.macapp.set_dock_icon_pixbuf(pixbuf)


    def set_global_menu(self):
        mh = getOSXMenuHelper()
        if mh.build()!=self.menu:
            log.error("the menu (%s) is not from the menu helper!", self.menu)
            return
        #redundant: the menu bar has already been set during gui init
        #using the basic the simple menu from build_menu_bar()
        self.macapp.set_menu_bar(self.menu)
        mh.add_full_menu()
        log("OSXTray.set_global_menu() done")

    def set_dock_menu(self):
        #dock menu
        log("OSXTray.set_dock_menu()")
        self.dock_menu = gtk.Menu()
        self.disconnect_dock_item = gtk.MenuItem("Disconnect")
        self.disconnect_dock_item.connect("activate", self.quit)
        self.dock_menu.add(self.disconnect_dock_item)
        self.dock_menu.show_all()
        self.macapp.set_dock_menu(self.dock_menu)
        log("OSXTray.set_dock_menu() done")

    def set_dock_icon(self):
        if not self.default_icon_filename:
            return
        filename = os.path.abspath(self.default_icon_filename)
        if not os.path.exists(filename):
            log.warn("cannot set dock icon, file '%s' not found!", filename)
            return
        log("OSXTray.set_dock_icon() loading icon from %s", filename)
        pixbuf = gtk.gdk.pixbuf_new_from_file(filename)
        self.macapp.set_dock_icon_pixbuf(pixbuf)
