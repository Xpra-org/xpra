#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from typing import Any
from collections.abc import MutableSequence, Callable
from ctypes.wintypes import HWND, BYTE, HICON, HDC
from ctypes import byref, sizeof, cast, c_wchar, c_void_p, WinError, get_last_error, POINTER

from xpra.client.gui.window.backing import fire_paint_callbacks
from xpra.client.win32.gdi_backing import GDIBacking
from xpra.os_util import gi_import
from xpra.platform.win32.wndproc_events import WNDPROC_EVENT_NAMES
from xpra.util.gobject import n_arg_signal, no_arg_signal
from xpra.util.objects import typedict
from xpra.platform.win32.constants import FLASHW_ALL, FLASHW_TIMERNOFG, FLASHW_STOP
from xpra.platform.win32.common import (
    GetModuleHandleA,
    WNDPROC, WNDCLASSEX, RegisterClassExW, UnregisterClassW,
    CreateWindowExW, DestroyWindow, DefWindowProcW,
    CreateCompatibleDC, DeleteDC,
    LoadCursor,
    ShowWindow, UpdateWindow,
    DestroyIcon, CREATESTRUCT,
    AdjustWindowRectEx, SetWindowPos, RECT, GetWindowLongW, SendMessageW,
    GetKeyboardState, ToUnicode, MapVirtualKeyW,
    SetWindowTextW,
    InvalidateRect,
    BeginPaint, EndPaint, PAINTSTRUCT,
    SetForegroundWindow, GetForegroundWindow,
    SetWindowLongA, GWLP_HWNDPARENT, SetWindowLongPtrValueW,
    MINMAXINFO, WINDOWPOS, FLASHWINFO, FlashWindowEx,
    MonitorFromWindow, GetMonitorInfo, EnumDisplayMonitors,
    CreateRectRgn, CombineRgn, RGN_OR, SetWindowRgn, DeleteObject,
)
from xpra.platform.win32.keyboard import VK_NAMES, VK_X11_MAP
from xpra.client.win32.common import WM_MESSAGES, to_signed_coordinate, get_xy_lparam, img_to_hicon
from xpra.log import Logger

log = Logger("client", "window")
iconlog = Logger("icon")
drawlog = Logger("draw")
geomlog = Logger("geometry")

GObject = gi_import("GObject")
GLib = gi_import("GLib")


ACTIVATION: dict[int, str] = {
    win32con.WA_ACTIVE: "active",
    win32con.WA_CLICKACTIVE: "clickactive",
    win32con.WA_INACTIVE: "inactive",
}
MOUSE_VK_MASK: dict[int, str] = {
    win32con.MK_CONTROL: "control",
    win32con.MK_SHIFT: "shift",
}
MK_XBUTTON1 = 0x0020
MK_XBUTTON2 = 0x0040
MOUSE_BUTTON_MASK: dict[int, int] = {
    win32con.MK_LBUTTON: 1,
    win32con.MK_MBUTTON: 2,
    win32con.MK_RBUTTON: 3,
    MK_XBUTTON1: 4,
    MK_XBUTTON2: 5,
}

BUTTON_MAP: dict[int, int] = {
    win32con.WM_LBUTTONDOWN: 1,
    win32con.WM_MBUTTONDOWN: 2,
    win32con.WM_RBUTTONDOWN: 3,
    win32con.WM_LBUTTONUP: 1,
    win32con.WM_MBUTTONUP: 2,
    win32con.WM_RBUTTONUP: 3,
}
WM_NCXBUTTONDOWN = 0x00AB
WM_NCXBUTTONUP = 0x00AC
WM_NCXBUTTONDBLCLK = 0x00AD
WM_MOUSEHWHEEL = 0x020E

DECORATION_STYLE = win32con.WS_CAPTION | win32con.WS_THICKFRAME | win32con.WS_SYSMENU | win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX
# window-type values (see xpra/client/gtk3/window/common.py) that should be
# treated like "skip-taskbar" on win32 (no clean equivalent to X11 dialog/utility
# window-manager hints, so we just hide them from the taskbar/alt-tab list):
WINDOW_TYPE_TOOLWINDOW = {"DIALOG", "UTILITY", "SPLASHSCREEN"}


