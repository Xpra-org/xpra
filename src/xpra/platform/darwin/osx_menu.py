# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk
from xpra.gtk_common.gtk_util import menuitem
from xpra.client.gtk_base.about import about
from xpra.platform.paths import get_icon

from xpra.log import Logger
log = Logger()

#for attention_request:
CRITICAL_REQUEST = 0
INFO_REQUEST = 10


OSXMenu = None
def getOSXMenu():
    global OSXMenu
    if OSXMenu is None:
        OSXMenu = OSXMenuHelper()
    return OSXMenu


class OSXMenuHelper(object):
    """
    we have to do this stuff here so we can
    re-use the same instance,
    and change the callbacks if needed.
    (that way, the launcher and the client can both change the menus)
    """

    def __init__(self):
        self.menu_bar = None
        self.hidden_window = None
        self.quit_menu_item = None
        self.menus = []
        self.quit_callback = None

    def set_quit_callback(self, cb):
        self.quit_callback = cb

    def quit(self):
        log("quit() callback=%s", self.quit_callback)
        if self.quit_callback:
            self.quit_callback()

    def build(self):
        if self.menu_bar is None:
            self.build_menu_bar()
        return self.menu_bar

    def rebuild(self):
        if self.menu_bar:
            self.remove_all_menus()
            self.menu_bar = None
        return self.build()

    def remove_all_menus(self):
        if self.menu_bar:
            for x in self.menu_bar.get_children():
                self.menu_bar.remove(x)
                x.hide()
        self.menus = []

    def build_menu_bar(self):
        self.menu_bar = gtk.MenuBar()
        def make_menu(name, submenu):
            item = gtk.MenuItem(name)
            item.set_submenu(submenu)
            item.show_all()
            self.menu_bar.add(item)
            return submenu
        self.menuitem("About Xpra", "information.png", None, about)
        info_menu        = make_menu("Info", gtk.Menu())
        info_menu.add(self.menuitem("About Xpra", "information.png", None, about))
        self.menu_bar.show_all()


    #the code below is mostly duplicated from xpra/client/gtk2...

    def menuitem(self, title, icon_name=None, tooltip=None, cb=None):
        """ Utility method for easily creating an ImageMenuItem """
        image = None
        if icon_name:
            image = self.get_image(icon_name, 24)
        return menuitem(title, image, tooltip, cb)

    def get_image(self, icon_name, size=None):
        try:
            pixbuf = get_icon(icon_name)
            log("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
            if not pixbuf:
                return  None
            if size:
                pixbuf = pixbuf.scale_simple(size, size, gtk.gdk.INTERP_BILINEAR)
            return  gtk.image_new_from_pixbuf(pixbuf)
        except:
            log.error("get_image(%s, %s)", icon_name, size, exc_info=True)
            return  None
