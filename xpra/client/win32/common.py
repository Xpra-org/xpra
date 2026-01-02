# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import sizeof, byref, c_void_p, memmove
from ctypes.wintypes import HICON

import win32con

from xpra.platform.win32.common import (
    GetDC, CreateCompatibleDC, BITMAPV5HEADER, CreateDIBSection, CreateBitmap,
    ICONINFO, CreateIconIndirect, DeleteObject, DeleteDC, ReleaseDC,
)


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


def to_signed_coordinate(coord) -> int:
    """
    Convert a 16-bit unsigned coordinate to a signed coordinate.

    Windows uses signed coordinates, but when read as unsigned values,
    negative coordinates (like -32000 for minimized windows) appear
    as large positive values (like 33536).

    Args:
        coord: Unsigned 16-bit coordinate value (0-65535)

    Returns:
        Signed coordinate value (-32768 to 32767)
    """
    if coord > 32767:
        return coord - 65536
    return coord


def get_xy_lparam(lparam: int) -> tuple[int, int]:
    """
        Extract signed X and Y coordinates from a Windows LPARAM value.

        Args:
            lparam: The LPARAM value containing packed coordinates

        Returns:
            tuple: (x, y) as signed integers
        """
    # Extract low-order 16 bits (X coordinate)
    x = lparam & 0xFFFF
    # Extract high-order 16 bits (Y coordinate)
    y = (lparam >> 16) & 0xFFFF

    return to_signed_coordinate(x), to_signed_coordinate(y)


def img_to_hicon(img) -> HICON:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    width, height = img.size

    hdc = GetDC(0)
    memdc = CreateCompatibleDC(hdc)

    rgb = BITMAPV5HEADER()
    rgb.bV5Size = sizeof(BITMAPV5HEADER)
    rgb.bV5Width = width
    rgb.bV5Height = -height
    rgb.bV5Planes = 1
    rgb.bV5BitCount = 32
    rgb.bV5Compression = win32con.BI_RGB

    bits = c_void_p()
    hbm_color = CreateDIBSection(memdc, rgb, 0, byref(bits), None, 0)

    # Copy RGBA data to the bitmap
    bgra = img.tobytes("raw", "BGRA")
    memmove(bits, bgra, len(bgra))

    # Create mask bitmap (for alpha channel)
    hbm_mask = CreateBitmap(width, height, 1, 1, None)

    iconinfo = ICONINFO()
    iconinfo.fIcon = True
    iconinfo.xHotspot = 0
    iconinfo.yHotspot = 0
    iconinfo.hbmMask = hbm_mask
    iconinfo.hbmColor = hbm_color

    hicon = CreateIconIndirect(byref(iconinfo))

    DeleteObject(hbm_color)
    DeleteObject(hbm_mask)
    DeleteDC(memdc)
    ReleaseDC(0, hdc)
    return hicon
