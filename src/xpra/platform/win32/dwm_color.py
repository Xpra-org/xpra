# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import WinDLL, windll, c_int, byref, Structure, POINTER
from ctypes.wintypes import DWORD, PDWORD, PBOOL, BOOL, UINT

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

from xpra.log import Logger
from xpra.util import envbool

log = Logger("win32")

TITLEBAR_TRANSPARENCY = envbool("XPRA_TITLEBAR_TRANSPARENCY", False)

COLORREF = DWORD        #0x00bbggrr

class COLORIZATIONPARAMS(Structure):
    _fields_ = (
        ('Color',                       COLORREF),
        ('Afterglow',                   COLORREF),
        ('ColorBalance',                UINT),
        ('AfterglowBalance',            UINT),
        ('BlurBalance',                 UINT),
        ('GlassReflectionIntensity',    UINT),
        ('Opaque',                      BOOL),
        )
PCOLORIZATIONPARAMS = POINTER(COLORIZATIONPARAMS)

try:
    DwmGetColorizationParameters = windll.dwmapi[127]
except Exception:
    DwmGetColorizationParameters = None
else:
    DwmGetColorizationParameters.argyptes = [PCOLORIZATIONPARAMS]
    DwmGetColorizationParameters.restype = c_int

def rgba(c):
    r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
    a = (c >> 24) & 0xff
    return (r, g, b, a)

def get_frame_color():
    if not DwmGetColorizationParameters:
        return None
    params = COLORIZATIONPARAMS()
    r = DwmGetColorizationParameters(byref(params))
    log("DwmGetColorizationParameters(..)=%i", r)
    if r:
        return None
    return params.Color

def get_colorization_color():
    dwmapi = WinDLL("dwmapi", use_last_error=True)
    DwmGetColorizationColor = dwmapi.DwmGetColorizationColor
    DwmGetColorizationColor.restype = c_int
    DwmGetColorizationColor.argtypes = [PDWORD, PBOOL]
    color = DWORD()
    opaque = BOOL()
    r = DwmGetColorizationColor(byref(color), byref(opaque))
    log("DwmGetColorizationColor(..)=%i", r)
    if r:
        return None
    return color.value


def match_window_color():
    color = get_frame_color() or get_colorization_color()
    if not color:
        return
    r, g, b, a = rgba(color)
    log("rgba(%#x)=%s", color, (r, g, b, a))
    if TITLEBAR_TRANSPARENCY:
        color_str = "rgba(%i, %i, %i, %.2f)" % (r, g, b, a/255)
    else:
        color_str = "rgb(%i, %i, %i)" % (r, g, b)
    if min(r, g, b)<128:
        title_color_str = "white"
    else:
        title_color_str = "black"
    if max(abs(0x99-c) for c in (r, g, b))>64:
        title_unfocused_color_str = "#999999"
    else:
        title_unfocused_color_str = "#333333"
    if max(abs(0xff-c) for c in (r, g, b))>64:
        unfocused_color_str = "white"
    else:
        unfocused_color_str = "#666666"
    style_provider = Gtk.CssProvider()
    css_data = """
.titlebar {
 background-color: %s;
 background-image: none;
}
headerbar .title {
 color : %s;
}
headerbar .titlebutton {
 color: %s;
}
.titlebar:backdrop {
 background-color: %s;
}
.titlebar:backdrop .title {
 color : %s;
}
headerbar:backdrop .titlebutton {
 color: %s;
}
""" % (
 color_str, title_color_str, title_color_str,
 unfocused_color_str, title_unfocused_color_str, title_unfocused_color_str,
)
    log("match_window_color() css=%r", css_data)
    style_provider.load_from_data(css_data.encode("latin1"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        style_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION+1
        )
