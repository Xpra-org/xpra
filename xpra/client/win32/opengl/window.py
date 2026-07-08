# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from typing import Any
from ctypes import WinError, get_last_error

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.platform.win32.common import WNDCLASSEX
from xpra.platform.win32.gl_context import WGLContext
from xpra.client.win32.window import ClientWindow
from xpra.client.win32.opengl.backing import GLWin32Backing
from xpra.log import Logger

log = Logger("opengl", "window", "win32")

GObject = gi_import("GObject")


def check_support(force_enable: bool = False) -> dict[str, Any]:
    # `WGLContext.check_support` creates its own throwaway window, makes a WGL
    # context current on it and validates PyOpenGL support - no Gtk involved:
    return WGLContext().check_support(force_enable)


class GLClientWindow(ClientWindow):
    """
    Native win32 client window that renders with OpenGL.

    It reuses all of the plain `ClientWindow` machinery (native `HWND`, message
    loop, input handling) but swaps the GDI backing for a WGL-backed
    `GLWin32Backing` bound to the window's own `HWND`.
    """

    # populated by the opengl subsystem (see `OpenGLClient.init_opengl`):
    MAX_VIEWPORT_DIMS: tuple[int, int] = (16 * 1024, 16 * 1024)
    MAX_BACKING_DIMS: tuple[int, int] = (16 * 1024, 16 * 1024)

    def __init__(self, *args) -> None:
        super().__init__(*args)
        # create the backing eagerly (before the native `HWND` exists) so that
        # `self._backing` is available to the shared OpenGL probe in
        # `xpra.opengl.window.test_gl_client_window`; the real `HWND` is wired
        # up later in `create()`:
        self.backing = GLWin32Backing(self.wid, 0, self.width, self.height, self.alpha, self.pixel_depth)

    def __repr__(self):
        return "GLWin32ClientWindow(%#x)" % self.wid

    def is_GL(self) -> bool:
        return True

    # expose the backing under the `_backing` name expected by shared code
    # (the OpenGL probe and the window manager's `reinit_windows`):
    @property
    def _backing(self):
        return self.backing

    @_backing.setter
    def _backing(self, value) -> None:
        self.backing = value

    def create_wnd_class(self) -> WNDCLASSEX:
        wc = super().create_wnd_class()
        # a private device context keeps the pixel format / GL binding stable:
        wc.style |= win32con.CS_OWNDC
        return wc

    def create(self) -> None:
        if self.hwnd:
            return
        self.hwnd = self.create_window() or 0
        if not self.hwnd:
            log.error("Error creating OpenGL window")
            log.error(" geometry=%s", (self.x, self.y, self.width, self.height))
            log.error(" metadata=%s", self.metadata)
            raise WinError(get_last_error())
        log("create() hwnd=%#x", self.hwnd)
        # no GDI memory DC is needed for OpenGL rendering; bind the backing to
        # the native window and let it own the WGL context:
        self.backing.set_hwnd(self.hwnd)
        self.backing.paint_screen = True
        self.backing.init(self.width, self.height, self.width, self.height)
        self.set_metadata(typedict(self.metadata))

    def realize(self) -> None:
        # used by the shared OpenGL probe, which creates the window without
        # going through the normal `_new_window` -> `create()` path:
        if not self.hwnd:
            self.create()

    def close(self) -> None:
        # used by the shared OpenGL probe to tear the test window down:
        self.destroy()


GObject.type_register(GLClientWindow)
