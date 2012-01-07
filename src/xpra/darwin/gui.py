# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import gtk.gdk

from xpra.platform.client_extras_base import ClientExtrasBase
from wimpiggy.log import Logger
log = Logger()


class ClientExtras(ClientExtrasBase):
    def __init__(self, client, opts):
        ClientExtrasBase.__init__(self, client, opts)
        self.locate_icon_filename(opts.tray_icon)
        self.setup_growl()
        self.setup_macdock()
        self.clipboard_helper = None

    def setup_growl(self):
        self.growl_notifier = None
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
            menu = gtk.MenuBar()
            # We need to add it to a widget (otherwise it just does not work)
            self.hidden_window = gtk.Window()
            self.hidden_window.add(menu)
            quit_item = gtk.MenuItem("Quit")
            quit_item.connect("activate", self.quit)
            menu.add(quit_item)
            menu.show_all()
            self.macapp.set_menu_bar(menu)
            quit_item.hide()

            self.macapp.insert_app_menu_item(self.make_aboutmenuitem(), 0)
            self.macapp.insert_app_menu_item(self.make_sessioninfomenuitem(), 1)
            self.macapp.insert_app_menu_item(self.make_bellmenuitem(), 2)
            self.macapp.insert_app_menu_item(self.make_notificationsmenuitem(), 3)
            self.macapp.insert_app_menu_item(self.make_encodingsmenuitem(), 4)
            if not self.client.readonly:
                self.macapp.insert_app_menu_item(self.make_layoutsmenuitem(), 5)
            self.macapp.insert_app_menu_item(self.make_jpegsubmenu(), 6)
            self.macapp.insert_app_menu_item(self.make_compressionmenu(), 7)
            self.macapp.insert_app_menu_item(self.make_refreshmenuitem(), 8)
            self.macapp.insert_app_menu_item(self.make_raisewindowsmenuitem(), 9)
            self.macapp.insert_app_menu_item(gtk.SeparatorMenuItem(), 10)

            #dock menu (does not work!)
            #menu = gtk.Menu()
            #quit_item = gtk.MenuItem("Disconnect")
            #quit_item.connect("activate", self.quit)
            #menu.add(quit_item)
            #menu.show_all()
            #self.macapp.set_dock_menu(menu)

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

    def show_notify(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
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

    def grok_modifier_map(self, display_source, xkbmap_mod_meanings):
        modifiers = ClientExtrasBase.grok_modifier_map(self, display_source, xkbmap_mod_meanings)
        modifiers["meta"] = 1 << 3
        return  modifiers

    def get_data_dir(self):
        return  os.environ.get("XDG_DATA_DIRS", os.getcwd())
