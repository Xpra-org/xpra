# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

import os.path

from xpra.log import Logger
log = Logger()

from xpra.gtk_common.gobject_compat import import_gdk
gdk = import_gdk()


def make_tray_menu(client):
    #let the toolkit classes use their own
    return None

def make_native_tray(menu, delay_tray, tray_icon):
    #FIXME: use win32 code here!
    return None

def system_bell(self, *args):
    return False


class ClientExtras(object):
    def __init__(self, client, opts, conn):
        self.setup_console_event_listener()

    def cleanup(self):
        self.setup_console_event_listener(False)
        log("ClientExtras.cleanup() ended")

    def setup_console_event_listener(self, enable=1):
        try:
            import win32api     #@UnresolvedImport
            result = win32api.SetConsoleCtrlHandler(self.handle_console_event, enable)
            if result == 0:
                log.error("could not SetConsoleCtrlHandler (error %r)", win32api.GetLastError())
        except:
            pass

    def handle_console_event(self, event):
        log("handle_console_event(%s)", event)
        import win32con         #@UnresolvedImport
        events = {win32con.CTRL_C_EVENT         : "CTRL_C",
                  win32con.CTRL_LOGOFF_EVENT    : "LOGOFF",
                  win32con.CTRL_BREAK_EVENT     : "BREAK",
                  win32con.CTRL_SHUTDOWN_EVENT  : "SHUTDOWN",
                  win32con.CTRL_CLOSE_EVENT     : "CLOSE"
                  }
        if event in events:
            log.info("received win32 console event %s", events.get(event))
        return 0


    def setup_tray(self, no_tray, notifications, tray_icon_filename):
        self.tray = None
        self.notify = None
        if not no_tray:
            #we wait for session_name to be set during the handshake
            #the alternative would be to implement a set_name() method
            #on the Win32Tray - but this looks too complicated
            self.client.connect("handshake-complete", self.do_setup_tray, notifications, tray_icon_filename)

    def do_setup_tray(self, client, notifications, tray_icon_filename):
        self.tray = None
        self.notify = None
        if not tray_icon_filename or not os.path.exists(tray_icon_filename):
            tray_icon_filename = self.get_icon_filename('xpra.ico')
        if not tray_icon_filename or not os.path.exists(tray_icon_filename):
            log.error("invalid tray icon filename: '%s'" % tray_icon_filename)

        def tray_exit(*args):
            log("tray_exit() calling quit")
            self.quit()
        try:
            from xpra.platform.win32.win32_tray import Win32Tray
            self.tray = Win32Tray(self.get_tray_tooltip(), self.activate_menu, tray_exit, tray_icon_filename)
        except Exception, e:
            log.error("failed to load native Windows NotifyIcon: %s", e)

        #cant do balloon without a tray:
        if self.tray and notifications:
            try:
                from xpra.platform.win32.win32_balloon import notify
                self.notify = notify
            except Exception, e:
                log.error("failed to load native win32 balloon: %s", e)
