# This file is part of Parti.
# Copyright (C) 2011 Antoine Martin <antoine@nagafix.co.uk>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

import sys
import os.path
import pygtk
pygtk.require("2.0")
import gtk
import gobject
import webbrowser

from xpra.scripts.main import ENCODINGS
from wimpiggy.util import gtk_main_quit_really
from wimpiggy.log import Logger
log = Logger()


#utility method to ensure there is always only one CheckMenuItem
#selected in a submenu:
def ensure_item_selected(submenu, item):
    if item.get_active():
        #find if another encoding is active and disable it:
        for x in submenu.get_children():
            if x!=item and x.get_active():
                x.set_active(False)
        return item
    #ensure there is at least one other active item
    for x in submenu.get_children():
        if x!=item and x.get_active():
            return x
    #if not then keep this one active:
    item.set_active(True)
    return item


class ClientExtrasBase(object):

    def __init__(self, client):
        self.client = client
        self.license_text = None

    def quit(self, *args):
        gtk_main_quit_really()

    def exit(self):
        pass

    def can_notify(self):
        return  False

    def show_notify(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        pass
    
    def close_notify(self, id):
        pass

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        import gtk.gdk
        gtk.gdk.beep()

    def get_keymap_spec(self):
        return None,None,None,None


    def about(self, *args):
        dialog = gtk.AboutDialog()
        def on_website_hook(dialog, web, *args):
            webbrowser.open("http://xpra.org/")
        def on_email_hook(dialog, mail, *args):
            webbrowser.open("mailto://"+mail)
        gtk.about_dialog_set_url_hook(on_website_hook)
        gtk.about_dialog_set_email_hook(on_email_hook)
        dialog.set_name("Xpra")
        from xpra import __version__
        dialog.set_version(__version__)
        dialog.set_copyright('Copyright (c) 2009-2011')
        dialog.set_authors(('Antoine Martin <antoine@nagafix.co.uk>',
                            'Nathaniel Smith <njs@pobox.com>',
                            'Serviware - Arthur Huillet <ahuillet@serviware.com>'))
        #dialog.set_artists ([""])
        dialog.set_license(self.get_license_text())
        dialog.set_website("http://xpra.org/")
        dialog.set_website_label("xpra.org")
        pixbuf = self.get_pixbuf("xpra.png")
        if pixbuf:
            dialog.set_logo(pixbuf)
        dialog.set_program_name("Xpra")
        def response(*args):
            dialog.destroy()
            self.about_dialog = None
        dialog.connect("response", response)
        self.about_dialog = dialog
        dialog.show()



    def grok_modifier_map(self, display_source):
        modifier_map = {
            "shift": 1 << 0,
            "lock": 1 << 1,
            "control": 1 << 2,
            "mod1": 1 << 3,
            "mod2": 1 << 4,
            "mod3": 1 << 5,
            "mod4": 1 << 6,
            "mod5": 1 << 7,
            "scroll": 0,
            "num": 0,
            "meta": 0,
            "super": 0,
            "hyper": 0,
            "alt": 0,
            }
        modifier_map["nuisance"] = (modifier_map["lock"]
                                    | modifier_map["scroll"]
                                    | modifier_map["num"])
        return modifier_map


    def get_data_dir(self):
        return  os.path.dirname(sys.executable)

    def get_icon_filename(self, icon_name):
        filename = os.path.join(self.get_data_dir(), 'icons', icon_name)
        log.debug("get_icon_filename(%s)=%s, exists=%s" % (icon_name, filename, os.path.exists(filename)))
        if os.path.exists(filename):
            return  filename
        return  None

    def get_license_text(self):
        if self.license_text:
            return  self.license_text
        filename = os.path.join(self.get_data_dir(), 'COPYING')
        if os.path.exists(filename):
            try:
                file = open(filename, mode='rb')
                return file.read()
            finally:
                file.close()
        if not self.license_text:
            self.license_text = "GPL version 2"
        return self.license_text

    def get_pixbuf(self, icon_name):
        try:
            icon_filename = self.get_icon_filename(icon_name)
            return  gtk.gdk.pixbuf_new_from_file(icon_filename)
        except:
            return  None
    
    def get_image(self, icon_name, size=None):
        try:
            pixbuf = self.get_pixbuf(icon_name)
            if not pixbuf:
                return  None
            if size:
                pixbuf = pixbuf.scale_simple(size, size, gtk.gdk.INTERP_BILINEAR)
            return  gtk.image_new_from_pixbuf(pixbuf)
        except:
            return  None



    def menuitem(self, title, icon_name=None, tooltip=None, cb=None):
        menu_item = gtk.ImageMenuItem(title)
        image = None
        if icon_name:
            image = self.get_image(icon_name, 24)
        if image:
            menu_item.set_image(image)
            #override gtk defaults: we *want* icons:
            settings = menu_item.get_settings()
            settings.set_property('gtk-menu-images', True)
            if hasattr(settings, "set_always_show_image"):
                settings.set_always_show_image(True)
        if tooltip:
            menu_item.set_tooltip_text(tooltip)
        if cb:
            menu_item.connect('activate', cb)
        menu_item.show()
        return menu_item

    def checkitem(self, title, cb=None):
        check_item = gtk.CheckMenuItem(title)
        if cb:
            check_item.connect("toggled", cb)
        check_item.show()
        return check_item


    def close_menu(self, *args):
        if self.menu_shown:
            self.menu.popdown()
            self.menu_shown = False

    def menu_deactivated(self, *args):
        self.menu_shown = False

    def activate_menu(self, *args):
        self.close_menu()
        self.menu.popup(None, None, None, 1, 0, None)
        self.menu_shown = True

    def make_aboutmenuitem(self):
        return  self.menuitem("About", "information.png", None, self.about)

    def make_bellmenuitem(self):
        self.bell_menuitem = self.checkitem("Bell", self.bell_toggled)
        return  self.bell_menuitem

    def make_notificationsmenuitem(self):
        self.notifications_menuitem = self.checkitem("Notifications", self.notifications_toggled)
        return self.notifications_menuitem

    def make_encodingsmenuitem(self):
        encodings = self.menuitem("Encoding", "configure.png", "Choose picture data encoding", None)
        self.encodings_submenu = gtk.Menu()
        encodings.set_submenu(self.encodings_submenu)
        self.popup_menu_workaround(self.encodings_submenu)
        return encodings

    def make_jpegsubmenu(self):
        self.jpeg_quality = self.menuitem("JPEG Quality", "slider.png", "Change JPEG quality setting", None)
        self.jpeg_submenu = gtk.Menu()
        self.jpeg_quality.set_submenu(self.jpeg_submenu)
        self.popup_menu_workaround(self.jpeg_submenu)
        jpeg_options = [10, 50, 80, 95]
        if self.client.jpegquality>0 and self.client.jpegquality not in jpeg_options:
            i = 0
            for x in jpeg_options:
                if self.client.jpegquality<x:
                    jpeg_options.insert(i, self.client.jpegquality)
                    break
                i += 1
        def set_jpeg_quality(item):
            item = ensure_item_selected(self.jpeg_submenu, item)
            q = int(item.get_label().replace("%", ""))
            if q!=self.client.jpegquality:
                log.debug("setting jpeg quality to %s", q)
                self.client.send_jpeg_quality(q)
        for q in jpeg_options:
            qi = gtk.CheckMenuItem("%s%%" % q)
            qi.set_active(q==self.client.jpegquality)
            qi.connect('activate', set_jpeg_quality)
            self.jpeg_submenu.append(qi)
        self.jpeg_submenu.show_all()
        return self.jpeg_quality

    def updated_menus(self):
        pass

    def update_jpeg_menu(self, *args):
        if self.jpeg_quality:
            self.jpeg_quality.set_sensitive("jpeg"==self.client.encoding)
            self.updated_menus()

    def update_encodings_menu(self, *args):
        if self.encodings_submenu:
            for encoding in ENCODINGS:
                encoding_item = gtk.CheckMenuItem(encoding)
                encoding_item.get_label()
                def encoding_changed(item):
                    item = ensure_item_selected(self.encodings_submenu, item)
                    enc = item.get_label()
                    if self.client.encoding!=enc:
                        self.client.set_encoding(enc)
                        log.debug("setting encoding to %s", enc)
                        self.update_jpeg_menu()
                        self.updated_menus()
                encoding_item.set_active(encoding==self.client.encoding)
                encoding_item.set_sensitive(encoding in self.client.server_capabilities.get("encodings", ["rgb24"]))
                encoding_item.connect("toggled", encoding_changed)
                self.encodings_submenu.append(encoding_item)
            self.encodings_submenu.show_all()

    def make_refreshmenuitem(self):
        return self.menuitem("Refresh", "retry.png", None, self.force_refresh)
    
    def make_disconnectmenuitem(self):
        return self.menuitem("Disconnect", "quit.png", None, self.quit)

    def make_closemenuitem(self):
        return self.menuitem("Close Menu", "close.png", None, self.close_menu)

    def setup_menu(self, show_close=False):
        self.client.connect("handshake-complete", self.handshake_complete)
        self.menu_shown = False
        menu = gtk.Menu()
        menu.set_title(self.client.session_name or "Xpra")
        def set_menu_title(*args):
            #set the real name when available:
            self.menu.set_title(self.client.session_name)
        self.client.connect("handshake-complete", set_menu_title)

        menu.append(self.make_aboutmenuitem())
        menu.append(gtk.SeparatorMenuItem())
        menu.append(self.make_bellmenuitem())
        menu.append(self.make_notificationsmenuitem())
        if len(ENCODINGS)>1:
            menu.append(self.make_encodingsmenuitem())
        else:
            self.encodings_submenu = None
        if "jpeg" in ENCODINGS:
            menu.append(self.make_jpegsubmenu())
        else:
            self.jpeg_quality = None
            self.jpeg_submenu = None
        menu.append(self.make_refreshmenuitem())
        #menu.append(item("Options", "configure", None, self.options))
        menu.append(gtk.SeparatorMenuItem())
        menu.append(self.make_disconnectmenuitem())
        if show_close:
            menu.append(self.make_closemenuitem())
        self.popup_menu_workaround(menu)
        menu.connect("deactivate", self.menu_deactivated)
        menu.show_all()
        self.menu = menu

    def popup_menu_workaround(self, menu):
        #win32 overrides this to add the workaround
        pass

    def add_popup_menu_workaround(self, menu):
        """ windows does not automatically close the popup menu when we click outside it
            so we workaround it by using a timer and closing the menu when the mouse
            has stayed outside it for more than 0.5s.
            This code must be added to all the sub-menus of the popup menu too!
        """
        def enter_menu(*args):
            log.debug("mouse_in_tray_menu=%s", self.mouse_in_tray_menu)
            self.mouse_in_tray_menu_counter += 1
            self.mouse_in_tray_menu = True
        def leave_menu(*args):
            log.debug("mouse_in_tray_menu=%s", self.mouse_in_tray_menu)
            self.mouse_in_tray_menu_counter += 1
            self.mouse_in_tray_menu = False
            def check_menu_left(expected_counter):
                if self.mouse_in_tray_menu:
                    return    False
                if expected_counter!=self.mouse_in_tray_menu_counter:
                    return    False            #counter has changed
                self.close_menu()
            gobject.timeout_add(500, check_menu_left, self.mouse_in_tray_menu_counter)
        self.mouse_in_tray_menu_counter = 0
        self.mouse_in_tray_menu = False
        log.debug("popup_menu_workaround: adding events callbacks")
        menu.connect("enter-notify-event", enter_menu)
        menu.connect("leave-notify-event", leave_menu)

    def bell_toggled(self, *args):
        self.client.bell_enabled = self.bell_menuitem.get_active()
        log.debug("bell_toggled(%s) bell_enabled=%s", args, self.client.bell_enabled)

    def notifications_toggled(self, *args):
        self.client.notifications_enabled = self.notifications_menuitem.get_active()
        log.debug("notifications_toggled(%s) notifications_enabled=%s", args, self.client.notifications_enabled)

    def force_refresh(self, *args):
        log.debug("force refresh")
        self.client.send_refresh_all()


    def set_checkboxes(self):
        self.bell_menuitem.set_active(self.client.bell_enabled)
        self.bell_menuitem.set_sensitive(self.client.server_capabilities.get("bell", False))
        self.notifications_menuitem.set_active(self.client.notifications_enabled)
        self.notifications_menuitem.set_sensitive(self.client.server_capabilities.get("notifications", False))

    def handshake_complete(self, *args):
        self.set_checkboxes()
        #populate encoding submenu and show unsupported encodings as greyed out:
        self.update_encodings_menu()
        #jpeg menu: enable it when encoding uses jpeg:
        self.update_jpeg_menu()
