#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from xpra.util.objects import typedict
from xpra.net.packet_type import WINDOW_ICON
from xpra.server.window import windowicon
from xpra.server.window.windowicon import WindowIconSource

ICON_48 = (48, 48, "png", b"icon-48")
ICON_64 = (64, 64, "png", b"icon-64")
ICON_256 = (256, 256, "png", b"icon-256")
FALLBACK = (32, 32, "png", b"fallback")


class FakeWindow:

    def __init__(self, icons=(), wm_class=("plain.py", "plain.py"), default_icons=None):
        self.props = {"icons": icons, "class-instance": wm_class}
        self.default_icons = default_icons or {}
        self.default_icon_sizes = []

    def get_property(self, prop):
        return self.props[prop]

    def get_default_window_icon(self, size):
        self.default_icon_sizes.append(size)
        return self.default_icons.get(size)


class IconSource(WindowIconSource):

    def __init__(self, window, encodings=("png", ), **icon_caps):
        super().__init__(encodings, typedict(icon_caps))
        self.window = window
        self.wid = 1
        self.suspended = False
        self.batch_config = SimpleNamespace(delay_per_megapixel=1000)
        self.packets = []

    def queue_packet(self, packet, wait_for_more=False):
        self.packets.append(packet)


class WindowIconTest(unittest.TestCase):

    def setUp(self):
        self.timers = []
        self.lookups = []

        def timeout_add(delay, fn, *args):
            self.timers.append((delay, fn))
            return len(self.timers)

        def get_default_window_icon(size, wmclass_name):
            self.lookups.append((size, wmclass_name))
            return self.default_icon

        self.default_icon = None
        glib = SimpleNamespace(timeout_add=timeout_add, source_remove=lambda _timer: None)
        for target, attr, value in (
                (windowicon, "GLib", glib),
                (windowicon, "get_default_window_icon", get_default_window_icon),
                (windowicon, "check_main_thread", lambda: None),
                (WindowIconSource, "fallback_window_icon", FALLBACK),
                (windowicon, "default_icon_cache", {}),
        ):
            patcher = patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_choose_icon(self):
        choose = WindowIconSource.choose_icon
        self.assertIsNone(choose([]))
        self.assertEqual(choose([ICON_48, ICON_64, ICON_256]), ICON_256)
        self.assertEqual(choose([ICON_48, ICON_64, ICON_256], 128, 128), ICON_64)
        # the limits are exclusive:
        self.assertEqual(choose([ICON_48, ICON_64], 64, 64), ICON_48)
        self.assertIsNone(choose([ICON_256], 128, 128))

    def test_window_icon_is_scheduled(self):
        source = IconSource(FakeWindow(icons=(ICON_48, ICON_256)))
        source.send_window_icon()
        # 256x256 exceeds the default max size of 64x64:
        self.assertEqual(source.window_icon_data, ICON_48)
        self.assertEqual(len(self.timers), 1)
        self.assertEqual(self.timers[0][0], 50)
        self.assertEqual(self.lookups, [])
        # only one timer for consecutive updates:
        source.send_window_icon()
        self.assertEqual(len(self.timers), 1)

    def test_oversized_icon_is_used_when_nothing_else_fits(self):
        source = IconSource(FakeWindow(icons=(ICON_256, )))
        source.send_window_icon()
        self.assertEqual(source.window_icon_data, ICON_256)

    def test_suspended_or_no_png(self):
        for source in (
                IconSource(FakeWindow(icons=(ICON_48, )), encodings=()),
                IconSource(FakeWindow(icons=(ICON_48, ))),
        ):
            source.suspended = bool(source.has_png)
            source.send_window_icon()
            self.assertIsNone(source.window_icon_data)
            self.assertEqual(self.timers, [])

    def test_client_has_theme_icon(self):
        source = IconSource(FakeWindow(), **{"default.icons": ("plain.py", )})
        source.send_window_icon()
        self.assertIsNone(source.window_icon_data)
        self.assertEqual(source.window.default_icon_sizes, [])
        self.assertEqual(self.lookups, [])

    def test_model_default_icon(self):
        window = FakeWindow(default_icons={48: ICON_48})
        source = IconSource(window, size=(32, 32), max_size=(64, 64))
        source.send_window_icon()
        self.assertEqual(window.default_icon_sizes, [32, 64, 48])
        self.assertEqual(source.window_icon_data, ICON_48)
        self.assertEqual(self.lookups, [])

    def test_wmclass_default_icon(self):
        self.default_icon = ICON_48
        source = IconSource(FakeWindow())
        source.send_window_icon()
        self.assertEqual(self.lookups, [(48, "plain.py")])
        self.assertEqual(source.window_icon_data, ICON_48)

    def test_wmclass_lookups_are_cached(self):
        self.default_icon = ICON_48
        for _ in range(2):
            IconSource(FakeWindow()).send_window_icon()
        # misses are cached too:
        self.default_icon = None
        for _ in range(2):
            IconSource(FakeWindow(wm_class=("other", "other"))).send_window_icon()
        self.assertEqual(self.lookups, [(48, "plain.py"), (48, "other")])
        windowicon.clear_default_icon_cache()
        self.default_icon = ICON_64
        source = IconSource(FakeWindow())
        source.send_window_icon()
        self.assertEqual(self.lookups[-1], (48, "plain.py"))
        self.assertEqual(source.window_icon_data, ICON_64)

    def test_no_wmclass(self):
        self.default_icon = ICON_48
        source = IconSource(FakeWindow(wm_class=()))
        source.send_window_icon()
        self.assertEqual(self.lookups, [])
        self.assertIsNone(source.window_icon_data)

    def test_no_icon_not_greedy(self):
        source = IconSource(FakeWindow())
        source.send_window_icon()
        self.assertIsNone(source.window_icon_data)
        self.assertEqual(self.timers, [])
        self.assertEqual(source.packets, [])

    def test_no_icon_greedy_with_default(self):
        source = IconSource(FakeWindow(), encodings=("png", "default"), greedy=True)
        source.send_window_icon()
        self.assertEqual(source.packets, [(WINDOW_ICON, 1, 0, 0, "default", b"")])
        self.assertIsNone(source.window_icon_data)
        self.assertEqual(self.timers, [])

    def test_no_icon_greedy_fallback(self):
        source = IconSource(FakeWindow(), greedy=True)
        source.send_window_icon()
        self.assertEqual(source.window_icon_data, FALLBACK)
        self.assertEqual(len(self.timers), 1)


