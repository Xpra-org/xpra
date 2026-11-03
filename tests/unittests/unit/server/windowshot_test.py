#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from xpra.codecs.image import ImageWrapper
from xpra.codecs.screenshot import make_windowshot_packet
from xpra.net.constants import ConnectionMessage
from xpra.net.packet_type import DISPLAY_SCREENSHOT
from xpra.server.subsystem.display import DisplayManager
from xpra.server.subsystem.window import WindowServer
from xpra.util.objects import typedict


def model(title="Terminal", xid=None, image=None, managed=True):
    properties = {"title": title, "geometry": (30, 40, 2, 2)}
    if xid is not None:
        properties["xid"] = xid
    return Mock(is_managed=Mock(return_value=managed),
                get_property_names=Mock(return_value=tuple(properties)),
                get_property=Mock(side_effect=properties.__getitem__),
                get_image=Mock(return_value=image))


class WindowSelectorTest(unittest.TestCase):

    def setUp(self):
        self.windows = WindowServer()
        self.first = model("Terminal: shell", 0x123)
        self.second = model("123", 0x456)
        self.native = model("Native Wayland")
        self.windows._id_to_window = {1: self.first, 2: self.second, 3: self.native,
                                      4: model("Gone", 0x789, managed=False)}

    def test_selectors(self):
        for selector, expected in (("1", self.first), ("wid:1", self.first), ("0001", self.first),
                                   ("0x123", self.first), ("xid:0x123", self.first), ("xid:291", self.first),
                                   ("0X123", self.first), ("xid:0X123", self.first),
                                   ("shell", self.first), ("Terminal: shell", self.first),
                                   ("name:123", self.second), ("name:Native", self.native)):
            with self.subTest(selector=selector):
                self.assertIs(self.windows.find_window(selector), expected)

    def test_missing_or_unmanaged(self):
        for selector in ("123", "99", "0x999", "4", "0x789", "Gone", "terminal"):
            with self.subTest(selector=selector), self.assertRaisesRegex(ValueError, "no managed window"):
                self.windows.find_window(selector)

    def test_invalid(self):
        for selector in ("", "wid:", "xid:", "name:", "wid:no", "xid:no", "0xno", "wid:0x1",
                         "wid:-1", "xid:-1", "wid:0", "xid:0", "wid: 1"):
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                self.windows.find_window(selector)

    def test_ambiguous_titles(self):
        self.windows._id_to_window[5] = model("Terminal: editor")
        for selector in ("Terminal", "name:Terminal"):
            with self.subTest(selector=selector), self.assertRaisesRegex(ValueError, "ambiguous") as cm:
                self.windows.find_window(selector)
            for candidate in ("wid:1", "wid:5", "Terminal: shell", "Terminal: editor"):
                self.assertIn(candidate, str(cm.exception))
        self.windows._id_to_window[5] = model("Terminal: shell")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.windows.find_window("Terminal: shell")


