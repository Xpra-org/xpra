#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Tests for the two per-pixel alpha paths of the win32 client.

The GDI backing needs a layered window (`UpdateLayeredWindow`), the OpenGL
backing must *not* have one: it is composited by DWM straight from its
framebuffer, which a layered window is not presented from.
These tests are skipped on non-Windows platforms.
"""

import sys
import unittest
from ctypes import sizeof, byref

WIN32 = sys.platform == "win32"


def import_opengl_window():
    """
    The OpenGL window module pulls in PyOpenGL at import time,
    which may not be installed even on MS Windows.
    """
    try:
        from xpra.client.win32.opengl import window
    except ImportError as e:
        raise unittest.SkipTest(f"the OpenGL client window is not available: {e}") from None
    return window


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class AlphaExStyleTest(unittest.TestCase):
    """
    Which extended window style each backing asks for.
    `get_alpha_exstyle` does not touch any instance state, so it can be called
    unbound - no window has to be created for these.
    """

    def test_gdi_window_is_layered(self):
        import win32con
        from xpra.client.win32.window import ClientWindow
        self.assertEqual(ClientWindow.get_alpha_exstyle(None), win32con.WS_EX_LAYERED)

    def test_opengl_window_is_not_layered(self):
        GLClientWindow = import_opengl_window().GLClientWindow
        # a layered window is not presented from its swap chain:
        # `SwapBuffers` would have nothing to present to
        self.assertEqual(GLClientWindow.get_alpha_exstyle(None), 0)


@unittest.skipUnless(WIN32, "DWM is only available on MS Windows")
class DWMBlurBehindTest(unittest.TestCase):

    def test_struct_layout(self):
        """
        A wrong ctypes layout would silently hand DWM garbage,
        so pin the offsets down. `hRgnBlur` is a pointer, which leaves 4 bytes
        of padding after the two `BOOL`s on 64-bit.
        """
        from ctypes.wintypes import HRGN
        from xpra.platform.win32.common import DWM_BLURBEHIND
        ptr = sizeof(HRGN)
        offsets = {name: getattr(DWM_BLURBEHIND, name).offset for name in (
            "dwFlags", "fEnable", "hRgnBlur", "fTransitionOnMaximized",
        )}
        self.assertEqual(offsets["dwFlags"], 0)
        self.assertEqual(offsets["fEnable"], 4)
        self.assertEqual(offsets["hRgnBlur"], 8)
        self.assertEqual(offsets["fTransitionOnMaximized"], 8 + ptr)
        self.assertEqual(sizeof(DWM_BLURBEHIND), 24 if ptr == 8 else 16)

    def make_window(self):
        import win32con
        # `WinError` and `get_last_error` only exist in ctypes on MS Windows,
        # so they cannot be imported at module level:
        from ctypes import WinError, get_last_error
        from xpra.platform.win32.common import (
            GetModuleHandleA, WNDCLASSEX, WNDPROC, DefWindowProcW,
            RegisterClassExW, UnregisterClassW, CreateWindowExW, DestroyWindow,
        )
        module_handle = GetModuleHandleA(None)
        class_name = "XpraDWMAlphaTest"
        # the wndproc wrapper must be kept alive for as long as the class is:
        wndproc = WNDPROC(lambda hwnd, msg, wparam, lparam: DefWindowProcW(hwnd, msg, wparam, lparam))
        wc = WNDCLASSEX()
        wc.cbSize = sizeof(WNDCLASSEX)
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW | win32con.CS_OWNDC
        wc.lpfnWndProc = wndproc
        wc.hInstance = module_handle
        wc.lpszClassName = class_name
        atom = RegisterClassExW(byref(wc))
        if not atom:
            raise WinError(get_last_error())
        hwnd = CreateWindowExW(0, atom, "dwm alpha test", win32con.WS_OVERLAPPEDWINDOW,
                               0, 0, 64, 64, 0, 0, module_handle, None)
        if not hwnd:
            UnregisterClassW(class_name, module_handle)
            raise WinError(get_last_error())

        def cleanup() -> None:
            DestroyWindow(hwnd)
            UnregisterClassW(class_name, module_handle)
            # keep the wndproc reference alive until the class is gone:
            assert wndproc and wc

        return hwnd, cleanup

    def test_enable_composition_alpha(self):
        import win32con
        from xpra.platform.win32.common import GetWindowLongW
        enable_composition_alpha = import_opengl_window().enable_composition_alpha
        hwnd, cleanup = self.make_window()
        try:
            self.assertTrue(enable_composition_alpha(hwnd))
            # DWM must not have turned it into a layered window:
            exstyle = GetWindowLongW(hwnd, win32con.GWL_EXSTYLE)
            self.assertFalse(exstyle & win32con.WS_EX_LAYERED)
            # re-applying it is harmless (the blur region is copied by DWM,
            # and we free our handle every time):
            self.assertTrue(enable_composition_alpha(hwnd))
        finally:
            cleanup()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
