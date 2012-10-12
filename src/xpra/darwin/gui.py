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

macapp = None
def get_OSXApplication():
    global macapp
    if macapp is None:
        try:
            import gtk_osxapplication        #@UnresolvedImport
            macapp = gtk_osxapplication.OSXApplication()
        except:
            pass
    return macapp

is_osx_ready = False
def osx_ready():
    global is_osx_ready
    if not is_osx_ready:
        get_OSXApplication().ready()
        is_osx_ready = True

#we have to do this stuff here so we can
#re-use the same instance
macmenubar = None
hidden_window = None
quit_menu_item = None
def setup_menubar(quit_cb):
    global macmenubar, hidden_window, quit_menu_item
    log("setup_menubar(%s)", quit_cb)
    if macmenubar:
        return macmenubar
    macapp = get_OSXApplication()
    assert macapp
    macmenubar = gtk.MenuBar()
    macmenubar.show_all()
    macapp.set_menu_bar(macmenubar)
    return macmenubar


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
            log("failed to load Growl: %s, notifications will not be shown", e)

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
        log("darwin client extras using icon_filename=%s", self.icon_filename)

    def cleanup(self):
        ClientExtrasBase.cleanup(self)
        self.remove_all_menus()

    def remove_all_menus(self):
        for x in self.menu_bar.get_children():
            self.menu_bar.remove(x)
            x.hide()
        self.info_menu        = None
        self.features_menu    = None
        self.encodings_menu   = None
        self.quality_menu     = None
        self.actions_menu     = None
        self.macapp.sync_menubar()

    def setup_macdock(self):
        log.debug("setup_macdock()")
        self.macapp = get_OSXApplication()
        try:
            #setup the menu:
            self.menu_bar = setup_menubar(self.quit)
            #remove all existing sub-menus:
            self.remove_all_menus()

            def make_menu(name, submenu):
                item = gtk.MenuItem(name)
                item.set_submenu(submenu)
                item.show_all()
                self.menu_bar.add(item)
                return submenu
            self.info_menu        = make_menu("Info", gtk.Menu())
            self.features_menu    = make_menu("Features", gtk.Menu())
            self.encodings_menu   = make_menu("Encodings", self.make_encodingssubmenu())
            self.quality_menu     = make_menu("Quality", self.make_qualitysubmenu())
            self.actions_menu     = make_menu("Actions", gtk.Menu())

            #info
            self.info_menu.add(self.make_aboutmenuitem())
            self.info_menu.add(self.make_sessioninfomenuitem())
            #features
            self.features_menu.add(self.make_bellmenuitem())
            self.features_menu.add(self.make_cursorsmenuitem())
            self.features_menu.add(self.make_notificationsmenuitem())
            if not self.client.readonly:
                self.features_menu.add(self.make_layoutsmenuitem())
            #actions:
            self.actions_menu.add(self.make_refreshmenuitem())
            self.actions_menu.add(self.make_raisewindowsmenuitem())

            self.menu_bar.show_all()
            self.macapp.sync_menubar()

            #dock menu
            self.dock_menu = gtk.Menu()
            self.disconnect_dock_item = gtk.MenuItem("Disconnect")
            self.disconnect_dock_item.connect("activate", self.quit)
            self.dock_menu.add(self.disconnect_dock_item)
            self.dock_menu.show_all()
            self.macapp.set_dock_menu(self.dock_menu)
            if self.icon_filename:
                log("setup_macdock() loading icon from %s", self.icon_filename)
                pixbuf = gtk.gdk.pixbuf_new_from_file(self.icon_filename)
                self.macapp.set_dock_icon_pixbuf(pixbuf)

            self.macapp.connect("NSApplicationBlockTermination", self.quit)
            def dock_ready(*args):
                log.debug("dock_ready()")
                osx_ready()
            self.client.connect("handshake-complete", dock_ready)
        except Exception, e:
            log.error("failed to create dock: %s", e, exc_info=True)

    def set_qualitymenu(self, *args):
        vq = not self.client.mmap_enabled and self.client.encoding in ("jpeg", "webp", "x264")
        if not vq:
            self.quality_menu.hide()
        else:
            self.quality_menu.show()
        self.quality_menu.set_sensitive(vq)
        for i in self.quality_menu.get_children():
            i.set_sensitive(vq)

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

    def get_data_dir(self):
        return  os.environ.get("XDG_DATA_DIRS", os.getcwd())
