#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from io import BytesIO
from ctypes.wintypes import HWND, ATOM
from ctypes import byref, sizeof

from xpra.platform.win32.common import (
    GetModuleHandleA,
    WNDPROC, WNDCLASSEX, RegisterClassExW, CreateWindowExW, DefWindowProcW,
    GetDC, ReleaseDC,
    LoadCursor,
    ShowWindow, UpdateWindow, InvalidateRect,
    BeginPaint, EndPaint, PAINTSTRUCT,
)
from xpra.client.win32.common import WM_MESSAGES
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("client", "window")


class ClientWindow(object):
    module_handle = GetModuleHandleA(None)
    log("module-handle=%#x", module_handle)

    def __init__(self, client, group_leader_window, wid: int, geom, backing_size, metadata: dict,
                 override_redirect, client_properties,
                 border, max_window_size, pixel_depth,
                 headerbar):
        self.wid = wid
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
        self.hwnd = self.create_window()
        log("hwnd=%s", self.hwnd)
        self.hdc = GetDC(self.hwnd)

    def __repr__(self):
        return "Win32ClientWindow(%i)" % self.wid

    def create_wnd_class(self) -> ATOM:
        # we must keep a reference to the WNDPROC wrapper:
        wc = WNDCLASSEX()
        wc.cbSize = sizeof(WNDCLASSEX)
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wc.lpfnWndProc = self.wnd_proc
        wc.hInstance = self.module_handle
        wc.hCursor = LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_WINDOW + 1
        wc.lpszClassName = "XpraWindowClass"
        return RegisterClassExW(byref(wc))

    def create_window(self) -> HWND:
        title = self.metadata.strget("title", "")
        alpha = self.metadata.boolget("has-alpha", False)
        dwexstyle = win32con.WS_EX_ACCEPTFILES | win32con.WS_EX_OVERLAPPEDWINDOW | win32con.WS_EX_APPWINDOW
        if alpha:
            log.warn("Warning: painting will require using UpdateLayeredWindow!")
            dwexstyle |= win32con.WS_EX_LAYERED
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

    def wnd_proc_cb(self, hwnd: int, msg: int, wparam: int, lparam) -> int:
        msg_str = WM_MESSAGES.get(msg, str(msg))
        log("wnd_proc_cb(%i, %s, %i, %#x)", hwnd, msg_str, wparam, lparam)
        if msg == win32con.WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = BeginPaint(hwnd, byref(ps))
            log("paint hdc=%#x", hdc)
            try:
                # self.paint()
                pass
            finally:
                EndPaint(hwnd, byref(ps))
            return 0
        if msg == win32con.WM_DESTROY:
            if self.hdc:
                ReleaseDC(self.hwnd, self.hdc)
                self.hdc = 0
            return 0
        return DefWindowProcW(hwnd, msg, wparam, lparam)

    def update_metadata(self, metadata: typedict):
        self.metadata.update(metadata)

    def draw(self, x: int, y: int, _w: int, _h: int, coding: str, data, _stride: int) -> None:
        if coding not in ("png", "jpg", "webp"):
            raise ValueError(f"unsupported format {coding!r}")
        from PIL import Image
        img = Image.open(BytesIO(data))
        log("img=%s", img)
        # todo: update backing with image
        InvalidateRect(self.hwnd, None, True)

    def is_tray(self) -> bool:
        return False

    def show_all(self):
        ShowWindow(self.hwnd, win32con.SW_SHOW)
        UpdateWindow(self.hwnd)
        # InvalidateRect(self.hwnd, None, True)

    def update_icon(self, img):
        pass

    def destroy(self) -> None:
        pass
