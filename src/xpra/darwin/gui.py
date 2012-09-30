# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import gtk.gdk

from xpra.platform.client_extras_base import ClientExtrasBase
from xpra.keys import get_gtk_keymap
from wimpiggy.log import Logger
log = Logger()


class ClientExtras(ClientExtrasBase):
    def __init__(self, client, opts, conn):
        ClientExtrasBase.__init__(self, client, opts, conn)
        self.locate_icon_filename(opts.tray_icon)
        self.setup_growl(opts.notifications)
        self.setup_macdock()

    def setup_growl(self, enabled):
        self.growl_notifier = None
        if not enabled:
            return
        try:
            import Growl        #@UnresolvedImport
            name = self.client.session_name or "Xpra"
            self.growl_notifier = Growl.GrowlNotifier(name, ["highlight"])
            self.growl_notifier.register()
            log.info("using growl for notications")
            def set_session_name(*args):
                self.growl_notifier.applicationName = self.client.session_name
            if not self.client.session_name:
                #session_name will get set during handshake
                self.client.connect("handshake-complete", set_session_name)
        except Exception, e:
            log.error("failed to load Growl: %s, notifications will not be shown", e)

    def locate_icon_filename(self, opts_tray_icon):
        # ensure icon_filename points to a valid file (or None)
        self.icon_filename = None
        if opts_tray_icon and os.path.exists(opts_tray_icon):
            self.icon_filename = opts_tray_icon
        else:
            #try to find the default icon:
            x = os.path.join(self.get_data_dir(), "icons", "xpra.png")
            if os.path.exists(x):
                self.icon_filename = x
        log.debug("darwin client extras using icon_filename=%s", self.icon_filename)

    def updated_menus(self):
        self.macapp.sync_menubar()

    def setup_macdock(self):
        log.debug("setup_macdock()")
        self.macapp = None
        try:
            import gtk_osxapplication		#@UnresolvedImport
            self.macapp = gtk_osxapplication.OSXApplication()
            if self.icon_filename:
                log.debug("setup_macdock() loading icon from %s", self.icon_filename)
                pixbuf = gtk.gdk.pixbuf_new_from_file(self.icon_filename)
                self.macapp.set_dock_icon_pixbuf(pixbuf)
            #setup the menu:
            self.menu_bar = gtk.MenuBar()
            # We need to add it to a widget (otherwise it just does not work)
            self.hidden_window = gtk.Window()
            self.hidden_window.add(self.menu_bar)
            self.quit_menu_item = gtk.MenuItem("Quit")
            self.quit_menu_item.connect("activate", self.quit)
            self.menu_bar.add(self.quit_menu_item)
            self.menu_bar.show_all()
            self.macapp.set_menu_bar(self.menu_bar)
            self.quit_menu_item.hide()

            self._menu_item_pos = 0
            def add_item(item):
                self.macapp.insert_app_menu_item(item, self._menu_item_pos)
                self._menu_item_pos += 1
            add_item(self.make_aboutmenuitem())
            add_item(self.make_sessioninfomenuitem())
            add_item(self.make_bellmenuitem())
            add_item(self.make_cursorsmenuitem())
            add_item(self.make_notificationsmenuitem())
            add_item(self.make_encodingsmenuitem())
            if not self.client.readonly:
                add_item(self.make_layoutsmenuitem())
            add_item(self.make_qualitysubmenu())
            #add_item(self.make_compressionmenu())
            add_item(self.make_refreshmenuitem())
            add_item(self.make_raisewindowsmenuitem())
            add_item(gtk.SeparatorMenuItem())

            #dock menu
            self.dock_menu = gtk.Menu()
            self.disconnect_dock_item = gtk.MenuItem("Disconnect")
            self.disconnect_dock_item.connect("activate", self.quit)
            self.dock_menu.add(self.disconnect_dock_item)
            self.dock_menu.show_all()
            self.macapp.set_dock_menu(self.dock_menu)

            self.macapp.connect("NSApplicationBlockTermination", self.quit)
            def active(*args):
                log.debug("active()")
            def inactive(*args):
                log.debug("inactive()")
            self.macapp.connect("NSApplicationDidBecomeActive", active)
            self.macapp.connect("NSApplicationWillResignActive", inactive)
            def dock_ready(*args):
                log.debug("dock_ready()")
                self.macapp.ready()
            self.client.connect("handshake-complete", dock_ready)
        except Exception, e:
            log.error("failed to create dock: %s", e)


    def can_notify(self):
        return  self.growl_notifier is not None

    def show_notify(self, dbus_id, nid, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        if not self.growl_notifier:
            return
        if self.icon_filename:
            import Growl.Image  #@UnresolvedImport
            icon = Growl.Image.imageFromPath(self.icon_filename)
        else:
            icon = None
        sticky = expire_timeout>30*1000
        self.growl_notifier.notify('highlight', summary, body, icon, sticky)

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        import Carbon.Snd           #@UnresolvedImport
        Carbon.Snd.SysBeep(1)

    def get_gtk_keymap(self):
        return  get_gtk_keymap()

    def grok_modifier_map(self, display_source, xkbmap_mod_meanings):
        modifiers = ClientExtrasBase.grok_modifier_map(self, display_source, xkbmap_mod_meanings)
        modifiers["meta"] = 1 << 3
        return  modifiers

    def get_data_dir(self):
        return  os.environ.get("XDG_DATA_DIRS", os.getcwd())
