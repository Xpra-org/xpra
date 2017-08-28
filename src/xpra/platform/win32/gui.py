# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32 -- the parts that may import gtk.

import sys
import types
import ctypes

from xpra.log import Logger
log = Logger("win32")
grablog = Logger("win32", "grab")
screenlog = Logger("win32", "screen")
keylog = Logger("win32", "keyboard")
mouselog = Logger("win32", "mouse")

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.window_hooks import Win32Hooks
from xpra.platform.win32.common import (GetSystemMetrics, SetWindowLongW, GetWindowLongW,
                                        ClipCursor, GetCursorPos,
                                        GetDC, ReleaseDC,
                                        SendMessageA, GetMessageA, TranslateMessage, DispatchMessageA,
                                        FindWindowA,
                                        GetModuleHandleA,
                                        GetKeyState, GetWindowRect,
                                        GetDoubleClickTime,
                                        MonitorFromWindow, GetMonitorInfoW, EnumDisplayMonitors,
                                        UnhookWindowsHookEx, CallNextHookEx, SetWindowsHookExA,
                                        SetConsoleCtrlHandler,
                                        GetDeviceCaps,
                                        user32)
from xpra.util import AdHocStruct, csv, envint, envbool
from xpra.os_util import PYTHON2

CONSOLE_EVENT_LISTENER = envbool("XPRA_CONSOLE_EVENT_LISTENER", True)
USE_NATIVE_TRAY = envbool("XPRA_USE_NATIVE_TRAY", True)


from ctypes import WinDLL, CFUNCTYPE, c_int, POINTER, Structure, byref, sizeof
from ctypes.wintypes import HWND, DWORD, WPARAM, LPARAM, MSG, WCHAR, POINT, RECT

shell32 = WinDLL("shell32", use_last_error=True)
try:
    from xpra.platform.win32.propsys import set_window_group    #@UnresolvedImport
except:
    #try using pywin32 for "Legacy" builds:
    try:
        from win32com.propsys import propsys    #@UnresolvedImport
        def set_window_group(hwnd, lhandle):
            try:
                ps = propsys.SHGetPropertyStoreForWindow(hwnd)
                key = propsys.PSGetPropertyKeyFromName("System.AppUserModel.ID")
                value = propsys.PROPVARIANTType(lhandle)
                log("win32 hooks: calling %s(%s, %s)", ps.SetValue, key, value)
                ps.SetValue(key, value)
            except Exception as e:
                log("set_window_group(%s, %s)", hwnd, lhandle, exc_info=True)
                log.error("Error: failed to set group leader '%s':", lhandle)
                log.error(" %s", e)
        log.info("using legacy propsys function for window grouping")
    except ImportError as e:
        log("propsys missing", exc_info=True)
        log.warn("Warning: propsys support missing, window grouping is not available:")
        log.warn(" %s", e)
        set_window_group = None


try:
    dwmapi = WinDLL("dwmapi", use_last_error=True)
    DwmGetWindowAttribute = dwmapi.DwmGetWindowAttribute
except:
    #win XP:
    DwmGetWindowAttribute = None

CCHDEVICENAME = 32
class MONITORINFOEX(ctypes.Structure):
    _fields_ = [('cbSize', DWORD),
                ('rcMonitor', RECT),
                ('rcWork', RECT),
                ('dwFlags', DWORD),
                ('szDevice', WCHAR * CCHDEVICENAME)]
