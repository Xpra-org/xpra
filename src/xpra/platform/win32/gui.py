# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

import os
from xpra.log import Logger
log = Logger("win32")
grablog = Logger("win32", "grab")
screenlog = Logger("win32", "screen")

from xpra.platform.win32.win32_events import get_win32_event_listener
from xpra.platform.win32.window_hooks import Win32Hooks
from xpra.util import AdHocStruct
import ctypes
from ctypes import windll, byref

WINDOW_HOOKS = os.environ.get("XPRA_WIN32_WINDOW_HOOKS", "1")=="1"
GROUP_LEADER = WINDOW_HOOKS and os.environ.get("XPRA_WIN32_GROUP_LEADER", "1")=="1"
UNDECORATED_STYLE = WINDOW_HOOKS and os.environ.get("XPRA_WIN32_UNDECORATED_STYLE", "1")=="1"
MAX_SIZE_HINT = WINDOW_HOOKS and os.environ.get("XPRA_WIN32_MAX_SIZE_HINT", "1")=="1"


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
    import win32api             #@UnresolvedImport
    import win32gui             #@UnresolvedImport
except Exception as e:
    log.warn("error loading pywin32: %s", e)


def do_init():
    #tell win32 we handle dpi
    try:
        if os.environ.get("XPRA_DPI_AWARE", "1")!="1":
            log.warn("SetProcessDPIAware not set due to environment override")
            return
        from ctypes import WINFUNCTYPE
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


def get_monitor_workarea_for_window(handle):
    try:
        monitor = win32api.MonitorFromWindow(handle, win32con.MONITOR_DEFAULTTONEAREST)
        mi = win32api.GetMonitorInfo(monitor)
        screenlog("get_monitor_workarea_for_window(%s) GetMonitorInfo(%s)=%s", handle, monitor, mi)
        #absolute workarea / monitor coordinates:
        #(all relative to 0,0 being top left)
        wx1, wy1, wx2, wy2 = mi['Work']
        mx1, my1, mx2, my2 = mi['Monitor']
        assert mx1<mx2 and my1<my2, "invalid monitor coordinates"
        #clamp to monitor, and make it all relative to monitor:
        rx1 = max(0, min(mx2-mx1, wx1-mx1))
        ry1 = max(0, min(my2-my1, wy1-my1))
        rx2 = max(0, min(mx2-mx1, wx2-mx1))
        ry2 = max(0, min(my2-my1, wy2-my1))
        assert rx1<rx2 and ry1<ry2, "invalid relative workarea coordinates"
        return rx1, ry1, rx2-rx1, ry2-ry1
    except Exception as e:
        log.warn("failed to query workareas: %s", e)
        return None


def noop(*args):
    pass


_propsys = None
def get_propsys():
    global _propsys
    if _propsys is None:
        try:
            from win32com.propsys import propsys    #@UnresolvedImport
            _propsys = propsys
        except Exception as e:
            log("unable to implement group leader: %s", e, exc_info=True)
            _propsys = False
    return _propsys


