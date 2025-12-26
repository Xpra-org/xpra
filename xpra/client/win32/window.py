#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from io import BytesIO
from ctypes.wintypes import HWND
from ctypes import byref, sizeof

from xpra.platform.win32.common import (
    GetModuleHandleA,
    WNDPROC, WNDCLASSEX, RegisterClassExW, CreateWindowExW, DefWindowProcA,
    GetDC, ReleaseDC,
    LoadCursor,
    BeginPaint, EndPaint,
)
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("client", "window")

WM_MESSAGES: dict[int, str] = {
    win32con.WM_NULL: "WM_NULL",

    # Window Lifecycle
    win32con.WM_CREATE: "WM_CREATE",
    win32con.WM_DESTROY: "WM_DESTROY",
    win32con.WM_CLOSE: "WM_CLOSE",
    win32con.WM_QUIT: "WM_QUIT",

    # Painting & Display
    win32con.WM_PAINT: "WM_PAINT",
    win32con.WM_ERASEBKGND: "WM_ERASEBKGND",
    win32con.WM_DISPLAYCHANGE: "WM_DISPLAYCHANGE",
    win32con.WM_NCPAINT: "WM_NCPAINT",

    # Mouse Input
    win32con.WM_MOUSEMOVE: "WM_MOUSEMOVE",
    win32con.WM_LBUTTONDOWN: "WM_LBUTTONDOWN",
    win32con.WM_LBUTTONUP: "WM_LBUTTONUP",
    win32con.WM_RBUTTONDOWN: "WM_RBUTTONDOWN",
    win32con.WM_RBUTTONUP: "WM_RBUTTONUP",
    win32con.WM_MBUTTONDOWN: "WM_MBUTTONDOWN",
    win32con.WM_MBUTTONUP: "WM_MBUTTONUP",
    win32con.WM_MOUSEWHEEL: "WM_MOUSEWHEEL",
    win32con.WM_MOUSELEAVE: "WM_MOUSELEAVE",

    # Keyboard Input
    win32con.WM_KEYDOWN: "WM_KEYDOWN",
    win32con.WM_KEYUP: "WM_KEYUP",
    win32con.WM_CHAR: "WM_CHAR",
    win32con.WM_SYSKEYDOWN: "WM_SYSKEYDOWN",
    win32con.WM_SYSKEYUP: "WM_SYSKEYUP",

    # Window State
    win32con.WM_SIZE: "WM_SIZE",
    win32con.WM_MOVE: "WM_MOVE",
    win32con.WM_ACTIVATE: "WM_ACTIVATE",
    win32con.WM_SETFOCUS: "WM_SETFOCUS",
    win32con.WM_KILLFOCUS: "WM_KILLFOCUS",
    win32con.WM_SHOWWINDOW: "WM_SHOWWINDOW",
    win32con.WM_ENABLE: "WM_ENABLE",
    win32con.WM_GETMINMAXINFO: "WM_GETMINMAXINFO",
    win32con.WM_NCCALCSIZE: "WM_NCCALCSIZE",
    win32con.WM_NCCREATE: "WM_NCCREATE",
    win32con.WM_WINDOWPOSCHANGING: "WM_WINDOWPOSCHANGING",
    win32con.WM_ACTIVATEAPP: "WM_ACTIVATEAPP",
    win32con.WM_NCACTIVATE: "WM_NCACTIVATE",
    win32con.WM_GETICON: "WM_GETICON",
    win32con.WM_WINDOWPOSCHANGED: "WM_WINDOWPOSCHANGED",

    win32con.WM_IME_SETCONTEXT: "WM_IME_SETCONTEXT",
    win32con.WM_IME_NOTIFY: "WM_IME_NOTIFY",

    # System
    win32con.WM_TIMER: "WM_TIMER",
    win32con.WM_COMMAND: "WM_COMMAND",
    win32con.WM_SYSCOMMAND: "WM_SYSCOMMAND",
    win32con.WM_SETCURSOR: "WM_SETCURSOR",
}


class ClientWindow(object):
    module_handle = GetModuleHandleA(None)
    log("module-handle=%#x", module_handle)

    def __init__(self, client, group_leader_window, wid: int, geom, backing_size, metadata: dict,
                 override_redirect, client_properties,
                 border, max_window_size, pixel_depth,
                 headerbar):
        if metadata.boolget("set-initial-position", False):
            self.x = geom[0]
            self.y = geom[1]
        else:
            self.x = win32con.CW_USEDEFAULT
            self.y = win32con.CW_USEDEFAULT
        self.width = geom[2]
        self.height = geom[3]
        self.metadata = metadata
        self.wnd_proc = WNDPROC(self.wnd_proc_cb)
        self.class_atom = self.create_wnd_class()
        log("class-atom=%s", self.class_atom)
        title = metadata.strget("title", "")
        self.hwnd = self.create_window(title)
        log("hwnd=%s", self.hwnd)
        self.hdc = GetDC(self.hwnd)

    def create_wnd_class(self):
        # we must keep a reference to the WNDPROC wrapper:
        wc = WNDCLASSEX()
        wc.cbSize = sizeof(WNDCLASSEX)
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wc.lpfnWndProc = self.wnd_proc
        wc.hInstance = self.module_handle
        wc.hCursor = LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_WINDOW
        wc.lpszClassName = "XpraWindowClass"
        return RegisterClassExW(byref(wc))

    def create_window(self, title: str) -> HWND:
        dwexstyle = win32con.WS_EX_ACCEPTFILES | win32con.WS_EX_OVERLAPPEDWINDOW | win32con.WS_EX_LAYERED | win32con.WS_EX_APPWINDOW
        # dwexstyle = win32con.WS_EX_OVERLAPPEDWINDOW
        return CreateWindowExW(
            dwexstyle,
            self.class_atom,
            title,
            win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
            self.x, self.y, self.width, self.height,
            0,
            0,
            self.module_handle,
            None
        )

    def wnd_proc_cb(self, hwnd: int, msg: int, wparam: int, lparam):
        msg_str = WM_MESSAGES.get(msg, str(msg))
        log("wnd_proc_cb(%i, %s, %i, %#x)", hwnd, msg_str, wparam, lparam)
        if msg == win32con.WM_PAINT:
            BeginPaint(hwnd)
            #self.paint()
            EndPaint(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            if self.hdc:
                ReleaseDC(self.hwnd, self.hdc)
                self.hdc = 0
            return 0
        return DefWindowProcA(hwnd, msg, wparam, lparam)

    def update_metadata(self, metadata: typedict):
        self.metadata.update(metadata)

    def draw(self, x: int, y: int, _w: int, _h: int, coding: str, data, _stride: int) -> None:
        if coding not in ("png", "jpg", "webp"):
            raise ValueError(f"unsupported format {coding!r}")
        from PIL import Image
        img = Image.open(BytesIO(data))
        log("img=%s", img)
        # todo: update backing with image

    def is_tray(self) -> bool:
        return False

    def show_all(self):
        pass

    def update_icon(self, img):
        pass

    def destroy(self) -> None:
        pass