class WindowshotTest(unittest.TestCase):

    def setUp(self):
        self.network = Mock()
        self.server = SimpleNamespace(hello_request_handlers={}, subsystems={"network": self.network})
        self.windows = WindowServer(self.server)
        self.server.subsystems["window"] = self.windows
        self.display = DisplayManager(self.server)
        self.proto = Mock()

    def request(self, selector="1"):
        handler = self.server.hello_request_handlers["windowshot"]
        self.assertTrue(handler(self.proto, typedict({"window": selector})))

    def test_pixels_and_borrowed_buffer(self):
        for fmt in ("RGB", "BGR", "RGBX", "XRGB", "BGRX", "RGBA", "ARGB", "BGRA"):
            with self.subTest(fmt=fmt):
                # Distinct colors in both rows, with padding that must not become pixels.
                colors = ((10, 20, 30, 40), (50, 60, 70, 80), (90, 100, 110, 120), (130, 140, 150, 160))
                packed = [bytes(dict(zip("RGBAX", (*color, 255)))[c] for c in fmt) for color in colors]
                stride = 2 * len(fmt) + 4
                pixels = packed[0] + packed[1] + b"\xff" * 4 + packed[2] + packed[3] + b"\xff" * 4
                image = ImageWrapper(0, 0, 2, 2, (pixels,), fmt, 32 if "A" in fmt else 24, stride, len(fmt))
                window = model(image=image)
                self.windows._id_to_window = {1: window}
                self.proto.reset_mock()
                self.request()
                self.network.send_disconnect.assert_not_called()
                window.get_image.assert_called_once_with(0, 0, 2, 2)
                packet = self.proto.send_now.call_args.args[0]
                self.assertEqual(tuple(packet[:5]), (DISPLAY_SCREENSHOT, 2, 2, "png", 8))
                with Image.open(io.BytesIO(packet[5].data)) as png:
                    self.assertEqual(png.format, "PNG")
                    self.assertEqual(png.size, (2, 2))
                    expected = colors if "A" in fmt else tuple(color[:3] for color in colors)
                    self.assertEqual([png.getpixel((x, y)) for y in range(2) for x in range(2)], list(expected))
                self.assertFalse(image.freed)
                self.assertIs(image.get_plane(0), pixels)
                self.assertEqual(image.get_rowstride(), stride)

    def test_selection_failures(self):
        for selector in ("", "wid:no", "123"):
            with self.subTest(selector=selector):
                self.network.reset_mock()
                self.request(selector)
                self.proto.send_now.assert_not_called()
                args = self.network.send_disconnect.call_args.args
                self.assertEqual(args[:2], (self.proto, ConnectionMessage.SERVER_ERROR))
                self.assertIn("windowshot failed", args[2])

    def test_server_without_windows(self):
        del self.server.subsystems["window"]
        self.request()
        self.proto.send_now.assert_not_called()
        self.assertIn("does not manage windows", self.network.send_disconnect.call_args.args[2])

    def test_wayland_model_keeps_its_image(self):
        from xpra.wayland.server.models.window import Window
        image = ImageWrapper(0, 0, 2, 2, (b"\xff\0\0\xff" * 4,), "RGBA", 32, 8)
        window = Window({"title": "Wayland", "geometry": (0, 0, 2, 2), "image": image})
        window.setup()
        self.windows._id_to_window = {1: window}
        # Repeated capture must leave the compositor's buffer usable.
        for _ in range(2):
            self.request("Wayland")
            self.network.send_disconnect.assert_not_called()
            self.assertIs(window.get_image(0, 0, 2, 2), image)
            self.assertFalse(image.freed)
        self.assertEqual(self.proto.send_now.call_count, 2)

    def test_capture_failures(self):
        for managed, geometry, error in ((False, (0, 0, 2, 2), "no longer managed"),
                                         (True, (0, 0, 0, 2), "no pixel area"),
                                         (True, (0, 0, 2, 2), "no pixels available")):
            with self.subTest(error=error):
                window = model(managed=managed)
                window.get_property.side_effect = lambda _name, g=geometry: g
                self.network.reset_mock()
                with patch.object(WindowServer, "find_window", return_value=window):
                    self.request()
                self.proto.send_now.assert_not_called()
                self.assertIn(error, self.network.send_disconnect.call_args.args[2])

    def test_unexpected_capture_error(self):
        window = model()
        window.get_image.side_effect = RuntimeError("capture failed")
        self.windows._id_to_window = {1: window}
        with patch("xpra.server.subsystem.display.log"):
            self.request()
        self.proto.send_now.assert_not_called()
        self.assertIn("cannot capture window pixels", self.network.send_disconnect.call_args.args[2])

    def test_unsupported_pixels(self):
        image = ImageWrapper(0, 0, 2, 2, (b"\0" * 16,), "r210", 30, 8)
        with self.assertRaisesRegex(ValueError, "unsupported window pixel format"):
            make_windowshot_packet(image)
        self.assertFalse(image.freed)

    def test_x11_capture_releases_image(self):
        from xpra.x11.subsystem.display import X11DisplayManager
        for fail in (False, True):
            with self.subTest(fail=fail):
                image = ImageWrapper(0, 0, 2, 2, (b"\0" * 16,), "BGRX", 24, 8)
                display = X11DisplayManager(self.server)
                window = model(image=image)
                with patch("xpra.x11.subsystem.display.xsync") as sync:
                    try:
                        with display.windowshot_image(window) as captured:
                            self.assertIs(captured, image)
                            if fail:
                                raise RuntimeError("encoding failed")
                    except RuntimeError:
                        self.assertTrue(fail)
                    sync.__enter__.assert_called_once()
                    sync.__exit__.assert_called_once()
                self.assertTrue(image.freed)


if __name__ == "__main__":
    unittest.main()