SIZE_SUBCOMMAND: dict[int: str] = {
    win32con.SIZE_MAXHIDE: "MAXHIDE",
    win32con.SIZE_MAXIMIZED: "MAXIMIZED",
    win32con.SIZE_MAXSHOW: "MAXSHOW",
    win32con.SIZE_MINIMIZED: "MINIMIZED",
    win32con.SIZE_RESTORED: "RESTORED",
}


def get_vk_mask(wparam: int) -> tuple[str]:
    return _vk_mask(wparam, MOUSE_VK_MASK)


def get_vk_buttons(wparam: int) -> tuple[int]:
    return _vk_mask(wparam, MOUSE_BUTTON_MASK)


def _vk_mask(wparam: int, mask: dict) -> tuple:
    values = []
    for mask, value in mask.items():
        if wparam & mask:
            values.append(value)
    return tuple(values)


def system_geometry(x: int, y: int, w: int, h: int, style: int, exstyle: int, has_menu=False) -> tuple[int, int, int, int]:
    """
    Convert the window's internal geometry into system coordinates,
    which include the top bar and borders.
    """
    rect = RECT()
    rect.left = x
    rect.top = y
    rect.right = x + w
    rect.bottom = y + h
    AdjustWindowRectEx(byref(rect), style, has_menu, exstyle)
    x1, y1, x2, y2 = rect_to_signed(rect)
    return x1, y1, x2 - x1, y2 - y1


def rect_to_signed(rect: RECT) -> tuple[int, int, int, int]:
    """Convert RECT coordinates to signed values."""
    return (
        to_signed_coordinate(rect.left & 0xFFFF),
        to_signed_coordinate(rect.top & 0xFFFF),
        to_signed_coordinate(rect.right & 0xFFFF),
        to_signed_coordinate(rect.bottom & 0xFFFF)
    )


