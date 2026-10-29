# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import ctypes
import os

from xpra.x11.error import xsync
from xpra.x11.bindings.test import XTestBindings
from xpra.log import Logger

log = Logger("x11", "server", "pointer")

# XTestFakeMotionEvent is compiled with screen_number=0
# (xpra/x11/bindings/test.pyx). On a multi-screen display
# (DISPLAY=:N.M, M != 0) every synthetic move lands on screen 0
# instead of the screen this server is bound to.
# button_action calls move_pointer() before the click, so clicks miss too.
# XWarpPointer takes a destination window, so it hits the correct screen;
# xtest_fake_button then acts where the pointer already is.
_libx11 = None
_x11_display = None
_x11_root_window = None


def _x11_root():
    global _libx11, _x11_display, _x11_root_window
    if _x11_root_window is not None:
        return _libx11, _x11_display, _x11_root_window
    lib = ctypes.CDLL("libX11.so.6")
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    # None -> NULL -> Xlib falls back to getenv("DISPLAY") itself, same as
    # every other X11 client in this process.
    display = lib.XOpenDisplay(None)
    if not display:
        raise RuntimeError(f"XOpenDisplay failed for DISPLAY={os.environ.get('DISPLAY')!r}")
    lib.XDefaultRootWindow.restype = ctypes.c_ulong
    lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    root = lib.XDefaultRootWindow(display)
    lib.XWarpPointer.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_int, ctypes.c_int,
    ]
    lib.XFlush.argtypes = [ctypes.c_void_p]
    _libx11, _x11_display, _x11_root_window = lib, display, root
    return lib, display, root


def _warp_pointer(x: int, y: int) -> bool:
    try:
        lib, display, root = _x11_root()
    except Exception as e:
        log.warn("Warning: failed to open a direct X11 connection for pointer warp: %s", e)
        return False
    # src_w=0 (X11 "None" -- no source-window constraint), dest_w=root of
    # our own screen, dest_x/y absolute within it -- moves the pointer onto
    # this screen regardless of which screen XTest itself defaults to.
    lib.XWarpPointer(display, 0, root, 0, 0, 0, 0, x, y)
    lib.XFlush(display)
    return True


class XTestPointerDevice:
    __slots__ = ()

    def __repr__(self):
        return "XTestPointerDevice"

    @staticmethod
    def move_pointer(x: int, y: int, props: dict) -> None:
        log("xtest_fake_motion%s", (x, y, props))
        with xsync:
            if not _warp_pointer(x, y):
                XTestBindings().xtest_fake_motion(x, y)

    # noinspection PyInconsistentReturns
    @staticmethod
    def get_position() -> tuple[int, int]:
        with xsync:
            from xpra.x11.bindings.keyboard import X11KeyboardBindings
            return X11KeyboardBindings().query_pointer()

    @staticmethod
    def click(button: int, pressed: bool, props: dict) -> None:
        log("xtest_fake_button(%i, %s, %s)", button, pressed, props)
        with xsync:
            XTestBindings().xtest_fake_button(button, pressed)

    @staticmethod
    def wheel_motion(button: int, distance: float) -> None:
        raise NotImplementedError()

    @staticmethod
    def has_precise_wheel() -> bool:
        return False