def add_window_hooks(window):
    if not WINDOW_HOOKS:
        #allows us to disable the win32 hooks for testing
        return
    #win32 cannot use set_group by default:
    try:
        window.get_window().set_group = noop
    except:
        pass
    #gtk2 to window handle:
    try:
        handle = window.get_window().handle
    except:
        return

    if GROUP_LEADER:
        #windows 7 onwards can use AppUserModel to emulate the group leader stuff:
        propsys = get_propsys()
        log("win32 hooks: propsys=%s", propsys)
        if propsys:
            def set_group(leader):
                try:
                    log("win32 hooks: set_group(%#x)", leader.handle)
                    ps = propsys.SHGetPropertyStoreForWindow(handle)
                    key = propsys.PSGetPropertyKeyFromName("System.AppUserModel.ID")
                    value = propsys.PROPVARIANTType(leader.handle)
                    log("win32 hooks: calling %s(%s, %s)", ps.SetValue, key, value)
                    ps.SetValue(key, value)
                except Exception as e:
                    log.error("failed to set group leader: %s", e)
            window.get_window().set_group = set_group
            log("hooked group leader override using %s", propsys)

    if UNDECORATED_STYLE:
        #OR windows never have any decorations or taskbar menu
        readd_window_options = None
        if not window._override_redirect:
            #override set_decorated so we can preserve the taskbar menu for undecorated windows
            window.__set_decorated = window.set_decorated
            def readd_window_options():
                try:
                    cur_style = win32api.GetWindowLong(handle, win32con.GWL_STYLE)
                    #re-add taskbar menu:
                    style = cur_style
                    style |= win32con.WS_SYSMENU
                    style |= win32con.WS_MAXIMIZEBOX
                    #can always minimize:
                    style |= win32con.WS_MINIMIZEBOX
                    log("readd_window_options() using %s style=%#x on window %#x", ["unchanged", "new"][int(style!=cur_style)], style, handle)
                    if style!=cur_style:
                        win32gui.SetWindowLong(handle, win32con.GWL_STYLE, style)
                except:
                    log.warn("failed to override window style", exc_info=True)
            def set_decorated(b):
                window.__set_decorated(b)
                readd_window_options()
            window.set_decorated = set_decorated
            readd_window_options()
            #override after_window_state_updated so we can re-add the missing style options
            #(somehow doing it from on_realize which calls add_window_hooks is not enough)
            window.__after_window_state_updated = window.after_window_state_updated
            def after_window_state_updated(*args):
                log("after_window_state_updated%s", args)
                window.__after_window_state_updated()
                readd_window_options()
            window.after_window_state_updated = after_window_state_updated
    
            try:
                el = get_win32_event_listener(True)
                log("win32_event_listener=%s", el)
                if el:
                    def activate_cb(*args):
                        log("activate_cb%s", args)
                        readd_window_options()
                    el.add_event_callback(win32con.WM_ACTIVATEAPP, activate_cb)
                    window.activate_app_hook = activate_cb
            except:
                log.warn("failed to add activateapp callback", exc_info=True)

    if MAX_SIZE_HINT:
        #glue code for gtk to win32 APIs:
        #add event hook class:
        win32hooks = Win32Hooks(handle)
        log("add_window_hooks(%s) added hooks for hwnd %#x: %s", window, handle, win32hooks)
        window.win32hooks = win32hooks
        win32hooks.max_size = None
        win32hooks.setup()

        #save original geometry function:
        window.__apply_geometry_hints = window.apply_geometry_hints
        #our function for taking gdk window hints and passing them to the win32 hooks class:
        def apply_maxsize_hints(hints):
            workw, workh = 0, 0
            if not window.get_decorated():
                workarea = get_monitor_workarea_for_window(handle)
                log("using workarea as window size limit for undecorated window: %s", workarea)
                if workarea:
                    workw, workh = workarea[2:4]
            maxw = hints.get("max_width", 0)
            maxh = hints.get("max_height", 0)
            if workw>0 and workh>0:
                #clamp to workspace for undecorated windows:
                if maxw>0 and maxh>0:
                    maxw = min(workw, maxw)
                    maxh = min(workh, maxh)
                else:
                    maxw, maxh = workw, workh
            log("apply_maxsize_hints(%s) for window %s, found max: %sx%s", hints, window, maxw, maxh)
            if (maxw>0 and maxw<32767) or (maxh>0 and maxh<32767):
                window.win32hooks.max_size = (maxw or 32000), (maxh or 32000)
            elif window.win32hooks.max_size:
                #was set, clear it
                window.win32hooks.max_size = None
            #remove them so GTK doesn't try to set attributes,
            #which would remove the maximize button:
            for x in ("max_width", "max_height"):
                if x in hints:
                    del hints[x]
        #our monkey patching method, which calls the function above:
        def apply_geometry_hints(hints):
            apply_maxsize_hints(hints)
            return window.__apply_geometry_hints(hints)
        window.apply_geometry_hints = apply_geometry_hints
        #apply current geometry hints, if any:
        if window.geometry_hints:
            apply_maxsize_hints(window.geometry_hints)

def remove_window_hooks(window):
    try:
        if hasattr(window, "win32hooks"):
            win32hooks = window.win32hooks
            log("remove_window_hooks(%s) found %s", window, win32hooks)
            if win32hooks:
                win32hooks.cleanup()
                window.win32hooks = None
        if hasattr(window, "activate_app_hook"):
            activate_app_cb = window.activate_app_hook
            if activate_app_cb:
                el = get_win32_event_listener(True)
                el.remove_event_callback(win32con.WM_ACTIVATEAPP, activate_app_cb)
            window.activate_app_hook = None
    except:
        log.error("remove_window_hooks(%s)", exc_info=True)


def get_xdpi():
    try:
        return _get_device_caps(win32con.LOGPIXELSX)
    except Exception as e:
        log.warn("failed to get xdpi: %s", e)
    return -1

def get_ydpi():
    try:
        return _get_device_caps(win32con.LOGPIXELSY)
    except Exception as e:
        log.warn("failed to get ydpi: %s", e)
    return -1

def get_dpi():
    try:
        return (get_xdpi() + get_ydpi())//2
    except Exception as e:
        log.warn("failed to get dpi: %s", e)
    return -1