MONITORINFOEX_size = ctypes.sizeof(MONITORINFOEX)
def GetMonitorInfo(hmonitor):
    info = MONITORINFOEX()
    info.szDevice = ""
    info.cbSize = MONITORINFOEX_size
    if not GetMonitorInfoW(hmonitor, byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    monitor = info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom
    work = info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom
    return  {
        "Work"      : work,
        "Monitor"   : monitor,
        "Flags"     : info.dwFlags,
        "Device"    : info.szDevice or "",
        }

WINDOW_HOOKS = envbool("XPRA_WIN32_WINDOW_HOOKS", True)
GROUP_LEADER = WINDOW_HOOKS and envbool("XPRA_WIN32_GROUP_LEADER", True)
UNDECORATED_STYLE = WINDOW_HOOKS and envbool("XPRA_WIN32_UNDECORATED_STYLE", True)
CLIP_CURSOR = WINDOW_HOOKS and envbool("XPRA_WIN32_CLIP_CURSOR", True)
#GTK3 is fixed, so we don't need this hook:
DEFAULT_MAX_SIZE_HINT = PYTHON2
MAX_SIZE_HINT = WINDOW_HOOKS and envbool("XPRA_WIN32_MAX_SIZE_HINT", DEFAULT_MAX_SIZE_HINT)
GEOMETRY = WINDOW_HOOKS and envbool("XPRA_WIN32_GEOMETRY", True)
LANGCHANGE = WINDOW_HOOKS and envbool("XPRA_WIN32_LANGCHANGE", True)

DPI_AWARE = envbool("XPRA_DPI_AWARE", True)
DPI_AWARENESS = envint("XPRA_DPI_AWARENESS", 1)
FORWARD_WINDOWS_KEY = envbool("XPRA_FORWARD_WINDOWS_KEY", True)
WHEEL = envbool("XPRA_WHEEL", True)
WHEEL_DELTA = envint("XPRA_WIN32_WHEEL_DELTA", 120)
assert WHEEL_DELTA>0

log("win32 gui settings: CONSOLE_EVENT_LISTENER=%s, USE_NATIVE_TRAY=%s, WINDOW_HOOKS=%s, GROUP_LEADER=%s, UNDECORATED_STYLE=%s, CLIP_CURSOR=%s, MAX_SIZE_HINT=%s, GEOMETRY=%s, LANGCHANGE=%s, DPI_AWARE=%s, DPI_AWARENESS=%s, FORWARD_WINDOWS_KEY=%s, WHEEL=%s, WHEEL_DELTA=%s",
    CONSOLE_EVENT_LISTENER, USE_NATIVE_TRAY, WINDOW_HOOKS, GROUP_LEADER, UNDECORATED_STYLE, CLIP_CURSOR, MAX_SIZE_HINT, GEOMETRY, LANGCHANGE, DPI_AWARE, DPI_AWARENESS, FORWARD_WINDOWS_KEY, WHEEL, WHEEL_DELTA)


KNOWN_EVENTS = {}
POWER_EVENTS = {}
for x in dir(win32con):
    if x.endswith("_EVENT"):
        v = getattr(win32con, x)
        KNOWN_EVENTS[v] = x
    if x.startswith("PBT_"):
        v = getattr(win32con, x)
        POWER_EVENTS[v] = x


def do_init():
    init_dpi()

def init_dpi():
    #tell win32 we handle dpi
    if not DPI_AWARE:
        screenlog.warn("SetProcessDPIAware not set due to environment override")
        return
    try:
        SetProcessDPIAware = user32.SetProcessDPIAware
        dpiaware = SetProcessDPIAware()
        screenlog("SetProcessDPIAware: %s()=%s", SetProcessDPIAware, dpiaware)
        assert dpiaware!=0
    except Exception as e:
        screenlog.warn("SetProcessDPIAware() failed: %s", e)
    if DPI_AWARENESS<=0:
        screenlog.warn("SetProcessDPIAwareness not set due to environment override")
        return
    try:
        Process_System_DPI_Aware        = 1
        Process_DPI_Unaware             = 0
        Process_Per_Monitor_DPI_Aware   = 2
        assert DPI_AWARENESS in (Process_System_DPI_Aware, Process_DPI_Unaware, Process_Per_Monitor_DPI_Aware)
        SetProcessDpiAwarenessInternal = user32.SetProcessDpiAwarenessInternal
        dpiawareness = SetProcessDpiAwarenessInternal(DPI_AWARENESS)
        screenlog("SetProcessDPIAwareness: %s(%s)=%s", SetProcessDpiAwarenessInternal, DPI_AWARENESS, dpiawareness)
        assert dpiawareness==0
    except Exception as e:
        screenlog("SetProcessDpiAwarenessInternal(%s) failed: %s", DPI_AWARENESS, e)
        screenlog(" (not available on MS Windows before version 8.1)")


def get_native_notifier_classes():
    try:
        from xpra.platform.win32.win32_notifier import Win32_Notifier
        return [Win32_Notifier]
    except ImportError as e:
        log("no native notifier", exc_info=True)
        log.warn("Warning: cannot load native win32 notifier")
        log.warn(" %s", e)
    return []

def get_native_tray_classes():
    c = []
    if USE_NATIVE_TRAY:
        try:
            from xpra.platform.win32.win32_tray import Win32Tray
            c.append(Win32Tray)
        except ImportError as e:
            log("no native tray", exc_info=True)
            log.warn("Warning: cannot load native win32 tray")
            log.warn(" %s", e)
    return c

def get_native_system_tray_classes(*_args):
    #Win32Tray cannot set the icon from data
    #so it cannot be used for application trays
    return get_native_tray_classes()

def gl_check():
    #This is supposed to help py2exe
    #(must be done after we setup the sys.path in platform.win32.paths):
    from OpenGL.platform import win32   #@UnresolvedImport @UnusedImport
    from xpra.platform.win32 import is_wine
    if is_wine():
        return "disabled when running under wine"
    return None


def get_monitor_workarea_for_window(handle):
    try:
        monitor = MonitorFromWindow(handle, win32con.MONITOR_DEFAULTTONEAREST)
        mi = GetMonitorInfo(monitor)
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


def get_window_handle(window):
    """ returns the win32 hwnd from a gtk.Window or gdk.Window """
    gdk_window = window
    try:
        gdk_window = window.get_window()
    except:
        pass
    try:
        return gdk_window.handle
    except:
        return None


def get_session_type():
    try:
        b = ctypes.c_bool()
        retcode = dwmapi.DwmIsCompositionEnabled(ctypes.byref(b))
        log("get_session_type() DwmIsCompositionEnabled()=%s (retcode=%s)", b.value, retcode)
        if retcode==0 and b.value:
            return "aero"
    except (AttributeError, WindowsError):      #@UndefinedVariable
        # No windll, no dwmapi or no DwmIsCompositionEnabled function.
        log("get_session_type() failed to query DwmIsCompositionEnabled", exc_info=True)
    return ""
#alternative code:
#    try:
#        # Vista & 7 stuff
#        hwnd = GetDesktopWindow()
#        DwmGetWindowAttribute = dwmapi.DwmGetWindowAttribute
#        DWMWA_NCRENDERING_ENABLED = 1
#        b = BOOL()
#        DwmGetWindowAttribute(HWND(hwnd), DWORD(DWMWA_NCRENDERING_ENABLED), byref(b), sizeof(b))
#        #wx1,wy1,wx2,wy2 = rect.left, rect.top, rect.right, rect.bottom
#        log("DwmGetWindowAttribute: DWMWA_NCRENDERING_ENABLED(%i)=%s", hwnd, b)
#        if b:
#            return "aero"
#    except WindowsError as e:           #@UndefinedVariable
#        log("no DwmGetWindowAttribute: %s", e)
#    return ""


def win32_propsys_set_group_leader(self, leader):
    """ implements set group leader using propsys """
    hwnd = get_window_handle(self)
    if not hwnd:
        return
    try:
        log("win32_propsys_set_group_leader(%s)", leader)
        lhandle = leader.handle
    except:
        log.warn("Warning: no window handle for %s", leader)
        log.warn(" cannot set window grouping attribute")
        return
    if not lhandle:
        return
    try:
        log("win32 hooks: get_window_handle(%s)=%s, set_group(%#x)", self, hwnd, lhandle)
        set_window_group(hwnd, lhandle)
    except Exception as e:
        log("set_window_group error", exc_info=True)
        log.error("Error: failed to set group leader")
        log.error(" %s", e)

WS_NAMES = {
            win32con.WS_BORDER              : "BORDER",
            win32con.WS_CAPTION             : "CAPTION",
            win32con.WS_CHILD               : "CHILD",
            win32con.WS_CHILDWINDOW         : "CHILDWINDOW",
            win32con.WS_CLIPCHILDREN        : "CLIPCHILDREN",
            win32con.WS_CLIPSIBLINGS        : "CLIPSIBLINGS",
            win32con.WS_DISABLED            : "DISABLED",
            win32con.WS_DLGFRAME            : "DLGFRAME",
            win32con.WS_GROUP               : "GROUP",
            win32con.WS_HSCROLL             : "HSCROLL",
            win32con.WS_ICONIC              : "ICONIC",
            win32con.WS_MAXIMIZE            : "MAXIMIZE",
            win32con.WS_MAXIMIZEBOX         : "MAXIMIZEBOX",
            win32con.WS_MINIMIZE            : "MINIMIZE",
            win32con.WS_MINIMIZEBOX         : "MINIMIZEBOX",
            win32con.WS_OVERLAPPED          : "OVERLAPPED",
            win32con.WS_POPUP               : "POPUP",
            win32con.WS_SIZEBOX             : "SIZEBOX",
            win32con.WS_SYSMENU             : "SYSMENU",
            win32con.WS_TABSTOP             : "TABSTOP",
            win32con.WS_THICKFRAME          : "THICKFRAME",
            win32con.WS_TILED               : "TILED",
            win32con.WS_VISIBLE             : "VISIBLE",
            win32con.WS_VSCROLL             : "VSCROLL",
            }

def style_str(style):
    return csv([s for c,s in WS_NAMES.items() if (c & style)==c])

def pointer_grab(window, *args):
    hwnd = get_window_handle(window)
    grablog("pointer_grab%s window=%s, hwnd=%s", args, window, hwnd)
    if not hwnd:
        window._client.pointer_grabbed = False
        return
    wrect = RECT()
    GetWindowRect(hwnd, byref(wrect))
    grablog("GetWindowRect(%i)=%s", hwnd, wrect)
    if DwmGetWindowAttribute:
        # Vista & 7 stuff
        rect = RECT()
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        DwmGetWindowAttribute(HWND(hwnd), DWORD(DWMWA_EXTENDED_FRAME_BOUNDS), byref(rect), sizeof(rect))
        #wx1,wy1,wx2,wy2 = rect.left, rect.top, rect.right, rect.bottom
        grablog("DwmGetWindowAttribute: DWMWA_EXTENDED_FRAME_BOUNDS(%i)=%s", hwnd, (rect.left, rect.top, rect.right, rect.bottom))
    bx = GetSystemMetrics(win32con.SM_CXSIZEFRAME)
    by = GetSystemMetrics(win32con.SM_CYSIZEFRAME)
    top = by
    style = GetWindowLongW(hwnd, win32con.GWL_STYLE)
    if style & win32con.WS_CAPTION:
        top += GetSystemMetrics(win32con.SM_CYCAPTION)
    grablog(" window style=%s, SIZEFRAME=%s, top=%i", style_str(style), (bx, by), top)
    clip = RECT(wrect.left+bx, wrect.top+top, wrect.right-bx, wrect.bottom-by)
    grablog("ClipCursor(%s)", clip)
    ClipCursor(clip)
    window._client.pointer_grabbed = True

def pointer_ungrab(window, *args):
    hwnd = get_window_handle(window)
    grablog("pointer_ungrab%s window=%s, hwnd=%s", args, window, hwnd)
    if hwnd:
        grablog("ClipCursor(None)")
        ClipCursor(None)
    window._client.pointer_grabbed = False

def fixup_window_style(self, *_args):
    """ a fixup function we want to call from other places """
    hwnd = get_window_handle(self)
    if not hwnd:
        return
    try:
        #warning: accessing "_metadata" on the client window class is fugly..
        metadata = getattr(self, "_metadata", {})
        if metadata.get("modal", False):
            #window is not / no longer meant to be decorated
            #(this is what GTK does for modal windows - keep it consistent)
            return
        cur_style = GetWindowLongW(hwnd, win32con.GWL_STYLE)
        #re-add taskbar menu:
        style = cur_style
        if cur_style & win32con.WS_CAPTION:
            style |= win32con.WS_SYSMENU
            style |= win32con.WS_MAXIMIZEBOX
            style |= win32con.WS_MINIMIZEBOX
        #we can't enable this because GTK would then get confused
        #and paint the window contents at the wrong offset
        if False:
            hints = metadata.get("size-constraints")
            if hints:
                minw, minh = hints.get("minimum-size", (0, 0))
                maxw, maxh = hints.get("maximum-size", (0, 0))
                if minw>0 and minw==maxw and minh>0 and minh==maxh:
                    #not resizable
                    style &= ~win32con.WS_MAXIMIZEBOX
                    style &= ~win32con.WS_SIZEBOX
        if style!=cur_style:
            log("fixup_window_style() using %s (%#x) instead of %s (%#x) on window %#x with metadata=%s", style_str(style), style, style_str(cur_style), cur_style, hwnd, metadata)
            SetWindowLongW(hwnd, win32con.GWL_STYLE, style)
        else:
            log("fixup_window_style() unchanged style %s (%#x) on window %#x", style_str(style), style, hwnd)
    except:
        log.warn("failed to fixup window style", exc_info=True)

def set_decorated(self, decorated):
    """ override method which ensures that we call
        fixup_window_style whenever decorations are toggled """
    self.__set_decorated(decorated)         #call the original saved method
    self.fixup_window_style()

def window_state_updated(window):
    """ fixup_window_style whenever the window state changes """
    log("window_state_updated(%s)", window)
    fixup_window_style(window)

def apply_maxsize_hints(window, hints):
    """ extracts the max-size hints from the hints,
        and passes it to the win32hooks class which can implement it
        (as GTK2 does not honour it properly on win32)
    """
    workw, workh = 0, 0
    handle = get_window_handle(window)
    log("apply_maxsize_hints(%s, %s) handle=%s", window, hints, handle)
    if not window.get_decorated():
        workarea = get_monitor_workarea_for_window(handle)
        log("using workarea as window size limit for undecorated window: %s", workarea)
        if workarea:
            workw, workh = workarea[2:4]
    minw = hints.get("min_width", 0)
    minh = hints.get("min_width", 0)
    maxw = hints.get("max_width", 0)
    maxh = hints.get("max_height", 0)
    if workw>0 and workh>0:
        #clamp to workspace for undecorated windows:
        if maxw>0 and maxh>0:
            maxw = min(workw, maxw)
            maxh = min(workh, maxh)
        else:
            maxw, maxh = workw, workh
    log("apply_maxsize_hints(%s, %s) found min: %sx%s, max: %sx%s", window, hints, minw, minh, maxw, maxh)
    if (maxw>0 and maxw<32767) or (maxh>0 and maxh<32767):
        window.win32hooks.max_size = (maxw or 32000), (maxh or 32000)
    elif window.win32hooks.max_size:
        #was set, clear it
        window.win32hooks.max_size = None
    if minw>0 or minh>0:
        window.win32hooks.min_size = minw, minh
    elif window.win32hooks.min_size:
        #was set, clear it:
        window.win32hooks.min_size = None
    if minw>0 and minw==maxw and minh>0 and minh==maxh:
        #fixed size, GTK can handle that
        return
    #remove them so GTK doesn't try to set attributes,
    #which would remove the maximize button:
    for x in ("min_width", "min_height", "max_width", "max_height"):
        if x in hints:
            del hints[x]
    window_state_updated(window)

def apply_geometry_hints(self, hints):
    log("apply_geometry_hints(%s)", hints)
    apply_maxsize_hints(self, hints)
    return self.__apply_geometry_hints(hints)   #call the original saved method

def cache_pointer_offset(self, event):
    #this overrides the window._get_pointer method
    #so we can cache the GTK position offset for synthetic wheel events
    gtk_x, gtk_y = event.x_root, event.y_root
    pos = POINT()
    GetCursorPos(ctypes.byref(pos))
    x, y = pos.x, pos.y
    self.win32_pointer_offset = gtk_x-x, gtk_y-y
    return gtk_x, gtk_y


def add_window_hooks(window):
    log("add_window_hooks(%s) WINDOW_HOOKS=%s, GROUP_LEADER=%s, UNDECORATED_STYLE=%s, MAX_SIZE_HINT=%s, GEOMETRY=%s",
            window, WINDOW_HOOKS, GROUP_LEADER, UNDECORATED_STYLE, MAX_SIZE_HINT, GEOMETRY)
    if not WINDOW_HOOKS:
        #allows us to disable the win32 hooks for testing
        return
    try:
        gdk_window = window.get_window()
        #win32 cannot use set_group by default:
        gdk_window.set_group = noop
    except:
        gdk_window = None
    #window handle:
    try:
        handle = gdk_window.handle
    except:
        handle = None
    if not handle:
        from xpra.gtk_common.gobject_compat import is_gtk3
        if is_gtk3():
            #access the missing gdk_win32_window_get_handle function using ctypes:
            try:
                ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
                ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object]
                gdkwin_gpointer = ctypes.pythonapi.PyCapsule_GetPointer(gdk_window.__gpointer__, None)
                gdkdll = ctypes.CDLL("libgdk-3-0.dll")
                handle = gdkdll.gdk_win32_window_get_handle(gdkwin_gpointer)
            except Exception as e:
                log("failed to get window handle", exc_info=True)
                log.error("Error: failed to access the window handle for %s", gdk_window)
                log.error(" %s", e)
    if not handle:
        log.warn("Warning: cannot add window hooks without a window handle!")
        return
    log("add_window_hooks(%s) gdk window=%s, hwnd=%#x", window, gdk_window, handle)

    if GROUP_LEADER:
        #windows 7 onwards can use AppUserModel to emulate the group leader stuff:
        log("win32 hooks: set_window_group=%s", set_window_group)
        if set_window_group:
            gdk_window.set_group = types.MethodType(win32_propsys_set_group_leader, gdk_window)
            log("hooked group leader override using %s", set_window_group)

    if UNDECORATED_STYLE:
        #OR windows never have any decorations or taskbar menu
        if not window._override_redirect:
            #the method to call to fix things up:
            window.fixup_window_style = types.MethodType(fixup_window_style, window)
            #override set_decorated so we can preserve the taskbar menu for undecorated windows
            window.__set_decorated = window.set_decorated
            window.set_decorated = types.MethodType(set_decorated, window)
            #override after_window_state_updated so we can re-add the missing style options
            #(somehow doing it from on_realize which calls add_window_hooks is not enough)
            window.connect("state-updated", window_state_updated)
            #call it at least once:
            window.fixup_window_style()

    if CLIP_CURSOR:
        window.pointer_grab = types.MethodType(pointer_grab, window)
        window.pointer_ungrab = types.MethodType(pointer_ungrab, window)

    if MAX_SIZE_HINT or LANGCHANGE or WHEEL:
        #glue code for gtk to win32 APIs:
        #add event hook class:
        win32hooks = Win32Hooks(handle)
        log("add_window_hooks(%s) added hooks for hwnd %#x: %s", window, handle, win32hooks)
        window.win32hooks = win32hooks
        win32hooks.max_size = None
        win32hooks.setup()

        if GEOMETRY:
            #save original geometry function:
            window.__apply_geometry_hints = window.apply_geometry_hints
            window.apply_geometry_hints = types.MethodType(apply_geometry_hints, window)
            #apply current max-size from hints, if any:
            if window.geometry_hints:
                apply_maxsize_hints(window, window.geometry_hints)

        if LANGCHANGE:
            def inputlangchange(_hwnd, _event, wParam, lParam):
                log("WM_INPUTLANGCHANGE: character set: %i, input locale identifier: %i", wParam, lParam)
                window.keyboard_layout_changed("WM_INPUTLANGCHANGE", wParam, lParam)
            win32hooks.add_window_event_handler(win32con.WM_INPUTLANGCHANGE, inputlangchange)

        if WHEEL:
            VERTICAL = "vertical"
            HORIZONTAL = "horizontal"
            def handle_wheel(orientation, wParam, lParam):
                distance = wParam>>16
                if distance>2**15:
                    #ie: 0xFF88 -> 0x78 (120)
                    distance = distance-2**16
                keys = wParam & 0xFFFF
                y = lParam>>16
                x = lParam & 0xFFFF
                units = float(distance) / WHEEL_DELTA
                client = getattr(window, "_client")
                wid = getattr(window, "_id", 0)
                mouselog("win32 mousewheel: orientation=%s, distance=%i, wheel-delta=%s, units=%.3f, new value=%.1f, keys=%#x, x=%i, y=%i, client=%s, wid=%i", orientation, distance, WHEEL_DELTA, units, distance, keys, x, y, client, wid)
                if client and wid>0:
                    if orientation==VERTICAL:
                        deltax = 0
                        deltay = units
                    else:
                        deltax = units
                        deltay = 0
                    client.wheel_event(wid, deltax, deltay)
            def mousewheel(_hwnd, _event, wParam, lParam):
                handle_wheel(VERTICAL, wParam, lParam)
                return 0
            def mousehwheel(_hwnd, _event, wParam, lParam):
                handle_wheel(HORIZONTAL, wParam, lParam)
                return 0
            WM_MOUSEHWHEEL = 0x020E
            win32hooks.add_window_event_handler(win32con.WM_MOUSEWHEEL, mousewheel)
            win32hooks.add_window_event_handler(WM_MOUSEHWHEEL, mousehwheel)


