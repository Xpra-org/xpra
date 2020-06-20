# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import Gtk

from xpra.util import envbool
from xpra.os_util import OSX
from xpra.gtk_common.gtk_util import menuitem
from xpra.gtk_common.about import about, close_about
from xpra.platform.gui import get_icon_size
from xpra.log import Logger

log = Logger("menu")

MENU_ICONS = envbool("XPRA_MENU_ICONS", True)


def ll(m):
    try:
        return "%s:%s" % (type(m), m.get_label())
    except AttributeError:
        return str(m)

def set_sensitive(widget, sensitive):
    if OSX:
        if sensitive:
            widget.show()
        else:
            widget.hide()
    widget.set_sensitive(sensitive)


#utility method to ensure there is always only one CheckMenuItem
#selected in a submenu:
def ensure_item_selected(submenu, item, recurse=True):
    if not isinstance(item, Gtk.CheckMenuItem):
        return None
    if item.get_active():
        #deactivate all except this one
        def deactivate(items, skip=None):
            for x in items:
                if x==skip:
                    continue
                if isinstance(x, Gtk.MenuItem):
                    submenu = x.get_submenu()
                    if submenu and recurse:
                        deactivate(submenu.get_children(), skip)
                if isinstance(x, Gtk.CheckMenuItem):
                    if x!=item and x.get_active():
                        x.set_active(False)
        deactivate(submenu.get_children(), item)
        return item
    #ensure there is at least one other active item
    def get_active_item(items):
        for x in items:
            if isinstance(x, Gtk.MenuItem):
                submenu = x.get_submenu()
                if submenu:
                    a = get_active_item(submenu.get_children())
                    if a:
                        return a
            if isinstance(x, Gtk.CheckMenuItem):
                if x.get_active():
                    return x
        return None
    active = get_active_item(submenu.get_children())
    if active:
        return active
    #if not then keep this one active:
    item.set_active(True)
    return item


class MenuHelper:

    def __init__(self, client):
        self.client = client
        self.menu = None
        self.menu_shown = False
        self.menu_icon_size = get_icon_size()

    def build(self):
        if self.menu is None:
            try:
                self.menu = self.setup_menu()
            except Exception as e:
                log("build()", exc_info=True)
                log.error("Error: failed to setup menu")
                log.error(" %s", e)
        return self.menu

    def show_session_info(self, *args):
        self.client.show_session_info(*args)

    def show_bug_report(self, *args):
        self.client.show_bug_report(*args)


    def get_image(self, icon_name, size=None):
        return self.client.get_image(icon_name, size)

    def setup_menu(self):
        raise NotImplementedError()

    def cleanup(self):
        self.close_menu()
        close_about()

    def close_menu(self, *_args):
        if self.menu_shown:
            self.menu.popdown()
            self.menu_shown = False

    def menu_deactivated(self, *_args):
        self.menu_shown = False

    def activate(self, button=1, time=0):
        log("activate(%s, %s)", button, time)
        self.show_menu(button, time)

    def popup(self, button, time):
        log("popup(%s, %s)", button, time)
        self.show_menu(button, time)

    def show_menu(self, button, time):
        self.close_menu()
        self.menu.popup(None, None, None, None, button, time)
        self.menu_shown = True


    def handshake_menuitem(self, *args, **kwargs):
        """ Same as menuitem() but this one will be disabled until we complete the server handshake """
        mi = self.menuitem(*args, **kwargs)
        set_sensitive(mi, False)
        def enable_menuitem(*_args):
            set_sensitive(mi, True)
        self.client.after_handshake(enable_menuitem)
        return mi


    def make_menu(self):
        return Gtk.Menu()

    def menuitem(self, title, icon_name=None, tooltip=None, cb=None, **kwargs):
        """ Utility method for easily creating an ImageMenuItem """
        image = None
        if MENU_ICONS:
            image = kwargs.get("image")
            if icon_name and not image:
                icon_size = self.menu_icon_size or get_icon_size()
                image = self.get_image(icon_name, icon_size)
        return menuitem(title, image, tooltip, cb)

    def checkitem(self, title, cb=None, active=False):
        """ Utility method for easily creating a CheckMenuItem """
        check_item = Gtk.CheckMenuItem(label=title)
        check_item.set_active(active)
        if cb:
            check_item.connect("toggled", cb)
        check_item.show()
        return check_item


    def make_aboutmenuitem(self):
        return self.menuitem("About Xpra", "xpra.png", None, about)

    def make_updatecheckmenuitem(self):
        def show_update_window(*_args):
            from xpra.client.gtk_base.update_status import getUpdateStatusWindow
            w = getUpdateStatusWindow()
            w.show()
            w.check()
        return self.menuitem("Check for updates", "update.png", None, show_update_window)

    def make_sessioninfomenuitem(self):
        def show_session_info_cb(*_args):
            #we define a generic callback to remove the arguments
            #(which contain the menu widget and are of no interest to the 'show_session_info' function)
            self.show_session_info()
        sessioninfomenuitem = self.handshake_menuitem("Session Info", "statistics.png", None, show_session_info_cb)
        return sessioninfomenuitem

    def make_bugreportmenuitem(self):
        def show_bug_report_cb(*_args):
            self.show_bug_report()
        return  self.menuitem("Bug Report", "bugs.png", None, show_bug_report_cb)

    def make_closemenuitem(self):
        return self.menuitem("Close Menu", "close.png", None, self.close_menu)
