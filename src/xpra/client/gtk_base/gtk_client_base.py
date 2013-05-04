# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os
from xpra.gtk_common.gobject_compat import import_gobject, import_gtk, import_gdk
gobject = import_gobject()
gtk = import_gtk()
gdk = import_gdk()


from xpra.log import Logger
log = Logger()

from xpra.gtk_common.quit import (gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)
from xpra.gtk_common.cursor_names import cursor_names
from xpra.gtk_common.gtk_util import add_gtk_version_info
from xpra.client.ui_client_base import UIXpraClient
from xpra.client.gobject_client_base import GObjectXpraClient
from xpra.client.gtk_base.gtk_keyboard_helper import GTKKeyboardHelper
from xpra.platform.paths import get_icon_filename
from xpra.platform.gui import make_native_tray, system_bell
from xpra.client.gtk_base.client_tray import ClientTray


sys.modules['QtCore']=None


class GTKXpraClient(UIXpraClient, GObjectXpraClient):
    __gsignals__ = UIXpraClient.__gsignals__

    def __init__(self):
        GObjectXpraClient.__init__(self)
        UIXpraClient.__init__(self)
        self.session_info = None

    def init(self, opts):
        GObjectXpraClient.init(self, opts)
        UIXpraClient.init(self, opts)

    def run(self):
        UIXpraClient.run(self)
        gtk_main_quit_on_fatal_exceptions_enable()
        gtk.main()
        log("GTKXpraClient.run_main_loop() main loop ended, returning exit_code=%s", self.exit_code)
        return  self.exit_code

    def quit(self, exit_code=0):
        log("GTKXpraClient.quit(%s) current exit_code=%s", exit_code, self.exit_code)
        if self.exit_code is None:
            self.exit_code = exit_code
        if gtk.main_level()>0:
            #if for some reason cleanup() hangs, maybe this will fire...
            gobject.timeout_add(4*1000, gtk_main_quit_really)
            #try harder!:
            gobject.timeout_add(5*1000, os._exit, 1)
        self.cleanup()
        if gtk.main_level()>0:
            log("GTKXpraClient.quit(%s) main loop at level %s, calling gtk quit via timeout", exit_code, gtk.main_level())
            gobject.timeout_add(500, gtk_main_quit_really)


    def get_pixbuf(self, icon_name):
        try:
            if not icon_name:
                log("get_pixbuf(%s)=None", icon_name)
                return None
            icon_filename = get_icon_filename(icon_name)
            log("get_pixbuf(%s) icon_filename=%s", icon_name, icon_filename)
            if icon_filename:
                return self.do_get_pixbuf(icon_filename)
        except:
            log.error("get_pixbuf(%s)", icon_name, exc_info=True)
        return  None

    def do_get_pixbuf(self, icon_filename):
        raise Exception("override me!")


    def get_image(self, icon_name, size=None):
        try:
            pixbuf = self.get_pixbuf(icon_name)
            log("get_image(%s, %s) pixbuf=%s", icon_name, size, pixbuf)
            if not pixbuf:
                return  None
            return self.do_get_image(pixbuf, size)
        except:
            log.error("get_image(%s, %s)", icon_name, size, exc_info=True)
            return  None

    def do_get_image(self, pixbuf, size=None):
        raise Exception("override me!")


    def make_keyboard_helper(self, keyboard_sync, key_shortcuts):
        return GTKKeyboardHelper(self.send, keyboard_sync, key_shortcuts, self.send_layout, self.send_keymap)

    def make_tray(self, delay_tray, tray_icon):
        self.menu_helper = self.make_tray_menu()
        tray = make_native_tray(self.menu_helper, delay_tray, tray_icon)
        if tray:
            return tray
        try:
            from xpra.client.gtk_base.appindicator_tray import can_use_appindicator, AppindicatorTray
            if can_use_appindicator():
                return AppindicatorTray(self.menu_helper.menu, delay_tray, tray_icon)
        except Exception, e:
            log.warn("failed to load appindicator: %s" % e)
        try:
            from xpra.client.gtk_base.statusicon_tray import GTKStatusIconTray
            def popup(widget, button, time, *args):
                self.menu_helper.popup(button, time)
            def activate(*args):
                self.menu_helper.activate()
            gtk_tray = GTKStatusIconTray(popup, activate, delay_tray, tray_icon)
            self.menu_helper.build()
            return gtk_tray
        except Exception, e:
            log.warn("failed to load StatusIcon tray: %s" % e)


    def make_notifier(self):
        return None


    def supports_system_tray(self):
        #always True: we can always use gtk.StatusIcon as fallback
        return True

    def make_system_tray(self, client, wid, w, h):
        return ClientTray(client, wid, w, h)

    def get_root_size(self):
        raise Exception("override me!")

    def set_windows_cursor(self, gtkwindows, new_cursor):
        raise Exception("override me!")


    def get_current_modifiers(self):
        modifiers_mask = gdk.get_default_root_window().get_pointer()[-1]
        return self.mask_to_names(modifiers_mask)


    def make_hello(self, challenge_response=None):
        capabilities = UIXpraClient.make_hello(self, challenge_response)
        capabilities["named_cursors"] = len(cursor_names)>0
        add_gtk_version_info(capabilities, gtk)
        return capabilities


    def window_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        gdkwindow = None
        if window:
            gdkwindow = window.get_window()
        if gdkwindow is None:
            gdkwindow = gdk.get_default_root_window()
        log("window_bell(..) gdkwindow=%s", gdkwindow)
        if not system_bell(gdkwindow, device, percent, pitch, duration, bell_class, bell_id, bell_name):
            #fallback to simple beep:
            gdk.beep()