def remove_window_hooks(window):
    try:
        win32hooks = getattr(window, "win32hooks", None)
        if win32hooks:
            log("remove_window_hooks(%s) found %s", window, win32hooks)
            win32hooks.cleanup()
            window.win32hooks = None
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


def _add_SPI(info, constant, name, convert, default=None):
    SystemParametersInfo = user32.SystemParametersInfoA
    i = ctypes.c_uint32()
    if SystemParametersInfo(constant, 0, byref(i), 0):
        info[name] = convert(i.value)
    elif default is not None:
        info[name] = default

def get_antialias_info():
    info = {}
    try:
        _add_SPI(info, SPI_GETFONTSMOOTHING, "enabled", bool)
        #"Valid contrast values are from 1000 to 2200. The default value is 1400."
        _add_SPI(info, SPI_GETFONTSMOOTHINGCONTRAST, "contrast", int)
        def orientation(v):
            return FE_ORIENTATION_STR.get(v, "unknown")
        _add_SPI(info, SPI_GETFONTSMOOTHINGORIENTATION, "orientation", orientation)
        def smoothing_type(v):
            return FE_FONTSMOOTHING_STR.get(v & FE_FONTSMOOTHINGCLEARTYPE, "unknown")
        _add_SPI(info, SPI_GETFONTSMOOTHINGTYPE, "type", smoothing_type)
        _add_SPI(info, SPI_GETFONTSMOOTHINGTYPE, "hinting", lambda v : bool(v & 0x2))
    except Exception as e:
        log.warn("failed to query antialias info: %s", e)
    return info

