# This file is part of Parti.
# Copyright (C) 2011 Antoine Martin <antoine@nagafix.co.uk>
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

import os.path
import pygtk
pygtk.require("2.0")
import gtk
import gobject

from xpra.platform.client_extras_base import ClientExtrasBase
from wimpiggy.log import Logger
log = Logger()


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



class ClientExtras(ClientExtrasBase):
    def __init__(self, client, opts):
        ClientExtrasBase.__init__(self, client)
        self.setup_menu()
        self.setup_tray(opts.tray_icon)
    
    def exit(self):
        if self.tray:
            self.tray.close()

    def can_notify(self):
        return  self.notify is not None

    def show_notify(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        if self.notify:
            self.notify(self.tray.getHWND(), summary, body, expire_timeout)
    

    def setup_menu(self):
        self.menu_shown = False
        menu = gtk.Menu()
        menu.set_title("Xpra")

        def item(title, icon_name, tooltip, cb):
            menu_item = gtk.ImageMenuItem(title)
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
            return menu_item

        menu.append(item("About", "information.png", None, self.about))
        #menu.append(item("Options", "configure", None, self.options))
        menu.append(item("Disconnect", "quit.png", None, self.quit))
        #menu.append(item("Close", "close.png", None, self.close_menu))
        self._popup_menu_workaround(menu)
        menu.connect("deactivate", self.menu_deactivated)
        menu.show_all()
        self.menu = menu


    def setup_tray(self, tray_icon_filename):
        self.tray = None
        self.notify = None
        if not tray_icon_filename or not os.path.exists(tray_icon_filename):
            tray_icon_filename = self.get_icon_filename('xpra.ico')
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