#those constants aren't found in win32con:
SPI_GETFONTSMOOTHING            = 0x004A
SPI_GETFONTSMOOTHINGCONTRAST    = 0x200C
SPI_GETFONTSMOOTHINGORIENTATION = 0x2012
FE_FONTSMOOTHINGORIENTATIONBGR  = 0x0000
FE_FONTSMOOTHINGORIENTATIONRGB  = 0x0001
FE_FONTSMOOTHINGORIENTATIONVBGR = 0x0002
FE_FONTSMOOTHINGORIENTATIONVRGB = 0x0003
SPI_GETFONTSMOOTHINGTYPE        = 0x200A
FE_FONTSMOOTHINGCLEARTYPE       = 0x0002
FE_FONTSMOOTHINGDOCKING         = 0x8000
FE_ORIENTATION_STR = {
                      FE_FONTSMOOTHINGORIENTATIONBGR    : "BGR",
                      FE_FONTSMOOTHINGORIENTATIONRGB    : "RGB",
                      FE_FONTSMOOTHINGORIENTATIONVBGR   : "VBGR",
                      FE_FONTSMOOTHINGORIENTATIONVRGB   : "VRGB",
                      }
FE_FONTSMOOTHING_STR = {
    0                           : "Normal",
    FE_FONTSMOOTHINGCLEARTYPE   : "ClearType",
    }

def get_antialias_info():
    info = {}
    try:
        SystemParametersInfo = windll.user32.SystemParametersInfoA
        def add_param(constant, name, convert):
            i = ctypes.c_uint32()
            if SystemParametersInfo(constant, 0, byref(i), 0):
                info[name] = convert(i.value)
        add_param(SPI_GETFONTSMOOTHING, "enabled", bool)
        #"Valid contrast values are from 1000 to 2200. The default value is 1400."
        add_param(SPI_GETFONTSMOOTHINGCONTRAST, "contrast", int)
        def orientation(v):
            return FE_ORIENTATION_STR.get(v, "unknown")
        add_param(SPI_GETFONTSMOOTHINGORIENTATION, "orientation", orientation)
        def smoothing_type(v):
            return FE_FONTSMOOTHING_STR.get(v & FE_FONTSMOOTHINGCLEARTYPE, "unknown")
        add_param(SPI_GETFONTSMOOTHINGTYPE, "type", smoothing_type)
        add_param(SPI_GETFONTSMOOTHINGTYPE, "hinting", lambda v : bool(v & 0x2))
    except Exception as e:
        log.warn("failed to query antialias info: %s", e)
    return info

def get_workarea():
    #this is for x11 servers which can only use a single workarea,
    #calculate the total area:
    try:
        #first we need to find the absolute top-left and bottom-right corners
        #so we can make everything relative to 0,0
        monitors = []
        for m in win32api.EnumDisplayMonitors(None, None):
            mi = win32api.GetMonitorInfo(m[0])
            mx1, my1, mx2, my2 = mi['Monitor']
            monitors.append((mx1, my1, mx2, my2))
        minmx = min(x[0] for x in monitors)
        minmy = min(x[1] for x in monitors)
        maxmx = max(x[2] for x in monitors)
        maxmy = max(x[3] for x in monitors)
        screenlog("get_workarea() absolute total monitor dimensions: %s", (maxmx, maxmy))
        workareas = []
        for m in win32api.EnumDisplayMonitors(None, None):
            mi = win32api.GetMonitorInfo(m[0])
            #absolute workarea / monitor coordinates:
            wx1, wy1, wx2, wy2 = mi['Work']
            workareas.append((wx1, wy1, wx2, wy2))
        assert len(workareas)>0
        minwx = min(w[0] for w in workareas)
        minwy = min(w[1] for w in workareas)
        maxwx = max(w[2] for w in workareas)
        maxwy = max(w[3] for w in workareas)
        #sanity checks:
        assert minwx>=minmx and minwy>=minmy and maxwx<=maxmx and maxwy<=maxmy, "workspace %s is outside monitor space %s" % ((minwx, minwy, maxwx, maxwy), (minmx, minmy, maxmx, maxmy))
        #now make it relative to the monitor space:
        wx1 = minwx - minmx
        wy1 = minwy - minmy
        wx2 = maxwx - minmx
        wy2 = maxwy - minmy
        assert wx1<wx2 and wy1<wy2, "invalid workarea coordinates: %s" % (wx1, wy1, wx2, wy2)
        return wx1, wy1, wx2-wx1, wy2-wy1
    except Exception as e:
        screenlog.warn("failed to query workareas: %s", e)
        return []

