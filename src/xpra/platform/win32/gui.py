# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

from xpra.log import Logger
log = Logger()


def get_native_notifier_classes():
    try:
        from xpra.platform.win32.win32_notifier import Win32_Notifier
        return [Win32_Notifier]
    except:
        log.warn("cannot load native win32 notifier", exc_info=True)
        return []

def get_native_tray_classes():
    try:
        from xpra.platform.win32.win32_tray import Win32Tray
        return [Win32Tray]
    except:
        log.warn("cannot load native win32 tray", exc_info=True)
        return []

def get_native_system_tray_classes(*args):
    #Win32Tray cannot set the icon from data
    #so it cannot be used for application trays
    return []


class ClientExtras(object):
    def __init__(self, client):
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