def get_mouse_config():
    #not all are present in win32con?
    SM_CMOUSEBUTTONS = 43
    SM_CXDRAG = 68
    SM_CYDRAG = 69
    SM_MOUSEPRESENT = 19
    SM_MOUSEHORIZONTALWHEELPRESENT = 91
    SM_SWAPBUTTON = 23
    SM_MOUSEWHEELPRESENT = 75
    wheel_info = {
                  "vertical"   : GetSystemMetrics(SM_MOUSEWHEELPRESENT),
                  "horizontal" : GetSystemMetrics(SM_MOUSEHORIZONTALWHEELPRESENT),
                  }
    SPI_GETWHEELSCROLLLINES = 104
    SPI_GETWHEELSCROLLCHARS = 0x006C
    SPI_GETMOUSEVANISH = 4128
    #rate for each direction:
    _add_SPI(wheel_info, SPI_GETWHEELSCROLLLINES, "lines", int, 3)
    _add_SPI(wheel_info, SPI_GETWHEELSCROLLCHARS, "chars", int, 3)
    info = {
            "present"       : bool(GetSystemMetrics(SM_MOUSEPRESENT)),
            "wheel"         : wheel_info,
            "buttons"       : GetSystemMetrics(SM_CMOUSEBUTTONS),
            "swap"          : bool(GetSystemMetrics(SM_SWAPBUTTON)),
            "drag"          : {
                               "x"  : GetSystemMetrics(SM_CXDRAG),
                               "y"  : GetSystemMetrics(SM_CYDRAG),
                               }
            }
    _add_SPI(info, SPI_GETMOUSEVANISH, "vanish", bool, False)
    return info


