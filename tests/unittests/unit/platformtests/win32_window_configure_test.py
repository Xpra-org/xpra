#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The win32 windows send their own `window-configure` packets.
These tests are skipped on non-Windows platforms.
"""

import unittest
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch

from xpra.os_util import WIN32


class Display:
    # client pixels are twice the server pixels:
    @staticmethod
    def cx(v):
        return v // 2

    cy = cx

    @staticmethod
    def sx(v):
        return v * 2

    sy = sx

    @staticmethod
    def get_server_position(pos):
        return pos[0] + 100, pos[1]

    @staticmethod
    def cp(x, y):
        return x // 2, y // 2


def scaled_display(scale: float):
    return SimpleNamespace(sx=lambda v: round(v * scale), sy=lambda v: round(v * scale),
                           cx=lambda v: round(v / scale), cy=lambda v: round(v / scale),
                           sp=lambda x, y: (round(x * scale), round(y * scale)),
                           cp=lambda x, y: (round(x / scale), round(y / scale)),
                           get_server_position=lambda pos: tuple(pos))


class Backing:
    """ records the sizes the backing is initialized with """

    def __init__(self, size):
        self.size = size
        self.inits = []

    def init(self, ww, wh, bw, bh):
        self.inits.append((ww, wh, bw, bh))
        self.size = bw, bh


def native_patches(set_window_pos):
    """ `move_resize` without a native window, `system_geometry` returns the client geometry """
    from contextlib import ExitStack
    from xpra.client.win32 import window as native
    stack = ExitStack()
    stack.enter_context(patch.object(native, "GetWindowLongW", lambda hwnd, index: 0))
    stack.enter_context(patch.object(native, "get_frame_dpi", lambda hwnd: 0))
    stack.enter_context(patch.object(native, "system_geometry", lambda x, y, w, h, *args, **kwargs: (x, y, w, h)))
    stack.enter_context(patch.object(native, "SetWindowPos", set_window_pos))
    return stack


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
class Win32ConfigureTest(unittest.TestCase):

    def make_window(self, subsystems, readonly=False, width=200, height=100, backing=None):
        from xpra.client.win32.window import ClientWindow
        sent = []
        subsystems.setdefault("window", SimpleNamespace(send=lambda *packet: sent.append(packet)))
        window = SimpleNamespace(get_subsystem=subsystems.get, is_readonly=lambda: readonly,
                                 wid=7, x=20, y=40, width=width, height=height, backing=backing,
                                 state_updates={"fullscreen": True}, resize_counter=3,
                                 pop_client_properties=lambda: {},
                                 get_monitor_position=lambda: {"index": 1, "position": (10, 20)})
        for name in ("get_server_geometry", "get_server_monitor_position", "send_configure", "clamp_backing_size"):
            setattr(window, name, MethodType(getattr(ClientWindow, name), window))
        return window, sent

    def test_send_configure(self) -> None:
        window, sent = self.make_window({"display": Display()})
        window.send_configure()
        self.assertEqual(sent, [("window-configure", 7, {
            "state": {"fullscreen": True},
            "geometry": (110, 20, 100, 50),
            "resize-counter": 3,
            "raw-position": (10, 20),
            "monitor": {"index": 1, "position": (5, 10)},
        })])
        self.assertEqual(window.state_updates, {})

    def test_send_configure_fractional_scaling(self) -> None:
        # the server must be told the size it knows, not one pixel off:
        for backing_size, expected in (
            ((1193, 847), (1193, 847)),
            ((1001, 703), (1192, 848)),
        ):
            with self.subTest(backing_size=backing_size):
                backing = SimpleNamespace(size=backing_size)
                window, sent = self.make_window({"display": scaled_display(0.8)},
                                                width=954, height=678, backing=backing)
                window.send_configure()
                self.assertEqual(sent[0][2]["geometry"], (25, 50, *expected))

    def test_update_backing_render_size(self) -> None:
        from xpra.client.win32.window import ClientWindow
        for server_size, expected in (
            # resized by the user, only the height changed: the width is still 1193 server pixels
            (None, (1193, 875)),
            # resized by the server, to a width that is also 954 window pixels:
            ((1192, 875), (1192, 875)),
        ):
            with self.subTest(server_size=server_size):
                backing = Mock(size=(1193, 847))
                window = SimpleNamespace(backing=backing, get_subsystem={"display": scaled_display(0.8)}.get,
                                         update_client_properties=Mock(), _requested_server_size=server_size,
                                         clamp_backing_size=lambda size: size)
                ClientWindow.update_backing_render_size(window, 954, 700)
                backing.init.assert_called_once_with(954, 700, *expected)

    def test_move_resize_server_size(self) -> None:
        import win32con
        from xpra.client.win32 import window as native
        from xpra.client.win32.window_state import handle_size

        for size, server_size, max_width, expected in (
            # only the height changes in window pixels, the width of 954 is both 1193 and 1192 server pixels:
            ((954, 700), (1192, 875), 0, (1192, 875)),
            # the window size does not change, so there is no `WM_SIZE`:
            ((954, 678), (1192, 847), 0, (1192, 847)),
            # the OS clamps the width: (ie: the size constraints)
            ((954, 700), (1192, 875), 900, (1125, 875)),
            # not resized by the server: (ie: `rescale_window`)
            ((954, 700), None, 0, (1193, 875)),
        ):
            with self.subTest(size=size, server_size=server_size, max_width=max_width):
                backing = Backing((1193, 847))
                window, sent = self.make_window({"display": scaled_display(0.8)},
                                                width=954, height=678, backing=backing)
                vars(window).update(hwnd=1, style=0, maximized=False, minimized=False, emit=Mock(),
                                    update_client_properties=Mock(), _requested_size=None,
                                    _requested_server_size=None)
                for name in ("move_resize", "update_backing_server_size", "update_backing_render_size"):
                    setattr(window, name, MethodType(getattr(native.ClientWindow, name), window))

                def set_window_pos(_hwnd, _after, _x, _y, w, h, _flags):
                    # `system_geometry` is patched out, so this is the client size,
                    # `handle_size` ignores a `WM_SIZE` that does not change it:
                    handle_size(window, win32con.SIZE_RESTORED, min(w, max_width or w), h)

                with native_patches(set_window_pos):
                    window.move_resize(window.x, window.y, *size, 5, server_size)
                self.assertEqual(backing.size, expected)
                # the backing is only updated once, with the size of the window:
                self.assertEqual(backing.inits, [(window.width, window.height, *expected)])
                self.assertIsNone(window._requested_server_size)
                window.send_configure()
                self.assertEqual(sent[0][2]["geometry"][2:], expected)

    def test_system_geometry_large_coordinates(self) -> None:
        import win32con
        from xpra.client.win32.window import system_geometry
        # beyond the 16-bit range: the frame must still surround the client area
        for x, y in ((40000, 50000), (-40000, -50000), (100, 100)):
            with self.subTest(x=x, y=y):
                wx, wy, ww, wh = system_geometry(x, y, 640, 480, win32con.WS_OVERLAPPEDWINDOW, 0)
                self.assertTrue(x - 64 < wx <= x and y - 128 < wy <= y, (wx, wy))
                self.assertTrue(wx + ww >= x + 640 and wy + wh >= y + 480, (ww, wh))

    def test_system_geometry_dpi(self) -> None:
        import win32con
        from xpra.client.win32.window import system_geometry
        from xpra.platform.win32.dpi import adjust_window_rect_for_dpi
        from xpra.platform.win32.common import RECT
        if not adjust_window_rect_for_dpi(RECT(), win32con.WS_OVERLAPPEDWINDOW, False, 0, 96):
            self.skipTest("AdjustWindowRectExForDpi is not available")
        style = win32con.WS_OVERLAPPEDWINDOW
        w96, h96 = system_geometry(0, 0, 640, 480, style, 0, dpi=96)[2:]
        w192, h192 = system_geometry(0, 0, 640, 480, style, 0, dpi=192)[2:]
        # the frame is thicker at a higher DPI, the client area is the same:
        self.assertGreater(w192, w96)
        self.assertGreater(h192, h96)
        # popups have no frame at any DPI:
        self.assertEqual(system_geometry(10, 20, 640, 480, win32con.WS_POPUP, 0, dpi=192), (10, 20, 640, 480))

    def test_frame_dpi(self) -> None:
        import ctypes
        from ctypes.wintypes import HWND, DWORD, LPCWSTR, HMENU, HINSTANCE, LPVOID
        from xpra.platform.win32 import dpi
        # our own function pointers, with the class name as a string:
        user32 = ctypes.WinDLL("user32")
        # both functions require Windows 10 1607 or later:
        set_context = getattr(user32, "SetThreadDpiAwarenessContext", None)
        if not set_context:
            self.skipTest("SetThreadDpiAwarenessContext is not available")
        if not dpi.get_window_dpi(user32.GetDesktopWindow()):
            self.skipTest("GetDpiForWindow is not available")
        set_context.restype = ctypes.c_void_p
        set_context.argtypes = [ctypes.c_void_p]
        create = user32.CreateWindowExW
        create.restype = HWND
        create.argtypes = [DWORD, LPCWSTR, LPCWSTR, DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           HWND, HMENU, HINSTANCE, LPVOID]
        destroy = user32.DestroyWindow
        destroy.argtypes = [HWND]
        # the frame of a Per-Monitor v1 window uses the system DPI:
        for context, v2 in ((dpi.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE, False),
                            (dpi.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, True)):
            with self.subTest(v2=v2):
                # returns the previous context, or NULL if this one is not supported:
                # (ie: Per-Monitor v2 requires Windows 10 1703 or later)
                previous = set_context(context)
                if not previous:
                    self.skipTest(f"the {dpi.CONTEXT_NAMES[context]!r} DPI awareness context is not supported")
                try:
                    hwnd = create(0, "STATIC", "", 0, 0, 0, 10, 10, 0, 0, 0, None)
                finally:
                    set_context(previous)
                self.assertTrue(hwnd)
                try:
                    self.assertEqual(dpi.is_per_monitor_v2(hwnd), v2)
                    self.assertEqual(dpi.get_frame_dpi(hwnd), dpi.get_window_dpi(hwnd) if v2 else 0)
                finally:
                    destroy(hwnd)
        self.assertEqual(dpi.get_frame_dpi(0), 0)

    def test_fit_frame_to_dpi(self) -> None:
        import win32con
        from xpra.client.win32 import window as native

        def frame(x, y, w, h, style, exstyle, has_menu=False, dpi=0):
            # without a DPI, the system DPI is used: 96
            border = (dpi or 96) // 12
            return x - border, y - border * 3, w + border * 2, h + border * 4

        for dpi, current, default_position, expected in (
            # created at 96 DPI and landed on a 96 DPI monitor: nothing to do
            (96, (92, 4, 656, 512), False, None),
            # same DPI, but clamped by the size constraints (ie: OpenGL texture size limit): leave it
            (96, (92, 4, 500, 512), False, None),
            # landed on a 192 DPI monitor: the frame is too thin
            (192, (92, 4, 656, 512), False, (84, -20, 672, 544)),
            # the OS chose the position: keep it
            (192, (300, 200, 656, 512), True, (300, 200, 672, 544)),
            # `GetDpiForWindow` is not available, or the window is not Per-Monitor v2
            (0, (92, 4, 656, 512), False, None),
        ):
            with self.subTest(dpi=dpi, default_position=default_position):
                window = SimpleNamespace(style=win32con.WS_OVERLAPPEDWINDOW, x=-1, y=-1, width=1, height=1)
                calls = []

                def get_window_rect(hwnd, rect):
                    r = rect._obj
                    r.left, r.top = current[:2]
                    r.right, r.bottom = current[0] + current[2], current[1] + current[3]
                    return True

                with (patch.object(native, "get_frame_dpi", lambda hwnd: dpi),
                      patch.object(native, "system_geometry", frame),
                      patch.object(native, "GetWindowRect", get_window_rect),
                      patch.object(native, "SetWindowPos", lambda hwnd, after, *geom: calls.append(geom[:4]))):
                    native.ClientWindow.fit_frame_to_dpi(window, 1, 0, (100, 28, 640, 480), default_position)
                self.assertEqual(calls, [expected] if expected else [])

    def test_dpi_scaled_size(self) -> None:
        import win32con
        from ctypes import addressof
        from ctypes.wintypes import SIZE
        from xpra.client.win32 import window as native

        def frame(x, y, w, h, style, exstyle, has_menu=False, dpi=0):
            border = (dpi or 96) // 12
            return x - border, y - border * 3, w + border * 2, h + border * 4

        def client_rect(hwnd, rect):
            rect._obj.right, rect._obj.bottom = 640, 480
            return True

        window = SimpleNamespace(style=win32con.WS_OVERLAPPEDWINDOW)
        for dpi, expected, size in (
            # the client area keeps its size in physical pixels, only the frame is scaled:
            (192, True, (640 + 32, 480 + 64)),
            (144, True, (640 + 24, 480 + 48)),
            # unknown DPI: let the OS scale it
            (0, False, (0, 0)),
        ):
            with self.subTest(dpi=dpi):
                buf = SIZE()
                with (patch.object(native, "GetClientRect", client_rect),
                      patch.object(native, "GetWindowLongW", lambda hwnd, index: 0),
                      patch.object(native, "system_geometry", frame)):
                    handled = native.ClientWindow.get_dpi_scaled_size(window, 1, dpi, addressof(buf))
                self.assertEqual(handled, expected)
                self.assertEqual((buf.cx, buf.cy), size)

    def test_dpi_changed(self) -> None:
        from ctypes import addressof
        from xpra.client.win32 import window as native
        from xpra.platform.win32.common import RECT

        for minimized, expected in (
            (False, [(10, 20, 690, 540)]),
            # don't move a minimized window, but still check the DPI:
            (True, []),
        ):
            with self.subTest(minimized=minimized):
                rect = RECT(10, 20, 700, 560)
                display = Mock()
                window = SimpleNamespace(minimized=minimized, get_subsystem={"display": display}.get)
                calls = []
                with patch.object(native, "SetWindowPos", lambda hwnd, after, *geom: calls.append(geom[:4])):
                    native.ClientWindow.dpi_changed(window, 1, 192, addressof(rect))
                self.assertEqual(calls, expected)
                display.screen_size_changed.assert_called_once_with()

    def test_map_drawable_geometry(self) -> None:
        from xpra.client.win32 import window as native

        # At 2x, widths 200 and 201 both round to 100 server pixels.
        # At 0.5x, height 50 could have come from 99 or 100 server pixels.
        display = SimpleNamespace(cx=lambda w: round(w / 2), cy=lambda h: round(h * 2))
        for origin_ok, rect_ok, size, expected in (
            (True, True, (201, 50), (201, 50, 100, 99)),
            (False, True, (210, 60), (210, 60, 105, 120)),
            (True, False, (210, 60), (200, 50, 100, 99)),
            (None, True, (210, 60), (210, 60, 105, 120)),
            (True, None, (210, 60), (200, 50, 100, 99)),
            (True, True, (210, 0), (200, 50, 100, 99)),
        ):
            with self.subTest(origin_ok=origin_ok, rect_ok=rect_ok, size=size):
                window = Mock(hwnd=1, x=20, y=30, width=200, height=50, _backing_size=(100, 99),
                              clamp_backing_size=lambda size: size)
                window.get_subsystem.return_value = display
                window.is_OR.return_value = True

                def origin(hwnd, point):
                    if origin_ok is None:
                        raise OSError()
                    point._obj.x, point._obj.y = -40, 70
                    return origin_ok

                def client_rect(hwnd, rect):
                    if rect_ok is None:
                        raise OSError()
                    rect._obj.right, rect._obj.bottom = size
                    return rect_ok

                with patch.object(native, "ClientToScreen", origin), patch.object(native, "GetClientRect", client_rect):
                    native.ClientWindow.window_created(window)
                window.backing.init.assert_called_once_with(*expected)
                self.assertEqual((window.width, window.height), expected[:2])
                self.assertEqual((window.x, window.y), (-40, 70) if origin_ok else (20, 30))
                window.emit.assert_called_once_with("mapped")

    def test_no_display_scaling(self) -> None:
        window, sent = self.make_window({})
        window.send_configure()
        self.assertEqual(sent[0][2]["geometry"], (20, 40, 200, 100))
        self.assertEqual(sent[0][2]["monitor"], {"index": 1, "position": (10, 20)})

    def test_readonly(self) -> None:
        # the server would ignore it:
        window, sent = self.make_window({"display": Display()}, readonly=True)
        window.send_configure()
        self.assertEqual(sent, [])
        self.assertEqual(window.state_updates, {})


@unittest.skipUnless(WIN32, "the win32 client is only available on MS Windows")
class Win32OpenGLSizeTest(unittest.TestCase):
    """
    The backing of an OpenGL window is a texture,
    it cannot be larger than the maximum texture size: 16384 here.
    """

    def setUp(self) -> None:
        self.windows = []

    def tearDown(self) -> None:
        for window in self.windows:
            # the native window is never created:
            window.hwnd = 0
            window.cleanup_class()

    def make_window(self, scale: float, size, backing_size, max_window_size=(0, 0)):
        from xpra.util.objects import typedict
        GLClientWindow = import_opengl_window().GLClientWindow
        sent = []
        subsystems = {
            "display": scaled_display(scale),
            "window": SimpleNamespace(send=lambda *packet: sent.append(packet)),
        }
        wid = len(self.windows) + 1
        # an override-redirect window, which Windows does not clamp to the maximum track size:
        window = GLClientWindow(subsystems.get, lambda: False, None, wid, (20, 40, *size), backing_size, typedict(),
                                True, {}, None, max_window_size, 32, None)
        self.windows.append(window)
        window.update_client_properties = Mock()
        window.get_monitor_position = dict
        return window, sent

    def test_max_window_size(self) -> None:
        for scale, max_window_size, expected in (
            (1, (0, 0), (16384, 16384)),
            # 16384 server pixels round to 3277 and 6554 window pixels, which convert back to 16385:
            (0.2, (0, 0), (3276, 3276)),
            (0.4, (0, 0), (6553, 6553)),
            # the configured limit is in window pixels:
            (0.4, (1000, 0), (1000, 6553)),
        ):
            with self.subTest(scale=scale, max_window_size=max_window_size):
                window, _ = self.make_window(scale, (100, 100), (100, 100), max_window_size)
                self.assertEqual(window.max_window_size, expected)

    def test_window_created(self) -> None:
        from xpra.client.win32 import window as native
        # at 0.5, 16385 server pixels are shown as 8192 window pixels, which is within the window size limit:
        window, sent = self.make_window(0.5, (8192, 50), (16385, 100))
        self.assertEqual(window.max_window_size, (8192, 8192))
        window.hwnd = 1
        window.backing = Backing((16385, 100))

        def client_rect(_hwnd, rect):
            rect._obj.right, rect._obj.bottom = 8192, 50
            return True

        with (patch.object(native, "ClientToScreen", lambda hwnd, point: False),
              patch.object(native, "GetClientRect", client_rect)):
            window.window_created()
        self.assertEqual(window.backing.inits, [(8192, 50, 16384, 100)])
        window.send_configure()
        self.assertEqual(sent[0][2]["geometry"][2:], (16384, 100))

    def test_move_resize(self) -> None:
        import win32con
        from xpra.client.win32.window_state import handle_size
        for scale, size, request, server_size, client_size, expected, configures in (
            # Windows does not clamp an override-redirect window:
            (1, (1000, 100), (20000, 100), (20000, 100), (16384, 100), (16384, 100), 1),
            # the window size does not change, so there is no `WM_SIZE` and no "resized" signal:
            (1, (16384, 100), (20000, 100), (20000, 100), (16384, 100), (16384, 100), 1),
            # at 0.5, 16385 server pixels fit in the 8192 window pixels limit, but not in the backing:
            (0.5, (8192, 50), (8192, 50), (16385, 100), (8192, 50), (16384, 100), 1),
            # within the limits:
            (1, (1000, 100), (2000, 100), (2000, 100), (2000, 100), (2000, 100), 1),
            (1, (1000, 100), (1000, 100), (1000, 100), (1000, 100), (1000, 100), 0),
        ):
            with self.subTest(scale=scale, size=size, server_size=server_size):
                display = scaled_display(scale)
                backing_size = display.cx(size[0]), display.cy(size[1])
                window, sent = self.make_window(scale, size, backing_size)
                window.hwnd = 1
                window.backing = Backing(backing_size)
                # the client sends a `window-configure` when the window is resized:
                window.connect("resized", lambda w: w.send_configure())
                sizes = []

                def set_window_pos(_hwnd, _after, _x, _y, w, h, _flags):
                    sizes.append((w, h))
                    handle_size(window, win32con.SIZE_RESTORED, w, h)

                with native_patches(set_window_pos):
                    window.move_resize(window.x, window.y, *request, 5, server_size)
                self.assertEqual(sizes, [client_size])
                self.assertEqual(window.backing.size, expected)
                self.assertEqual(len(sent), configures)
                if configures:
                    self.assertEqual(sent[0][2]["geometry"][2:], expected)

    def test_window_classes(self) -> None:
        from xpra.util.objects import typedict
        from xpra.client.win32.client import XpraWin32Client
        from xpra.client.win32.window import ClientWindow
        gl_window_class = object()
        for size, force, expected in (
            ((3276, 3276), False, (gl_window_class, ClientWindow)),
            # too large for OpenGL, use a GDI window:
            ((3277, 100), False, (ClientWindow, )),
            ((100, 3277), False, (ClientWindow, )),
            ((3277, 100), True, (gl_window_class, ClientWindow)),
        ):
            with self.subTest(size=size, force=force):
                gl = SimpleNamespace(GLClientWindowClass=gl_window_class, enabled=True, force=force,
                                     get_max_window_size=lambda: (3276, 3276))
                client = SimpleNamespace(get_subsystem={"opengl": gl}.get)
                classes = XpraWin32Client.get_client_window_classes(client, (0, 0, *size), typedict(), False)
                self.assertEqual(tuple(classes), expected)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
