# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

from xpra.log import Logger
log = Logger("win32")
grablog = Logger("win32", "grab")

from xpra.platform.win32.win32_events import get_win32_event_listener
from xpra.platform.win32.window_hooks import Win32Hooks
from xpra.util import AdHocStruct


KNOWN_EVENTS = {}
POWER_EVENTS = {}
try:
    import win32con             #@UnresolvedImport
    for x in dir(win32con):
        if x.endswith("_EVENT"):
            v = getattr(win32con, x)
            KNOWN_EVENTS[v] = x
        if x.startswith("PBT_"):
            v = getattr(win32con, x)
            POWER_EVENTS[v] = x
except:
    pass


def do_init():
    #tell win32 we handle dpi
    try:
        from ctypes import WINFUNCTYPE, windll
        from ctypes.wintypes import BOOL
        prototype = WINFUNCTYPE(BOOL)
        SetProcessDPIAware = prototype(("SetProcessDPIAware", windll.user32))
        dpi_set = SetProcessDPIAware()
        log("SetProcessDPIAware()=%s", dpi_set)
    except Exception as e:
        log("failed to set DPI: %s", e)


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
    return get_native_tray_classes()

def gl_check():
    #This is supposed to help py2exe
    #(must be done after we setup the sys.path in platform.win32.paths):
    from OpenGL.platform import win32   #@UnusedImport
    from xpra.platform.win32 import is_wine
    if is_wine():
        return "disabled when running under wine"
    return None


def add_window_hooks(window):
    #gtk2 to window handle:
    try:
        handle = window.get_window().handle
    except:
        return
    #glue code for gtk to win32 APIs:
    #add even hook class:
    win32hooks = Win32Hooks(handle)
    log("add_window_hooks(%s) added hooks for hwnd %#x: %s", window, handle, win32hooks)
    window.win32hooks = win32hooks
    window.win32hooks.max_size = None
    #save original geometry function:
    window.__apply_geometry_hints = window.apply_geometry_hints
    #our function for taking gdk window hints and passing them to the win32 hooks class:
    def apply_maxsize_hints(window, hints):
        maxw = hints.get("max_width", 0)
        maxh = hints.get("max_height", 0)
        log("apply_maxsize_hints(%s, %s) found max: %sx%s", window, hints, maxw, maxh)
        if maxw>0 or maxh>0:
            window.win32hooks.max_size = (maxw or 32000), (maxh or 32000)
        elif window.win32hooks.max_size:
            #was set, clear it
            window.win32hooks.max_size = None
    #our monkey patching method, which calls the function above:
    def apply_geometry_hints(window, hints):
        apply_maxsize_hints(window, hints)
        return window.__apply_geometry_hints(hints)
    window.apply_geometry_hints = apply_geometry_hints
    #apply current geometry hints, if any:
    if window.geometry_hints:
        apply_maxsize_hints(window, window.geometry_hints)

def remove_window_hooks(window):
    try:
        if hasattr(window, "win32hooks"):
            win32hooks = window.win32hooks
            log("remove_window_hooks(%s) found %s", window, win32hooks)
            if win32hooks:
                win32hooks.cleanup()
                window.win32hooks = None
    except:
        log.error("remove_window_hooks(%s)", exc_info=True)


def get_double_click_time():
    try:
        import win32gui                     #@UnresolvedImport
        return win32gui.GetDoubleClickTime()
    except:
        return 0


class ClientExtras(object):
    def __init__(self, client, opts):
        self.client = client
        self._kh_warning = False
        self.setup_console_event_listener()
        try:
            import win32con                 #@Reimport @UnresolvedImport
            el = get_win32_event_listener(True)
            if el:
                el.add_event_callback(win32con.WM_ACTIVATEAPP, self.activateapp)
                el.add_event_callback(win32con.WM_POWERBROADCAST, self.power_broadcast_event)
        except Exception as e:
            log.error("cannot register focus and power callbacks: %s", e)

    def cleanup(self):
        self.setup_console_event_listener(False)
        log("ClientExtras.cleanup() ended")
        el = get_win32_event_listener(False)
        if el:
            el.cleanup()
        self.client = None

    def activateapp(self, wParam, lParam):
        log("WM_ACTIVATEAPP: %s/%s client=%s", wParam, lParam, self.client)
        if wParam==0 and self.client:
            #our app has lost focus
            self.client.update_focus(0, False)

    def power_broadcast_event(self, wParam, lParam):
        log("WM_POWERBROADCAST: %s/%s client=%s", POWER_EVENTS.get(wParam, wParam), lParam, self.client)
        #maybe also "PBT_APMQUERYSUSPEND" and "PBT_APMQUERYSTANDBY"?
        if wParam==win32con.PBT_APMSUSPEND and self.client:
            self.client.suspend()
        #According to the documentation:
        #The system always sends a PBT_APMRESUMEAUTOMATIC message whenever the system resumes.
        elif wParam==win32con.PBT_APMRESUMEAUTOMATIC and self.client:
            self.client.resume()

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
        event_name = KNOWN_EVENTS.get(event, event)
        info_events = [win32con.CTRL_C_EVENT,
                       win32con.CTRL_LOGOFF_EVENT,
                       win32con.CTRL_BREAK_EVENT,
                       win32con.CTRL_SHUTDOWN_EVENT,
                       win32con.CTRL_CLOSE_EVENT]
        if event in info_events:
            log.info("received console event %s", str(event_name).replace("_EVENT", ""))
        else:
            log.warn("unknown console event: %s", event_name)
        return 0


def main():
    from xpra.platform import init, clean
    try:
        init("Platform-Events", "Platform Events Test")
        import sys
        if "-v" in sys.argv or "--verbose" in sys.argv:
            from xpra.platform.win32.win32_events import log as win32_event_logger
            log.enable_debug()
            win32_event_logger.enable_debug()

        def suspend():
            log.info("suspend event")
        def resume():
            log.info("resume event")
        fake_client = AdHocStruct()
        fake_client.window_with_grab = None
        fake_client.suspend = suspend
        fake_client.resume = resume
        fake_client.keyboard_helper = None
        ClientExtras(fake_client, None)

        import gobject
        gobject.threads_init()

        log.info("Event loop is running")
        loop = gobject.MainLoop()
        try:
            loop.run()
        except KeyboardInterrupt:
            log.info("exiting on keyboard interrupt")
    finally:
        #this will wait for input on win32:
        clean()

if __name__ == "__main__":
    main()