def get_workarea():
    #this is for x11 servers which can only use a single workarea,
    #calculate the total area:
    try:
        #first we need to find the absolute top-left and bottom-right corners
        #so we can make everything relative to 0,0
        monitors = []
        for m in EnumDisplayMonitors():
            mi = GetMonitorInfo(m)
            mx1, my1, mx2, my2 = mi['Monitor']
            monitors.append((mx1, my1, mx2, my2))
        minmx = min(x[0] for x in monitors)
        minmy = min(x[1] for x in monitors)
        maxmx = max(x[2] for x in monitors)
        maxmy = max(x[3] for x in monitors)
        screenlog("get_workarea() absolute total monitor area: %s", (minmx, minmy, maxmx, maxmy))
        screenlog(" total monitor dimensions: %s", (maxmx-minmx, maxmy-minmy))
        workareas = []
        for m in EnumDisplayMonitors():
            mi = GetMonitorInfo(m)
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
MONITORINFOF_PRIMARY = 1
def get_workareas():
    try:
        workareas = []
        for m in EnumDisplayMonitors():
            mi = GetMonitorInfo(m)
            screenlog("get_workareas() GetMonitorInfo(%s)=%s", m, mi)
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
            geom = rx1, ry1, rx2-rx1, ry2-ry1
            #GTK will return the PRIMARY monitor first,
            #so we have to do the same thing:
            if mi['Flags'] & MONITORINFOF_PRIMARY:
                workareas.insert(0, geom)
            else:
                workareas.append(geom)
        assert len(workareas)>0
        screenlog("get_workareas()=%s", workareas)
        return workareas
    except Exception as e:
        screenlog.warn("failed to query workareas: %s", e)
        return []

