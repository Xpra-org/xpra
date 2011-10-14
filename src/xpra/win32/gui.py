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

from wimpiggy.util import gtk_main_quit_really
from wimpiggy.log import Logger
log = Logger()

def grok_modifier_map(display_source):
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


def get_icon_filename(icon_name):
    filename = os.path.join(os.path.dirname(sys.executable), 'icons', icon_name)
    log.debug("get_icon_filename(%s)=%s, exists=%s" % (icon_name, filename, os.path.exists(filename)))
    if os.path.exists(filename):
        return  filename
    return  None

def get_license_text():
    filename = os.path.join(os.path.dirname(sys.executable), 'COPYING')
    if not os.path.exists(filename):
        return "GPL version 2"
    try:
        file = open(filename, mode='rb')
        return file.read()
    finally:
        file.close()
LICENSE = get_license_text()

def get_pixbuf(icon_name):
    try:
        icon_filename = get_icon_filename(icon_name)
        return  gtk.gdk.pixbuf_new_from_file(icon_filename)
    except:
        return  None

def get_image(icon_name, size=None):
    try:
        pixbuf = get_pixbuf(icon_name)
        if not pixbuf:
            return  None
        if size:
            pixbuf = pixbuf.scale_simple(size, size, gtk.gdk.INTERP_BILINEAR)
        return  gtk.image_new_from_pixbuf(pixbuf)
    except:
        return  None


class ClipboardProtocolHelper(object):
    def __init__(self, send_packet_cb):
        self.send = send_packet_cb

    def send_all_tokens(self):
        pass

    def process_clipboard_packet(self, packet):
        packet_type = packet[0]
        if packet_type == "clipboard_request":
            (_, request_id, selection, _) = packet
            self.send(["clipboard-contents-none", request_id, selection])



class ClientExtras(object):
    def __init__(self, send_packet_cb, pulseaudio, opts):
        self.send = send_packet_cb
        self.menu_shown = False
        self.setup_menu()
        self.setup_tray(opts.tray_icon)
    
    def exit(self):
        if self.tray:
            self.tray.close()

    def handshake_complete(self):
        pass

    def can_notify(self):
        #not implemented yet
        return  self.notify is not None

    def show_notify(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        if self.notify:
            self.notify(self.tray.getHWND(), summary, body, expire_timeout)
    
    def close_notify(self, id):
        pass

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        if False:
            # winsound is currently disabled because it does not work for me! :(
            # maybe because I run Windows through VirtualBox?
            import winsound #@UnresolvedImport
            winsound.Beep(pitch, duration)
        import gtk.gdk
        gtk.gdk.beep()

    def get_keymap_spec(self):
        return None,None,None





    def setup_menu(self):
        menu = gtk.Menu()
        menu.set_title("Xpra")

        def item(title, icon_name, tooltip, cb):
            menu_item = gtk.ImageMenuItem(title)
            image = get_image(icon_name, 24)
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
            return menu_item

        menu.append(item("About", "information.png", None, self.about))
        #menu.append(item("Options", "configure", None, self.options))
        menu.append(item("Disconnect", "quit.png", None, self.quit))
        #menu.append(item("Close", "close.png", None, self.close_menu))
        self._popup_menu_workaround(menu)
        menu.connect("deactivate", self.menu_deactivated)
        menu.show_all()
        self.menu = menu

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
        dialog.set_license(str(LICENSE))
        dialog.set_website("http://xpra.org/")
        dialog.set_website_label("xpra.org")
        pixbuf = get_pixbuf("xpra.png")
        if pixbuf:
            dialog.set_logo(pixbuf)
        dialog.set_program_name("Xpra")
        def response(*args):
            dialog.destroy()
            self.about_dialog = None
        dialog.connect("response", response)
        self.about_dialog = dialog
        dialog.show()
        pass

    def setup_tray(self, tray_icon_filename):
        self.tray = None
        self.notify = None
        if not tray_icon_filename or not os.path.exists(tray_icon_filename):
            tray_icon_filename = get_icon_filename('xpra.ico')
        if not tray_icon_filename or not os.path.exists(tray_icon_filename):
            log.error("invalid tray icon filename: '%s'" % tray_icon_filename)

        try:
            from xpra.win32.win32_tray import Win32Tray
            self.tray = Win32Tray(self.activate_menu, self.quit, tray_icon_filename)
        except Exception, e:
            log.error("failed to load native Windows NotifyIcon: %s", e)
            return  #cant do balloon without tray!
        try:
            from xpra.win32.win32_balloon import notify
            self.notify = notify
        except Exception, e:
            log.error("failed to load native win32 balloon: %s", e)
        

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

    def quit(self, *args):
        gtk_main_quit_really()

    def _popup_menu_workaround(self, menu):
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
