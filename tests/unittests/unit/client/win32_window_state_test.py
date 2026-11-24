#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The minimized / maximized state of the win32 client windows, driven by `WM_MOVE` and `WM_SIZE`:
which signals are emitted (and therefore which packets are sent) and which state updates they carry.
"""

import unittest

try:
    from xpra.client.win32.window_state import (
        handle_move, handle_size, MINIMIZED_POSITION,
        SIZE_RESTORED, SIZE_MINIMIZED, SIZE_MAXIMIZED, SIZE_MAXSHOW, SIZE_MAXHIDE,
    )
except ImportError:
    handle_move = handle_size = None


class FakeWindow:

    def __init__(self, x=100, y=50, width=640, height=480, backing=True):
        self.hwnd = 1
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.backing = backing
        self.minimized = False
        self.maximized = False
        self.state_updates = {}
        self.signals = []
        self.backing_sizes = []

    def emit(self, signal: str) -> None:
        # the client consumes the state updates when it sends the packet for the signal:
        self.signals.append((signal, self.state_updates))
        self.state_updates = {}

    def update_backing_render_size(self, width: int, height: int) -> None:
        self.backing_sizes.append((width, height))

    def move(self, x: int, y: int) -> bool:
        return handle_move(self, x, y)

    def size(self, wparam: int, width: int, height: int) -> bool:
        return handle_size(self, wparam, width, height)

    def minimize(self) -> None:
        # the message sequence `ShowWindow(SW_MINIMIZE)` produces:
        assert self.move(MINIMIZED_POSITION, MINIMIZED_POSITION)
        assert self.size(SIZE_MINIMIZED, 0, 0)


@unittest.skipIf(handle_size is None, "win32 client not available")
class Win32WindowStateTest(unittest.TestCase):

    def test_maximize_and_restore(self):
        w = FakeWindow()
        assert not w.size(SIZE_MAXIMIZED, 1920, 1080)
        assert w.maximized
        assert w.backing_sizes == [(1920, 1080)]
        assert (w.width, w.height) == (1920, 1080)
        # the state goes with the new geometry, in the same `window-configure`:
        assert w.signals == [("resized", {"maximized": True})]
        w.signals = []
        assert not w.size(SIZE_RESTORED, 640, 480)
        assert not w.maximized
        assert w.backing_sizes[-1] == (640, 480)
        assert w.signals == [("resized", {"maximized": False})]

    def test_maximize_same_size(self):
        w = FakeWindow(width=1920, height=1080)
        w.size(SIZE_MAXIMIZED, 1920, 1080)
        assert not w.backing_sizes
        assert w.signals == [("maximized", {"maximized": True})]

    def test_maximize_without_backing(self):
        w = FakeWindow(backing=None)
        w.size(SIZE_MAXIMIZED, 1920, 1080)
        assert not w.backing_sizes
        assert w.signals == [("maximized", {"maximized": True})]

    def test_resize(self):
        w = FakeWindow()
        w.size(SIZE_RESTORED, 800, 600)
        assert w.signals == [("resized", {})]
        w.signals = []
        # nothing changed, nothing to send:
        w.size(SIZE_RESTORED, 800, 600)
        assert not w.signals

    def test_server_maximized(self):
        # `set_metadata()` sets the state before calling `ShowWindow`, so it is not echoed back:
        w = FakeWindow()
        w.maximized = True
        w.size(SIZE_MAXIMIZED, 1920, 1080)
        assert w.signals == [("resized", {})]

    def test_move(self):
        w = FakeWindow()
        assert not w.move(200, 300)
        assert (w.x, w.y) == (200, 300)
        assert w.signals == [("moved", {})]

    def test_move_before_hwnd(self):
        # the `WM_MOVE` sent from within `CreateWindowExW`, before the window is mapped:
        w = FakeWindow()
        w.hwnd = 0
        assert not w.move(200, 300)
        assert not w.signals

    def test_minimize(self):
        w = FakeWindow()
        w.minimize()
        assert w.minimized
        # only one `window-unmap`, and the minimized position and size are not recorded:
        assert w.signals == [("minimized", {"iconified": True})]
        assert (w.x, w.y, w.width, w.height) == (100, 50, 640, 480)
        assert not w.backing_sizes

    def test_restore_from_minimized(self):
        w = FakeWindow()
        w.minimize()
        w.signals = []
        # `WM_MOVE` comes first: the `map-window` that follows carries the position
        assert not w.move(100, 50)
        assert not w.signals
        w.size(SIZE_RESTORED, 640, 480)
        assert not w.minimized
        assert w.signals == [("mapped", {"iconified": False})]
        # minimizing it again must unmap it again:
        w.signals = []
        w.minimize()
        assert w.signals == [("minimized", {"iconified": True})]

    def test_restore_from_minimized_resized(self):
        w = FakeWindow()
        w.minimize()
        w.signals = []
        w.move(10, 20)
        w.size(SIZE_RESTORED, 800, 600)
        assert (w.x, w.y) == (10, 20)
        assert w.backing_sizes == [(800, 600)]
        # a single `map-window` with the new geometry, not followed by a `window-configure`:
        assert w.signals == [("mapped", {"iconified": False})]

    def test_restore_from_minimized_to_maximized(self):
        w = FakeWindow()
        w.size(SIZE_MAXIMIZED, 1920, 1080)
        w.minimize()
        assert w.maximized
        w.signals = []
        # Windows restores it straight back to maximized, with the same size as before:
        w.size(SIZE_MAXIMIZED, 1920, 1080)
        assert w.maximized and not w.minimized
        assert w.signals == [("mapped", {"iconified": False})]
        w.signals = []
        w.size(SIZE_RESTORED, 640, 480)
        assert w.signals == [("resized", {"maximized": False})]

    def test_maximize_from_minimized(self):
        w = FakeWindow()
        w.minimize()
        w.signals = []
        w.size(SIZE_MAXIMIZED, 1920, 1080)
        assert w.signals == [("mapped", {"maximized": True, "iconified": False})]

    def test_other_windows_maximized(self):
        w = FakeWindow()
        for wparam in (SIZE_MAXSHOW, SIZE_MAXHIDE):
            assert w.size(wparam, 1920, 1080)
        assert not w.signals
        assert not w.maximized

    def test_unexpected(self):
        w = FakeWindow()
        assert not w.size(0x10, 1920, 1080)
        assert not w.signals
        assert (w.width, w.height) == (640, 480)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