def _get_device_caps(constant):
    dc = None
    try:
        dc = GetDC(None)
        return GetDeviceCaps(dc, constant)
    finally:
        if dc:
            ReleaseDC(None, dc)

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
        return GetDoubleClickTime()
    except Exception as e:
        log.warn("failed to get double click time: %s", e)
        return 0

def get_double_click_distance():
    try:
        return GetSystemMetrics(win32con.SM_CXDOUBLECLK), GetSystemMetrics(win32con.SM_CYDOUBLECLK)
    except Exception as e:
        log.warn("failed to get double click distance: %s", e)
        return -1, -1

def get_fixed_cursor_size():
    try:
        w = GetSystemMetrics(win32con.SM_CXCURSOR)
        h = GetSystemMetrics(win32con.SM_CYCURSOR)
        return w, h
    except Exception as e:
        log.warn("failed to get window frame size information: %s", e)
        #best to try to use a limit anyway:
        return 32, 32

def get_cursor_size():
    w,h = get_fixed_cursor_size()
    return (w+h)//2


def get_window_frame_sizes():
    try:
        #normal resizable windows:
        rx = GetSystemMetrics(win32con.SM_CXSIZEFRAME)
        ry = GetSystemMetrics(win32con.SM_CYSIZEFRAME)
        #non-resizable windows:
        fx = GetSystemMetrics(win32con.SM_CXFIXEDFRAME)
        fy = GetSystemMetrics(win32con.SM_CYFIXEDFRAME)
        #min size:
        mx = GetSystemMetrics(win32con.SM_CXMIN)
        my = GetSystemMetrics(win32con.SM_CYMIN)
        #size of menu bar:
        m = GetSystemMetrics(win32con.SM_CYMENU)
        #border:
        b = GetSystemMetrics(win32con.SM_CYBORDER)
        #caption:
        c = GetSystemMetrics(win32con.SM_CYCAPTION)
        return {
                "normal"    : (rx, ry),
                "fixed"     : (fx, fy),
                "minimum"   : (mx, my),
                "menu-bar"  : m,
                "border"    : b,
                "caption"   : c,
                "offset"    : (rx, ry+c),
                #left, right, top, bottom:
                "frame"     : (rx, rx, ry+c, ry),
                }
    except Exception as e:
        log.warn("failed to get window frame size information: %s", e)
        return None

def get_virtualscreenmetrics():
    dx = GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    dy = GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    dw = GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    dh = GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    return dx, dy, dw, dh

def take_screenshot():
    #would be better to refactor the code..
    from xpra.platform.win32.gdi_screen_capture import GDICapture
    gdic = GDICapture()
    v = gdic.take_screenshot()
    gdic.cleanup()
    return v


def show_desktop(b):
    #not defined in win32con..
    MIN_ALL         = 419
    MIN_ALL_UNDO    = 416
    if bool(b):
        v = MIN_ALL
    else:
        v = MIN_ALL_UNDO
    try:
        root = FindWindowA("Shell_TrayWnd", None)
        assert root is not None, "cannot find 'Shell_TrayWnd'"
        SendMessageA(root, win32con.WM_COMMAND, v, 0)
    except Exception as e:
        log.warn("failed to call show_desktop(%s): %s", b, e)


WM_WTSSESSION_CHANGE = 0x02b1
WTS_CONSOLE_CONNECT         = 0x1
WTS_CONSOLE_DISCONNECT      = 0x2
WTS_REMOTE_CONNECT          = 0x3
WTS_REMOTE_DISCONNECT       = 0x4
WTS_SESSION_LOGON           = 0x5
WTS_SESSION_LOGOFF          = 0x6
WTS_SESSION_LOCK            = 0x7
WTS_SESSION_UNLOCK          = 0x8
WTS_SESSION_REMOTE_CONTROL  = 0x9
WTS_SESSION_EVENTS = {
                      WTS_CONSOLE_CONNECT       : "CONSOLE CONNECT",
                      WTS_CONSOLE_DISCONNECT    : "CONSOLE_DISCONNECT",
                      WTS_REMOTE_CONNECT        : "REMOTE_CONNECT",
                      WTS_REMOTE_DISCONNECT     : "REMOTE_DISCONNECT",
                      WTS_SESSION_LOGON         : "SESSION_LOGON",
                      WTS_SESSION_LOGOFF        : "SESSION_LOGOFF",
                      WTS_SESSION_LOCK          : "SESSION_LOCK",
                      WTS_SESSION_UNLOCK        : "SESSION_UNLOCK",
                      WTS_SESSION_REMOTE_CONTROL: "SESSION_REMOTE_CONTROL",
                      }