class ClientWindow(GObject.GObject):

    __gsignals__ = {
        "mapped": no_arg_signal,
        "focused": no_arg_signal,
        "minimized": no_arg_signal,
        "maximized": no_arg_signal,
        "focus-lost": no_arg_signal,
        "moved": no_arg_signal,
        "resized": no_arg_signal,
        "mouse-move": n_arg_signal(4),
        "mouse-click": n_arg_signal(6),
        "wheel": n_arg_signal(5),
        "key": n_arg_signal(6),
        "closed": no_arg_signal,
    }

    module_handle = GetModuleHandleA(None)
    log("module-handle=%#x", module_handle)

    def __init__(self, client, group_leader_window, wid: int, geom, backing_size, metadata: dict,
                 override_redirect, client_properties,
                 border, max_window_size, pixel_depth,
                 headerbar=None):
        GObject.GObject.__init__(self)
        self.client = client
        self.wid = wid
        self.x = geom[0]
        self.y = geom[1]
        self.width = max(1, geom[2])
        self.height = max(1, geom[3])
        self._backing_size = backing_size
        self.alpha = metadata.boolget("has-alpha", False)
        if override_redirect:
            metadata["override-redirect"] = override_redirect
        self.metadata = metadata
        self.pixel_depth = pixel_depth
        self.wnd_proc = WNDPROC(self.wnd_proc_cb)
        self.wc = self.create_wnd_class()
        self.class_atom = RegisterClassExW(byref(self.wc))
        self.hwnd: HWND = 0
        self.hdc: HDC = 0
        self.pixels = c_void_p()
        self.hicon = 0
        self.hicons: set[HICON] = set()
        self.style = 0
        self.resize_counter = 0
        # state:
        self.minimized = False
        self.maximized = False
        self.fullscreen = False
        self._pre_fullscreen_geom = None
        self.state_updates = {}
        self.fullscreen_monitors = ()
        self.size_constraints = typedict()
        self._above = False
        self._below = False
        self._skip_taskbar = False
        self._type_toolwindow = False
        self.backing = None
        log("new window: %#x %s", self.wid, self.metadata)

    def create(self):
        self.hwnd = self.create_window() or 0
        if not self.hwnd:
            log.error("Error creating window")
            log.error(" geometry=%s", (self.x, self.y, self.width, self.height))
            log.error(" alpha=%s", self.alpha)
            log.error(" metadata=%s", self.metadata)
            raise WinError(get_last_error())
        log("hwnd=%s", self.hwnd)
        self.hdc = CreateCompatibleDC(None)
        log("CreateCompatibleDC()=%#x", self.hdc)
        bw, bh = self._backing_size
        self.backing = GDIBacking(self.wid, self.hdc, self.hwnd, bw, bh, self.alpha)
        self.backing.init(self.width, self.height, bw, bh)
        # apply the metadata the window was created with:
        # (`set_metadata()` is otherwise only reached later, via `update_metadata()`,
        # on a subsequent server metadata packet)
        self.set_metadata(typedict(self.metadata))

    def __repr__(self):
        return "Win32ClientWindow(%#x)" % self.wid

    def create_wnd_class(self) -> WNDCLASSEX:
        # we must keep a reference to the WNDPROC wrapper:
        wc = WNDCLASSEX()
        wc.cbSize = sizeof(WNDCLASSEX)
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wc.lpfnWndProc = self.wnd_proc
        wc.hInstance = self.module_handle
        wc.hCursor = LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_WINDOW + 1
        wc.lpszClassName = "XpraWindowClass%i" % self.wid
        return wc

    def update_backing_render_size(self, width: int, height: int) -> None:
        """
        The native window's on-screen (client) size changed - either because the OS
        clamped/adjusted the requested size at creation time, or because the user
        dragged/snapped the window. Recompute the corresponding server-pixel backing
        size via the display subsystem's scale factor (mirroring the GTK3 backend's
        `_set_backing_size()`) and update the backing's render size accordingly.
        """
        backing = self.backing
        if not backing:
            return
        display = self.client.get_subsystem("display") if self.client else None
        if display:
            bw, bh = display.cx(width), display.cy(height)
        else:
            bw, bh = width, height
        backing.init(width, height, bw, bh)

    def get_system_geometry(self, exstyle: int) -> tuple[int, int, int, int]:
        """
        Convert the window's internal geometry into system coordinates,
        which include the top bar and borders.
        """
        return system_geometry(self.x, self.y, self.width, self.height, self.style, exstyle)

    def create_window(self) -> HWND:
        title = self.metadata.strget("title", "")
        dwexstyle = 0
        style = win32con.WS_VISIBLE
        if self.is_OR():
            dwexstyle |= win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOPMOST
            style |= win32con.WS_POPUP
        else:
            dwexstyle |= win32con.WS_EX_ACCEPTFILES | win32con.WS_EX_OVERLAPPEDWINDOW | win32con.WS_EX_APPWINDOW
            style |= win32con.WS_OVERLAPPEDWINDOW
        if self.alpha:
            log.warn("Warning: painting with alpha requires using UpdateLayeredWindow!")
            dwexstyle |= win32con.WS_EX_LAYERED
        self.style = style
        x, y, w, h = self.get_system_geometry(dwexstyle)
        log("create_window() system-geometry(%s)=%s", (self.x, self.y, self.width, self.height), (x, y, w, h))
        if not self.is_OR() and not self.metadata.boolget("set-initial-position", False):
            x = win32con.CW_USEDEFAULT
            y = win32con.CW_USEDEFAULT
        return CreateWindowExW(dwexstyle, self.class_atom, title, style,
                               x, y, w, h,
                               0, 0, self.module_handle, None)

    def wnd_proc_cb(self, hwnd: int, msg: int, wparam: int, lparam) -> int:
        msg_str = WM_MESSAGES.get(msg, str(msg))
        log("wnd_proc_cb(%i, %s, %i, %#x)", hwnd, msg_str, wparam, lparam)
        try:
            if msg == win32con.WM_GETMINMAXINFO and lparam:
                self.apply_size_constraints(lparam)
                return 0
            if msg == win32con.WM_WINDOWPOSCHANGING and self._below and lparam:
                # re-assert "always on bottom" on every pending z-order change
                # (there is no persistent/"sticky" HWND_BOTTOM, unlike HWND_TOPMOST):
                wp = cast(lparam, POINTER(WINDOWPOS)).contents
                wp.hwndInsertAfter = win32con.HWND_BOTTOM
                # falls through to DefWindowProcW, do not return here
            if msg == win32con.WM_CREATE:
                create = cast(lparam, POINTER(CREATESTRUCT)).contents
                self.x = create.x
                self.y = create.y
                if self.backing and (self.width != create.cx or self.height != create.cy):
                    self.update_backing_render_size(create.cx, create.cy)
                    self.width = create.cx
                    self.height = create.cy
                self.emit("mapped")
            if msg == win32con.WM_CLOSE:
                self.emit("closed")
                return 0
            if msg == win32con.WM_MOVE:
                x = lparam & 0xffff
                y = (lparam >> 16) & 0xffff
                if x >= 2**15:
                    x = x - 2**16
                if y >= 2**15:
                    y = y - 2**16
                if x == -32000 and y == -32000:
                    if self.minimized:
                        return 0
                    self.minimized = True
                    self.emit("minimized")
                    return 0
                self.x = x
                self.y = y
                self.emit("moved")
            if msg == win32con.WM_SIZE:
                width = lparam & 0xffff
                height = (lparam >> 16) & 0xffff
                log("WM_SIZE %r: %ix%i", SIZE_SUBCOMMAND.get(wparam, str(wparam)), width, height)
                if wparam == win32con.SIZE_MINIMIZED:
                    if not self.minimized:
                        self.minimized = True
                        self.state_updates["minimized"] = True
                        self.emit("minimized")
                    return 0
                elif wparam == win32con.SIZE_MAXIMIZED:
                    if not self.maximized:
                        self.maximized = True
                        self.state_updates["maximized"] = True
                        self.emit("maximized")
                    return 0
                elif wparam == win32con.SIZE_MAXHIDE:
                    return 0
                elif wparam == win32con.SIZE_MAXSHOW:
                    return 0
                elif wparam == win32con.SIZE_RESTORED:
                    if self.backing and (width != self.width or height != self.height):
                        self.update_backing_render_size(width, height)
                        self.width = width
                        self.height = height
                        self.emit("resized")
                else:
                    log("unexpected WM_SIZE wparam %#x", wparam)
            if msg == win32con.WM_SETFOCUS:
                self.emit("focused")
            if msg == win32con.WM_KILLFOCUS:
                self.emit("focus-lost")
            if msg == win32con.WM_ACTIVATE:
                log("%s: %s", msg_str, ACTIVATION.get(wparam, "unknown"))
            if msg == win32con.WM_MOUSEMOVE:
                x, y = get_xy_lparam(lparam)
                vkeys = get_vk_mask(wparam)
                buttons = get_vk_buttons(wparam)
                self.emit("mouse-move", x, y, vkeys, buttons)
            if msg in (
                win32con.WM_LBUTTONDBLCLK, win32con.WM_MBUTTONDBLCLK, win32con.WM_RBUTTONDBLCLK,
            ):
                # should be handled as fast clicks and trigger double-clicks on the server
                pass
            if msg in (
                win32con.WM_LBUTTONDOWN, win32con.WM_MBUTTONDOWN, win32con.WM_RBUTTONDOWN,
                win32con.WM_LBUTTONUP, win32con.WM_MBUTTONUP, win32con.WM_RBUTTONUP,
            ):
                button = BUTTON_MAP.get(msg, 0)
                assert button > 0
                pressed = msg in (win32con.WM_LBUTTONDOWN, win32con.WM_MBUTTONDOWN, win32con.WM_RBUTTONDOWN)
                x, y = get_xy_lparam(lparam)
                vkeys = get_vk_mask(wparam)
                buttons = get_vk_buttons(wparam)
                self.emit("mouse-click", button, pressed, x, y, vkeys, buttons)
            if msg in (
                # non-client area events:
                win32con.WM_NCLBUTTONDOWN, win32con.WM_NCLBUTTONDBLCLK, win32con.WM_NCLBUTTONUP,
                win32con.WM_NCMBUTTONDOWN, win32con.WM_NCMBUTTONDBLCLK, win32con.WM_NCMBUTTONUP,
                win32con.WM_NCRBUTTONDOWN, win32con.WM_NCRBUTTONDBLCLK, win32con.WM_NCRBUTTONUP,
                WM_NCXBUTTONDOWN, WM_NCXBUTTONDBLCLK, WM_NCXBUTTONUP,
            ):
                log("non-client area event: %s", WNDPROC_EVENT_NAMES.get(msg, msg))
            if msg in (win32con.WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                vertical = msg == win32con.WM_MOUSEWHEEL
                vkeys = get_vk_mask(wparam & 0xffff)
                delta = (wparam >> 16) & 0xffff
                x, y = get_xy_lparam(lparam)
                self.emit("wheel", x, y, vertical, vkeys, delta)
            if msg in (win32con.WM_KEYDOWN, win32con.WM_KEYUP):
                vk_code = wparam
                extended = lparam & (2 << 24)
                scancode = (lparam >> 16) & 0xff

                # Use ToUnicode to convert VK code to character
                keyboard_state = (BYTE * 256)()
                # first retrieve using an empty keyboard state:
                result = (c_wchar * 4)()
                count = ToUnicode(vk_code, 0, keyboard_state, result, 4, 0)
                string = result.value if count > 0 else ""
                # then with the current keyboard state:
                GetKeyboardState(keyboard_state)
                result = (c_wchar * 4)()
                count = ToUnicode(vk_code, 0, keyboard_state, result, 4, 0)
                local_string = result.value if count > 0 else ""

                # for now, we still translate to X11 key names:
                keyname = VK_NAMES.get(vk_code, string)
                log("vk_code: %d, string=%r, local_string=%r, scancode=%i, extended=%s, keyname=%r", vk_code, string, local_string, scancode, extended, keyname)
                if keyname.startswith("VK_"):
                    keyname = VK_X11_MAP.get(keyname[3:], keyname)
                if not string:
                    if vk_code == win32con.VK_CONTROL:
                        keyname = "Control_R" if extended else "Control_L"
                    elif vk_code == win32con.VK_MENU:
                        keyname = "MENU"
                    elif vk_code == win32con.VK_SHIFT:
                        MAPVK_VSC_TO_VK_EX = 3
                        vk = MapVirtualKeyW(scancode, MAPVK_VSC_TO_VK_EX)
                        VK_LSHIFT = 0xA0
                        VK_RSHIFT = 0xA1
                        if vk == VK_LSHIFT:
                            keyname = "Shift_L"
                        elif vk == VK_RSHIFT:
                            keyname = "Shift_R"
                scancode = (lparam >> 16) & 0xff
                pressed = msg == win32con.WM_KEYDOWN
                self.emit("key", keyname, pressed, vk_code, string, scancode, extended)
            if msg == win32con.WM_ERASEBKGND:
                log("skipped erase background")
                return 1
            if msg == win32con.WM_PAINT:
                ps = PAINTSTRUCT()
                hdc = BeginPaint(self.hwnd, byref(ps))
                backing = self.backing
                log("paint hdc=%#x, backing=%s", hdc, backing)
                if backing:
                    backing.paint(hdc)
                EndPaint(self.hwnd, byref(ps))
                return 0
            if msg == win32con.WM_GETICON:
                if self.hicon:
                    return self.hicon
                return 0
            if msg == win32con.WM_DESTROY:
                # Cleanup GDI resources (bitmaps, DCs, icons)
                # but NOT the window class yet
                log("WM_DESTROY: cleaning up GDI resources")
                self.cleanup()
                # Don't return 0 here - let DefWindowProc handle it
            if msg == win32con.WM_NCDESTROY:
                # This is the LAST message - window is fully destroyed
                log("WM_NCDESTROY: will unregister window class")
                # Use GLib idle to defer until message handler completes
                GLib.idle_add(self.cleanup_class)
                return 0
        except Exception:
            log.error("Error handling %s message", msg_str, exc_info=True)
        return DefWindowProcW(hwnd, msg, wparam, lparam)

    def update_metadata(self, metadata: typedict):
        self.metadata.update(metadata)
        self.set_metadata(metadata)

    def set_metadata(self, metadata: typedict):
        if "title" in metadata:
            SetWindowTextW(self.hwnd, metadata.strget("title", ""))
        if "size-constraints" in metadata:
            self.size_constraints = typedict(metadata.dictget("size-constraints"))
        if "transient-for" in metadata:
            self.apply_transient_for(metadata.intget("transient-for"))
        if "maximized" in metadata:
            self.maximized = metadata.boolget("maximized")
            if self.maximized:
                ShowWindow(self.hwnd, win32con.SW_MAXIMIZE)
            else:
                ShowWindow(self.hwnd, win32con.SW_RESTORE)
        if "fullscreen-monitors" in metadata:
            self.fullscreen_monitors = metadata.inttupleget("fullscreen-monitors")
        if "fullscreen" in metadata:
            self.set_fullscreen(metadata.boolget("fullscreen"))
        if "iconic" in metadata:
            self.minimized = metadata.boolget("iconic")
            if self.minimized:
                ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            else:
                ShowWindow(self.hwnd, win32con.SW_RESTORE)
        if "decorations" in metadata:
            self.set_decorations(metadata.boolget("decorations", True))

        if "above" in metadata:
            self._above = metadata.boolget("above")
            change = win32con.HWND_TOPMOST if self._above else win32con.HWND_NOTOPMOST
            SetWindowPos(self.hwnd, change, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

        if "below" in metadata:
            self._below = metadata.boolget("below")
            if self._below:
                # the `WM_WINDOWPOSCHANGING` handler in `wnd_proc_cb` re-asserts this
                # on every subsequent z-order change, since there is no persistent
                # "always on bottom" flag equivalent to `HWND_TOPMOST`:
                SetWindowPos(self.hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            # clearing `_below` needs no HWND action: the next natural z-order
            # change simply stops being overridden

        if "shaded" in metadata:
            # no win32 equivalent, would need to be reimplemented manually
            # (resize down to the titlebar and restore) - not attempted in this pass
            pass

        if "sticky" in metadata:
            # visible on all virtual desktops: would require the undocumented
            # IVirtualDesktopManager COM interface - not attempted in this pass
            pass

        if "skip-taskbar" in metadata:
            self.set_skip_taskbar(metadata.boolget("skip-taskbar"))

        if "skip-pager" in metadata:
            # no win32 equivalent to an X11 pager / virtual-desktop overview
            pass

        if "window-type" in metadata:
            self.set_window_type(metadata.strtupleget("window-type"))

        if "shape" in metadata:
            self.set_shape(metadata.dictget("shape", {}))

    def apply_transient_for(self, wid: int) -> None:
        if not self.hwnd:
            return
        owner_hwnd = 0
        if wid and self.client:
            wm = self.client.get_subsystem("window")
            owner = wm.get_window(wid) if wm else None
            owner_hwnd = getattr(owner, "hwnd", 0) or 0
        SetWindowLongPtrValueW(self.hwnd, GWLP_HWNDPARENT, owner_hwnd)

    def set_fullscreen(self, fullscreen: bool) -> None:
        if fullscreen == self.fullscreen or not self.hwnd:
            self.fullscreen = fullscreen
            return
        self.fullscreen = fullscreen
        if fullscreen:
            self._pre_fullscreen_geom = (self.x, self.y, self.width, self.height)
            left, top, right, bottom = self._get_fullscreen_rect()
            flags = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
            SetWindowPos(self.hwnd, 0, left, top, right - left, bottom - top, flags)
        else:
            geom = self._pre_fullscreen_geom or (self.x, self.y, self.width, self.height)
            self._pre_fullscreen_geom = None
            self.move_resize(*geom)

    def get_monitor_position(self) -> dict[str, Any]:
        if not self.hwnd:
            return {}
        try:
            hmonitor = MonitorFromWindow(self.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            index = EnumDisplayMonitors().index(hmonitor)
            left, top = GetMonitorInfo(hmonitor)["Monitor"][:2]
        except (OSError, ValueError):
            geomlog("failed to resolve monitor for window %#x", self.hwnd, exc_info=True)
            return {}
        return {"index": index, "position": (self.x - left, self.y - top)}

    def _get_fullscreen_rect(self) -> tuple[int, int, int, int]:
        # best-effort multi-monitor span: `fullscreen_monitors` is a 4-tuple of
        # monitor indices (top, bottom, left, right); monitor index ordering from
        # `EnumDisplayMonitors()` is not guaranteed to match the server's enumeration,
        # this is an inherent limitation shared with the X11 implementation:
        monitors = self.fullscreen_monitors
        if len(monitors) == 4:
            try:
                handles = EnumDisplayMonitors()
                rects = [GetMonitorInfo(handles[i])["Monitor"] for i in monitors]
                lefts, tops, rights, bottoms = zip(*rects)
                return min(lefts), min(tops), max(rights), max(bottoms)
            except (IndexError, OSError):
                geomlog("invalid fullscreen-monitors %s, using single monitor", monitors, exc_info=True)
        hmonitor = MonitorFromWindow(self.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        return GetMonitorInfo(hmonitor)["Monitor"]

    def set_decorations(self, decorated: bool) -> None:
        if not self.hwnd or self.is_OR():
            return
        style = self.style
        if decorated:
            style |= DECORATION_STYLE
        else:
            style &= ~DECORATION_STYLE
        if style != self.style:
            self.style = style
            SetWindowLongA(self.hwnd, win32con.GWL_STYLE, style)
            flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED
            SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, flags)

    def _apply_toolwindow(self) -> None:
        if not self.hwnd:
            return
        want = self._skip_taskbar or self._type_toolwindow
        exstyle = GetWindowLongW(self.hwnd, win32con.GWL_EXSTYLE)
        have = bool(exstyle & win32con.WS_EX_TOOLWINDOW)
        if want == have:
            return
        exstyle = (exstyle | win32con.WS_EX_TOOLWINDOW) if want else (exstyle & ~win32con.WS_EX_TOOLWINDOW)
        was_focused = self.has_toplevel_focus()
        SetWindowLongA(self.hwnd, win32con.GWL_EXSTYLE, exstyle)
        # the taskbar / alt-tab list doesn't reliably refresh from SWP_FRAMECHANGED alone
        # for this bit, a hide/show cycle is the documented workaround:
        ShowWindow(self.hwnd, win32con.SW_HIDE)
        ShowWindow(self.hwnd, win32con.SW_SHOW if was_focused else win32con.SW_SHOWNOACTIVATE)

    def set_skip_taskbar(self, skip_taskbar: bool) -> None:
        self._skip_taskbar = skip_taskbar
        self._apply_toolwindow()

    def set_window_type(self, window_types) -> None:
        self._type_toolwindow = bool(set(window_types) & WINDOW_TYPE_TOOLWINDOW)
        self._apply_toolwindow()

    def set_shape(self, shape: dict) -> None:
        if not self.hwnd:
            return
        rectangles = shape.get("Bounding.rectangles")
        if not rectangles:
            # clear any custom shape, restore the default rectangular region:
            SetWindowRgn(self.hwnd, 0, True)
            return
        x_off, y_off = shape.get("x", 0), shape.get("y", 0)
        combined = 0
        for x, y, w, h in rectangles:
            rgn = CreateRectRgn(x_off + x, y_off + y, x_off + x + w, y_off + y + h)
            if not combined:
                combined = rgn
            else:
                CombineRgn(combined, combined, rgn, RGN_OR)
                DeleteObject(rgn)
        if combined:
            # ownership of `combined` transfers to the HWND on success:
            SetWindowRgn(self.hwnd, combined, True)

    def get_info(self) -> dict[str, Any]:
        attributes = [a for a, v in (
            ("fullscreen", self.fullscreen),
            ("maximized", self.maximized),
            ("minimized", self.minimized),
            ("above", self._above),
            ("below", self._below),
            ("skip-taskbar", self._skip_taskbar),
            ("focused", self.has_toplevel_focus()),
        ) if v]
        return {
            "hwnd": self.hwnd,
            "override-redirect": self.is_OR(),
            "position": (self.x, self.y),
            "size": (self.width, self.height),
            "pixel-depth": self.pixel_depth,
            "has-alpha": self.alpha,
            "attributes": attributes,
        }

    def set_alert_state(self, alert_state: bool) -> None:
        if not self.hwnd:
            return
        fwi = FLASHWINFO()
        fwi.cbSize = sizeof(FLASHWINFO)
        fwi.hwnd = self.hwnd
        fwi.dwFlags = (FLASHW_ALL | FLASHW_TIMERNOFG) if alert_state else FLASHW_STOP
        fwi.uCount = 0
        fwi.dwTimeout = 0
        FlashWindowEx(byref(fwi))

    def draw_region(self, x: int, y: int, width: int, height: int,
                    coding: str, img_data, rowstride: int,
                    options: typedict, callbacks: MutableSequence[Callable]):
        backing = self.backing
        if not backing:
            fire_paint_callbacks(callbacks, False, "window does not have a backing!")
            return
        if coding == "void":
            fire_paint_callbacks(callbacks)
            return
        if options.intget("flush", 0) == 0:
            callbacks.append(self.draw_callback)

        backing.draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)

    def draw_callback(self, success: int | bool, message: str):
        if success and self.hwnd:
            GLib.idle_add(self.redraw)

    def redraw(self) -> None:
        InvalidateRect(self.hwnd, None, True)

    def eos(self):
        if backing := self.backing:
            backing.eos()

    def move_resize(self, x: int, y: int, w: int, h: int, resize_counter: int = 0) -> None:
        self.resize_counter = resize_counter
        if not self.hwnd:
            return
        exstyle = GetWindowLongW(self.hwnd, win32con.GWL_EXSTYLE)
        wx, wy, ww, wh = system_geometry(x, y, w, h, self.style, exstyle)
        flags = win32con.SWP_NOACTIVATE | win32con.SWP_NOOWNERZORDER | win32con.SWP_NOZORDER
        geomlog("move_resize%s system geometry=%s", (x, y, w, h, resize_counter), (wx, wy, ww, wh))
        SetWindowPos(self.hwnd, 0, wx, wy, ww, wh, flags)
        # this triggers WM_MOVE / WM_SIZE, which update self.x/y/width/height and the backing

    def resize(self, w: int, h: int, resize_counter: int = 0) -> None:
        self.move_resize(self.x, self.y, w, h, resize_counter)

    def apply_size_constraints(self, lparam) -> None:
        info = cast(lparam, POINTER(MINMAXINFO)).contents
        minw, minh = self.size_constraints.intpair("minimum-size")
        if minw > 0 and minh > 0:
            info.ptMinTrackSize.x = minw
            info.ptMinTrackSize.y = minh
        maxw, maxh = self.size_constraints.intpair("maximum-size")
        if maxw > 0 and maxh > 0:
            info.ptMaxTrackSize.x = maxw
            info.ptMaxTrackSize.y = maxh

    def is_tray(self) -> bool:
        return False

    def is_OR(self) -> bool:
        return self.metadata.get("override-redirect", False)

    def get_window_handle(self) -> int:
        # the native window handle is simply our `HWND`:
        return int(self.hwnd) or 0

    def show_all(self):
        ShowWindow(self.hwnd, win32con.SW_SHOW)
        UpdateWindow(self.hwnd)
        # InvalidateRect(self.hwnd, None, True)

    def has_toplevel_focus(self) -> bool:
        return bool(self.hwnd) and GetForegroundWindow() == self.hwnd

    def present(self) -> None:
        if not self.hwnd:
            return
        if self.minimized:
            ShowWindow(self.hwnd, win32con.SW_RESTORE)
        else:
            ShowWindow(self.hwnd, win32con.SW_SHOW)
        SetForegroundWindow(self.hwnd)

    def restack(self, other_window, above: int = 0) -> None:
        if not self.hwnd:
            return
        flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        other_hwnd = getattr(other_window, "hwnd", 0)
        if above:
            SetWindowPos(self.hwnd, other_hwnd or win32con.HWND_TOP, 0, 0, 0, 0, flags)
        elif other_hwnd:
            # there is no "insert before" in the win32 API,
            # so we place the other window above ourselves instead:
            SetWindowPos(other_hwnd, self.hwnd, 0, 0, 0, 0, flags)
        else:
            SetWindowPos(self.hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0, flags)

    def update_icon(self, img):
        iconlog("update_icon(%s) size=%s", img, img.size)
        self.hicon = img_to_hicon(img)
        iconlog("hicon=%#x", self.hicon)
        for size in (win32con.ICON_SMALL, win32con.ICON_BIG):
            old = SendMessageW(self.hwnd, win32con.WM_SETICON, size, self.hicon)
            if old in self.hicons:
                DestroyIcon(old)
                self.hicons.remove(old)
        self.hicons.add(self.hicon)

    def destroy(self) -> None:
        """Called by the client to initiate window destruction"""
        log("destroy() hwnd=%#x", self.hwnd)
        if hwnd := self.hwnd:
            self.hwnd = 0
            # Just destroy the window - cleanup happens in WM_NCDESTROY
            DestroyWindow(hwnd)
            # The message loop will handle the rest

    def cleanup(self) -> None:
        if backing := self.backing:
            self.backing = None
            backing.close()

        self.hicon = 0
        for hicon in tuple(self.hicons):
            DestroyIcon(hicon)
        self.hicons.clear()

        if hdc := self.hdc:
            self.hdc = 0
            DeleteDC(hdc)

    def cleanup_class(self) -> None:
        ca = self.class_atom
        wc = self.wc
        if ca and wc:
            self.class_atom = 0
            result = UnregisterClassW(wc.lpszClassName, self.module_handle)
            if not result:
                log.warn("UnregisterClassW failed: %s", get_last_error())


GObject.type_register(ClientWindow)