#ie: for a 60 pixel bottom bar on the second monitor at 1280x800:
# [(0,0,1920,1080), (0,0,1280,740)]
def get_workareas():
    try:
        workareas = []
        for m in win32api.EnumDisplayMonitors(None, None):
            mi = win32api.GetMonitorInfo(m[0])
            screenlog("get_workareas() GetMonitorInfo(%s)=%s", m[0], mi)
            #absolute workarea / monitor coordinates:
            wx1, wy1, wx2, wy2 = mi['Work']
            mx1, my1, mx2, my2 = mi['Monitor']
            assert mx1<mx2 and my1<my2, "invalid monitor coordinates"
            #clamp to monitor, and make it all relative to monitor:
            rx1 = max(0, min(mx2-mx1, wx1-mx1))
            ry1 = max(0, min(my2-my1, wy1-my1))
            rx2 = max(0, min(mx2-mx1, wx2-mx1))
            ry2 = max(0, min(my2-my1, wy2-my1))
            assert rx1<rx2 and ry1<ry2, "invalid relative workarea coordinates"
            workareas.append((rx1, ry1, rx2-rx1, ry2-ry1))
        assert len(workareas)>0
        screenlog("get_workareas()=%s", workareas)
        return workareas
    except Exception as e:
        screenlog.warn("failed to query workareas: %s", e)
        return []

def _get_device_caps(constant):
    dc = None
    try:
        gdi32 = ctypes.windll.gdi32
        dc = win32gui.GetDC(None)
        return gdi32.GetDeviceCaps(dc, constant)
    finally:
        if dc:
            win32gui.ReleaseDC(None, dc)

def get_vrefresh():
    try:
        v = _get_device_caps(win32con.VREFRESH)
        screenlog("get_vrefresh()=%s", v)
        return v
    except Exception as e:
        log.warn("failed to get VREFRESH: %s", e)
        return -1

def get_double_click_time():
    try:
        return win32gui.GetDoubleClickTime()
    except Exception as e:
        log.warn("failed to get double click time: %s", e)
        return 0

def get_double_click_distance():
    try:
        return win32api.GetSystemMetrics(win32con.SM_CXDOUBLECLK), win32api.GetSystemMetrics(win32con.SM_CYDOUBLECLK)
    except Exception as e:
        log.warn("failed to get double click distance: %s", e)
        return -1, -1

def get_fixed_cursor_size():
    try:
        w = win32api.GetSystemMetrics(win32con.SM_CXCURSOR)
        h = win32api.GetSystemMetrics(win32con.SM_CYCURSOR)
        return w, h
    except Exception as e:
        log.warn("failed to get window frame size information: %s", e)
        #best to try to use a limit anyway:
        return 32, 32

def get_window_frame_sizes():
    try:
        #normal resizable windows:
        rx = win32api.GetSystemMetrics(win32con.SM_CXSIZEFRAME)
        ry = win32api.GetSystemMetrics(win32con.SM_CYSIZEFRAME)
        #non-resizable windows:
        fx = win32api.GetSystemMetrics(win32con.SM_CXFIXEDFRAME)
        fy = win32api.GetSystemMetrics(win32con.SM_CYFIXEDFRAME)
        #min size:
        mx = win32api.GetSystemMetrics(win32con.SM_CXMIN)
        my = win32api.GetSystemMetrics(win32con.SM_CYMIN)
        #size of menu bar:
        m = win32api.GetSystemMetrics(win32con.SM_CYMENU)
        #border:
        b = win32api.GetSystemMetrics(win32con.SM_CYBORDER)
        #caption:
        c = win32api.GetSystemMetrics(win32con.SM_CYCAPTION)
        return {
                "normal"    : (rx, ry),
                "fixed"     : (fx, fy),
                "minimum"   : (mx, my),
                "menu-bar"  : m,
                "border"    : b,
                "caption"   : c,
                }
    except Exception as e:
        log.warn("failed to get window frame size information: %s", e)
        return None

def show_desktop(b):
    #not defined in win32con..
    MIN_ALL         = 419
    MIN_ALL_UNDO    = 416
    if bool(b):
        v = MIN_ALL
    else:
        v = MIN_ALL_UNDO
    try:
        root = win32gui.FindWindow("Shell_TrayWnd", None)
        assert root is not None, "cannot find 'Shell_TrayWnd'"
        win32api.SendMessage(root, win32con.WM_COMMAND, v, 0)
    except Exception as e:
        log.warn("failed to call show_desktop(%s): %s", b, e)


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
        c = self.client
        if event==win32con.CTRL_C_EVENT:
            if c:
                c.signal_disconnect_and_quit(0, "CTRL_C")
            return 1
        if event==win32con.CTRL_CLOSE_EVENT:
            if c:
                c.signal_disconnect_and_quit(0, "CTRL_CLOSE")
            return 1
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
