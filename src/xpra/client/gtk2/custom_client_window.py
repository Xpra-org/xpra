# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject
from xpra.client.gtk2.topbar_client_window import TopBarClientWindow
from xpra.gtk_common.gtk_util import imagebutton, CheckMenuItem


"""
Example of a custom client window top bar with some icons and a menu.
"""
class CustomClientWindow(TopBarClientWindow):

    def add_top_bar_widgets(self, hbox):
        #use an event box so we can style it:
        b = gtk.HBox()
        eb = gtk.EventBox()
        eb.add(b)
        eb.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color(red=0, green=0, blue=0))
        white = gtk.gdk.Color(red=60000, green=63000, blue=65000)
        hbox.pack_start(eb, expand=True, fill=True)
        for i,l in {"encoding.png"  : "Encoding",
                  "speed.png"       : "Speed",
                  "information.png" : "Information",
                  "keyboard.png"    : "Keyboard",
                  "clipboard.png"   : "Clipboard"}.items():
            icon = self._client.get_pixbuf(i)
            def clicked(*args):
                self.info("clicked(%s)", args)
            button = imagebutton(l, icon, clicked_callback=clicked, label_color=white)
            button.set_relief(gtk.RELIEF_NONE)
            b.add(button)
        icon = self._client.get_pixbuf("xpra.png")
        submenu = gtk.Menu()
        for l, a, s, r in (
                           ("Check Option 1", True, True, False),
                           ("Disabled Option", True, False, False),
                           ("Radio 1", True, True, True),
                           ("Radio 2", False, True, True),
                           ):
            item = CheckMenuItem(l)
            def item_changed(item):
                self.info("item_changed(%s)", item)
            item.set_active(a)
            item.set_sensitive(s)
            item.set_draw_as_radio(r)
            item.connect("toggled", item_changed)
            submenu.append(item)
        submenu.show_all()
        def show_menu(btn, *args):
            self.info("show_menu(%s, %s)", btn, args)
            submenu.popup(None, None, None, 1, 0)
        menu_button = imagebutton("Xpra", icon, clicked_callback=show_menu, label_color=white)
        menu_button.set_relief(gtk.RELIEF_NONE)
        menu_button.show_all()
        b.add(menu_button)

    def do_expose_event(self, event):
        self.capture_log = False
        TopBarClientWindow.do_expose_event(self, event)
        self.capture_log = True

gobject.type_register(CustomClientWindow)