class ClientExtras(object):
    def __init__(self, client, opts):
        self.client = client
        self._kh_warning = False
        self._console_handler_added = False
        if CONSOLE_EVENT_LISTENER:
            self._console_handler_added = self.setup_console_event_listener(True)
        from xpra.platform.win32.win32_events import get_win32_event_listener
        try:
            el = get_win32_event_listener(True)
            self._el = el
            if el:
                el.add_event_callback(win32con.WM_ACTIVATEAPP,      self.activateapp)
                el.add_event_callback(win32con.WM_POWERBROADCAST,   self.power_broadcast_event)
                el.add_event_callback(win32con.WM_MOVE,             self.wm_move)
                el.add_event_callback(WM_WTSSESSION_CHANGE,         self.session_change_event)
                el.add_event_callback(win32con.WM_INPUTLANGCHANGE,  self.inputlangchange)
                el.add_event_callback(win32con.WM_WININICHANGE,     self.inichange)
        except Exception as e:
            log.error("cannot register focus and power callbacks: %s", e)
        self.keyboard_hook_id = None
        if FORWARD_WINDOWS_KEY:
            from xpra.make_thread import make_thread
            make_thread(self.init_keyboard_listener, "keyboard-listener", daemon=True).start()

    def ready(self):
        pass

    def cleanup(self):
        log("ClientExtras.cleanup()")
        cha = self._console_handler_added
        if cha:
            self._console_handler_added = False
            self.setup_console_event_listener(False)
        el = self._el
        if el:
            self._el = None
            el.cleanup()
        khid = self.keyboard_hook_id
        if khid:
            self.keyboard_hook_id = None
            UnhookWindowsHookEx(khid)
        log("ClientExtras.cleanup() ended")
        #self.client = None

    def init_keyboard_listener(self):
        class WindowsKeyEvent(AdHocStruct):
            pass
        class KBDLLHOOKSTRUCT(Structure):
            _fields_ = [("vk_code", DWORD),
                        ("scan_code", DWORD),
                        ("flags", DWORD),
                        ("time", c_int),]
        DOWN = [win32con.WM_KEYDOWN, win32con.WM_SYSKEYDOWN]
        #UP = [win32con.WM_KEYUP, win32con.WM_SYSKEYUP]
        ALL_KEY_EVENTS = {win32con.WM_KEYDOWN       : "KEYDOWN",
                          win32con.WM_SYSKEYDOWN    : "SYSKEYDOWN",
                          win32con.WM_KEYUP         : "KEYUP",
                          win32con.WM_SYSKEYUP      : "SYSKEYUP",
                          }
        def low_level_keyboard_handler(nCode, wParam, lParam):
            try:
                scan_code = lParam.contents.scan_code
                vk_code = lParam.contents.vk_code
                focused = self.client._focused
                #the keys we intercept before the OS:
                keyname = {
                           win32con.VK_LWIN   : "Super_L",
                           win32con.VK_RWIN   : "Super_R",
                           win32con.VK_TAB    : "Tab",
                           }.get(vk_code)
                modifiers = []
                kh = self.client.keyboard_helper
                key_event_type = ALL_KEY_EVENTS.get(wParam)
                #log("low_level_keyboard_handler(%s, %s, %s) vk_code=%i, scan_code=%i, keyname=%s, key_event_type=%s, focused=%s, keyboard_grabbed=%s", nCode, wParam, lParam, vk_code, scan_code, keyname, key_event_type, focused, self.client.keyboard_grabbed)
                if self.client.keyboard_grabbed and focused and keyname and kh and kh.keyboard and key_event_type:
                    modifier_keycodes = kh.keyboard.modifier_keycodes
                    modifier_keys = kh.keyboard.modifier_keys
                    if keyname.startswith("Super"):
                        keycode = 0
                        #find the modifier keycode: (try the exact key we hit first)
                        for x in [keyname, "Super_L", "Super_R"]:
                            keycodes = modifier_keycodes.get(x, [])
                            for k in keycodes:
                                #only interested in numeric keycodes:
                                try:
                                    keycode = int(k)
                                    break
                                except:
                                    pass
                            if keycode>0:
                                break
                    else:
                        keycode = vk_code           #true for non-modifier keys only!
                    for vk, modkeynames in {
                                        win32con.VK_NUMLOCK     : ["Num_Lock"],
                                        win32con.VK_CAPITAL     : ["Caps_Lock"],
                                        win32con.VK_CONTROL     : ["Control_L", "Control_R"],
                                        win32con.VK_SHIFT       : ["Shift_L", "Shift_R"],
                                        }.items():
                        if GetKeyState(vk):
                            for modkeyname in modkeynames:
                                mod = modifier_keys.get(modkeyname)
                                if mod:
                                    modifiers.append(mod)
                                    break
                    #keylog.info("keyboard helper=%s, modifier keycodes=%s", kh, modifier_keycodes)
                    grablog("vk_code=%s, scan_code=%s, event=%s, keyname=%s, keycode=%s, modifiers=%s, focused=%s", vk_code, scan_code, ALL_KEY_EVENTS.get(wParam), keyname, keycode, modifiers, focused)
                    if keycode>0:
                        key_event = WindowsKeyEvent()
                        key_event.keyname = keyname
                        key_event.pressed = wParam in DOWN
                        key_event.modifiers = modifiers
                        key_event.keyval = scan_code
                        key_event.keycode = keycode
                        key_event.string = ""
                        key_event.group = 0
                        grablog("detected '%s' key, sending %s", keyname, key_event)
                        self.client.keyboard_helper.send_key_action(focused, key_event)
                        #swallow this event:
                        return 1
            except Exception as e:
                keylog.error("Error: low level keyboard hook failed")
                keylog.error(" %s", e)
            return CallNextHookEx(keyboard_hook_id, nCode, wParam, lParam)
        # Our low level handler signature.
        CMPFUNC = CFUNCTYPE(c_int, WPARAM, LPARAM, POINTER(KBDLLHOOKSTRUCT))
        # Convert the Python handler into C pointer.
        pointer = CMPFUNC(low_level_keyboard_handler)
        # Hook both key up and key down events for common keys (non-system).
        keyboard_hook_id = SetWindowsHookExA(win32con.WH_KEYBOARD_LL, pointer, GetModuleHandleA(None), 0)
        # Register to remove the hook when the interpreter exits:
        keylog("init_keyboard_listener() hook_id=%#x", keyboard_hook_id)
        msg = MSG()
        lpmsg = byref(msg)
        while True:
            ret = GetMessageA(lpmsg, None, 0, 0)
            keylog("init_keyboard_listener: GetMessage()=%s", ret)
            if ret==-1:
                raise ctypes.WinError(ctypes.get_last_error())
            elif ret==0:
                keylog("GetMessage()=0, exiting loop")
                return
            else:
                TranslateMessage(lpmsg)
                DispatchMessageA(lpmsg)


    def wm_move(self, wParam, lParam):
        c = self.client
        log("WM_MOVE: %s/%s client=%s", wParam, lParam, c)
        if c:
            #this is not really a screen size change event,
            #but we do want to process it as such (see window reinit code)
            c.screen_size_changed()

    def session_change_event(self, event, session):
        event_name = WTS_SESSION_EVENTS.get(event, event)
        log("WM_WTSSESSION_CHANGE: %s on session %#x", event_name, session)
        c = self.client
        if not c:
            return
        if event in (WTS_SESSION_LOGOFF, WTS_SESSION_LOCK):
            log("will freeze all the windows")
            c.freeze()
        elif event in (WTS_SESSION_LOGON, WTS_SESSION_UNLOCK):
            log("will unfreeze all the windows")
            #don't unfreeze directly from here,
            #as the system may not be fully usable yet (see #997)
            from xpra.gtk_common.gobject_compat import import_glib
            glib = import_glib()
            glib.idle_add(c.unfreeze)


    def inputlangchange(self, wParam, lParam):
        log("WM_INPUTLANGCHANGE: %i, %i", wParam, lParam)

    def inichange(self, wParam, lParam):
        if lParam:
            from ctypes import c_char_p
            log("WM_WININICHANGE: %#x=%s", lParam, c_char_p(lParam).value)
        else:
            log("WM_WININICHANGE: %i, %i", wParam, lParam)


    def activateapp(self, wParam, lParam):
        c = self.client
        log("WM_ACTIVATEAPP: %s/%s client=%s", wParam, lParam, c)
        if not c:
            return
        if wParam==0:
            #our app has lost focus
            c.update_focus(0, False)
        #workaround for windows losing their style:
        for window in c._id_to_window.values():
            fixup_window_style = getattr(window, "fixup_window_style", None)
            if fixup_window_style:
                fixup_window_style()


    def power_broadcast_event(self, wParam, lParam):
        c = self.client
        log("WM_POWERBROADCAST: %s/%s client=%s", POWER_EVENTS.get(wParam, wParam), lParam, c)
        #maybe also "PBT_APMQUERYSUSPEND" and "PBT_APMQUERYSTANDBY"?
        if wParam==win32con.PBT_APMSUSPEND and c:
            c.suspend()
        #According to the documentation:
        #The system always sends a PBT_APMRESUMEAUTOMATIC message whenever the system resumes.
        elif wParam==win32con.PBT_APMRESUMEAUTOMATIC and c:
            c.resume()

    def setup_console_event_listener(self, enable):
        try:
            log("calling SetConsoleCtrlHandler(%s)", enable)
            handler = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)(self.handle_console_event)
            result = SetConsoleCtrlHandler(handler, int(enable))
            log("SetConsoleCtrlHandler(%s, %s)=%s", handler, enable, result)
            if result==0 and enable:
                log.error("Error: could not set console control handler:")
                log.error(" SetConsoleCtrlHandler: %r", ctypes.GetLastError())
                return False
            return True
        except Exception as e:
            log.error("SetConsoleCtrlHandler error: %s", e)
            return False


    def handle_console_event(self, event):
        c = self.client
        event_name = KNOWN_EVENTS.get(event, event)
        log("handle_console_event(%s) client=%s, event_name=%s", event, c, event_name)
        info_events = [win32con.CTRL_C_EVENT,
                       win32con.CTRL_LOGOFF_EVENT,
                       win32con.CTRL_BREAK_EVENT,
                       win32con.CTRL_SHUTDOWN_EVENT,
                       win32con.CTRL_CLOSE_EVENT]
        if event in info_events:
            log.info("received console event %s", str(event_name).replace("_EVENT", ""))
        else:
            log.warn("unknown console event: %s", event_name)
        if event==win32con.CTRL_C_EVENT:
            if c:
                log("calling=%s", c.signal_disconnect_and_quit)
                c.signal_disconnect_and_quit(0, "CTRL_C")
                return 1
        if event==win32con.CTRL_CLOSE_EVENT:
            if c:
                c.signal_disconnect_and_quit(0, "CTRL_CLOSE")
                return 1
        return 0


def main():
    from collections import namedtuple
    from xpra.platform import program_context
    with program_context("Platform-Events", "Platform Events Test"):
        if "-v" in sys.argv or "--verbose" in sys.argv:
            from xpra.platform.win32.win32_events import log as win32_event_logger
            log.enable_debug()
            win32_event_logger.enable_debug()

        import gobject
        gobject.threads_init()      #@UndefinedVariable

        log.info("Event loop is running")
        loop = gobject.MainLoop()

        def suspend():
            log.info("suspend event")
        def resume():
            log.info("resume event")
        FakeClient = namedtuple("FakeClient", "_focused,keyboard_grabbed,window_with_grab,suspend,resume,keyboard_helper")
        fake_client = FakeClient(_focused=False, keyboard_grabbed=False, window_with_grab=None,
                                 suspend=suspend, resume=resume, keyboard_helper=None)
        def signal_quit(*_args):
            loop.quit()
        fake_client.signal_disconnect_and_quit = signal_quit
        ClientExtras(fake_client, None)

        try:
            loop.run()
        except KeyboardInterrupt:
            log.info("exiting on keyboard interrupt")


if __name__ == "__main__":
    main()
