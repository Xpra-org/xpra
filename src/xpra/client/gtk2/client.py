# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
gobject.threads_init()
from gtk import gdk


from xpra.client.gtk_base.gtk_client_base import GTKXpraClient
from xpra.client.gtk2.tray_menu import GTK2TrayMenu
from xpra.log import Logger

log = Logger("gtk", "client")
grablog = Logger("gtk", "client", "grab")

from xpra.client.gtk2.client_window import ClientWindow


class XpraClient(GTKXpraClient):

    def __init__(self):
        GTKXpraClient.__init__(self)
        self.UI_watcher = None

    def init(self, opts):
        GTKXpraClient.init(self, opts)
        self.ClientWindowClass = ClientWindow
        log("init(..) ClientWindowClass=%s", self.ClientWindowClass)
        from xpra.platform.ui_thread_watcher import get_UI_watcher
        self.UI_watcher = get_UI_watcher(self.timeout_add)


    def cleanup(self):
        uw = self.UI_watcher
        if uw:
            self.UI_watcher = None
            uw.stop()
        GTKXpraClient.cleanup(self)

    def __repr__(self):
        return "gtk2.client"

    def client_type(self):
        return "Python/Gtk2"

    def client_toolkit(self):
        return "gtk2"


    def get_tray_menu_helper_classes(self):
        tmhc = GTKXpraClient.get_tray_menu_helper_classes(self)
        tmhc.append(GTK2TrayMenu)
        return tmhc


    def make_hello(self):
        capabilities = GTKXpraClient.make_hello(self)
        capabilities["encoding.supports_delta"] = [x for x in ("png", "rgb24", "rgb32") if x in self.get_core_encodings()]
        capabilities["pointer.grabs"] = True
        return capabilities

    def init_packet_handlers(self):
        GTKXpraClient.init_packet_handlers(self)
        self._ui_packet_handlers["pointer-grab"] = self._process_pointer_grab
        self._ui_packet_handlers["pointer-ungrab"] = self._process_pointer_ungrab


    def process_ui_capabilities(self):
        GTKXpraClient.process_ui_capabilities(self)
        self.UI_watcher.start()
        #if server supports it, enable UI thread monitoring workaround when needed:
        def UI_resumed():
            self.send("resume", True, self._id_to_window.keys())
        def UI_failed():
            self.send("suspend", True, self._id_to_window.keys())
        self.UI_watcher.add_resume_callback(UI_resumed)
        self.UI_watcher.add_fail_callback(UI_failed)


    def window_grab(self, window):
        mask = gdk.BUTTON_PRESS_MASK | gdk.BUTTON_RELEASE_MASK | gdk.POINTER_MOTION_MASK  | gdk.POINTER_MOTION_HINT_MASK | gdk.ENTER_NOTIFY_MASK | gdk.LEAVE_NOTIFY_MASK
        gdk.pointer_grab(window.get_window(), owner_events=True, event_mask=mask)
        #also grab the keyboard so the user won't Alt-Tab away:
        gdk.keyboard_grab(window.get_window(), owner_events=False)

    def window_ungrab(self):
        gdk.pointer_ungrab()
        gdk.keyboard_ungrab()


gobject.type_register(XpraClient)
