# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con

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
    win32con.WM_NCHITTEST: "WM_NCHITTEST",

    win32con.WM_IME_SETCONTEXT: "WM_IME_SETCONTEXT",
    win32con.WM_IME_NOTIFY: "WM_IME_NOTIFY",
    win32con.WM_QUERYOPEN: "WM_QUERYOPEN",

    # System
    win32con.WM_TIMER: "WM_TIMER",
    win32con.WM_COMMAND: "WM_COMMAND",
    win32con.WM_SYSCOMMAND: "WM_SYSCOMMAND",
    win32con.WM_SETCURSOR: "WM_SETCURSOR",
}
