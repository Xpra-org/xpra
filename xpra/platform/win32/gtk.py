# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# GTK-on-win32 glue: extract the native `HWND` from a GTK / GDK window.
# This lives apart from `xpra.platform.win32.gui` (which is toolkit-agnostic)
# because it reaches into GDK-Win32 internals via `libgdk-3-0.dll`.

from ctypes import CDLL, pythonapi, py_object
from ctypes.util import find_library
from ctypes.wintypes import HWND, HGDIOBJ

from xpra.log import Logger

log = Logger("win32")

PyCapsule_GetPointer = pythonapi.PyCapsule_GetPointer
PyCapsule_GetPointer.restype = HGDIOBJ
PyCapsule_GetPointer.argtypes = [py_object]
log("PyCapsule_GetPointer=%s", PyCapsule_GetPointer)

GDK_DLL_NAME = "libgdk-3-0.dll"
gdk_dll = find_library(GDK_DLL_NAME)
if not gdk_dll:
    raise ImportError(f"ctypes cannot find {GDK_DLL_NAME!r}")
gdkdll = CDLL(gdk_dll)
gdk_win32_window_get_handle = gdkdll.gdk_win32_window_get_handle
gdk_win32_window_get_handle.argtypes = [HGDIOBJ]
gdk_win32_window_get_handle.restype = HWND
log("gdkdll=%s", gdkdll)


def get_window_handle(window) -> int:
    """ returns the win32 hwnd from a gtk.Window or gdk.Window """
    gdk_window = window
    try:
        gdk_window = window.get_window()
    except Exception:
        pass
    if not gdk_window:
        return 0
    gpointer = PyCapsule_GetPointer(gdk_window.__gpointer__, None)
    hwnd = gdk_win32_window_get_handle(gpointer)
    # log("get_window_handle(%s) gpointer=%#x, hwnd=%#x", gpointer, hwnd)
    return hwnd