class ThemeIconLookupTest(unittest.TestCase):

    def lookup(self, filename="", theme_icon=None, loaded=None, theme_loaded=None, fallback=None):
        calls = []

        def record(name, value):
            def fn(*args):
                calls.append((name, ) + args)
                return value
            return fn

        with (
            patch.object(windowicon, "find_theme_icon", record("find", (filename, theme_icon))),
            patch.object(windowicon, "load_icon_file", record("file", loaded)),
            patch.object(windowicon, "load_theme_icon", record("theme", theme_loaded)),
            patch.object(windowicon, "do_get_default_window_icon", record("fallback", fallback)),
        ):
            icon = windowicon.get_default_window_icon(48, "app")
        return icon, [call[0] for call in calls]

    def test_raster_theme_icon(self):
        icon, calls = self.lookup("/icons/app.png", "info", loaded=ICON_48)
        self.assertEqual(icon, ICON_48)
        self.assertEqual(calls, ["find", "file"])

    def test_svg_theme_icon(self):
        icon, calls = self.lookup("/icons/app.svg", "info", theme_loaded=ICON_64)
        self.assertEqual(icon, ICON_64)
        self.assertEqual(calls, ["find", "theme"])

    def test_raster_file_fails_to_load(self):
        icon, calls = self.lookup("/resource/app.png", "info", theme_loaded=ICON_64)
        self.assertEqual(icon, ICON_64)
        self.assertEqual(calls, ["find", "file", "theme"])

    def test_not_in_theme(self):
        icon, calls = self.lookup(fallback=ICON_48)
        self.assertEqual(icon, ICON_48)
        self.assertEqual(calls, ["find", "fallback"])

    def test_nothing_found(self):
        icon, calls = self.lookup("/icons/app.png", "info")
        self.assertIsNone(icon)
        self.assertEqual(calls, ["find", "file", "theme", "fallback"])


class DefaultWindowIconTest(unittest.TestCase):

    def setUp(self):
        if not windowicon.POSIX or windowicon.OSX:
            self.skipTest("posix only")

    def test_scaled_to_requested_size(self):
        from xpra.platform.paths import get_icon_filename
        filename = get_icon_filename("xpra.png")
        if not filename or not os.path.exists(filename):
            self.skipTest("xpra.png icon not found")
        with patch("xpra.platform.posix.menu_helper.find_icon", lambda *_names: filename):
            icon = windowicon.do_get_default_window_icon(37, "xpra")
        self.assertIsNotNone(icon)
        w, h, coding, data = icon
        self.assertEqual((w, h, coding), (37, 37, "png"))
        self.assertEqual(Image.open(BytesIO(data)).size, (37, 37))

    def test_not_found(self):
        with patch("xpra.platform.posix.menu_helper.find_icon", lambda *_names: ""):
            self.assertIsNone(windowicon.do_get_default_window_icon(48, "no-such-icon"))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
