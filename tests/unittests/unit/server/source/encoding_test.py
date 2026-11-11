#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.server.source.encoding import EncodingsConnection
from xpra.util.objects import typedict


class EncodingConnectionTest(unittest.TestCase):

    @staticmethod
    def parse(caps: dict) -> EncodingsConnection:
        source = EncodingsConnection()
        source.init_state()
        source.window_sources = {}
        source.scaling_control = None
        source.default_quality = source.default_min_quality = source.default_speed = source.default_min_speed = -1
        c = typedict(caps)
        source.parse_encoding_caps(c, typedict(c.dictget("encoding")))
        return source

    def test_auto_refresh_delay(self):
        encoding = {"core": ("rgb24", "png", "jpeg"), "rgb_formats": ("BGRX", ), "setting": "auto"}
        self.assertEqual(self.parse({"encoding": encoding}).auto_refresh_delay, 0)
        self.assertEqual(self.parse({"encoding": encoding | {"auto_refresh_delay": 150}}).auto_refresh_delay, 150)
        # the namespaced value takes precedence over the legacy top-level one:
        caps = {"encoding": encoding | {"auto_refresh_delay": 150}, "auto_refresh_delay": 500}
        self.assertEqual(self.parse(caps).auto_refresh_delay, 150)
        legacy = {"encoding": encoding, "auto_refresh_delay": 500}
        with patch("xpra.server.source.encoding.BACKWARDS_COMPATIBLE", True):
            self.assertEqual(self.parse(legacy).auto_refresh_delay, 500)
        with patch("xpra.server.source.encoding.BACKWARDS_COMPATIBLE", False):
            self.assertEqual(self.parse(legacy).auto_refresh_delay, 0)
        # the `encoding-config` packet sent after the handshake does not include it:
        source = self.parse({"encoding": encoding | {"auto_refresh_delay": 150}})
        source.parse_encoding_caps(typedict(), typedict(encoding))
        self.assertEqual(source.auto_refresh_delay, 150)
        # an explicit zero still disables auto-refresh:
        source.parse_encoding_caps(typedict(), typedict(encoding | {"auto_refresh_delay": 0}))
        self.assertEqual(source.auto_refresh_delay, 0)

    def test_late_encodings_reach_existing_windows(self):
        for context in (None, object()):
            for window_context in (None, object()):
                with self.subTest(context=context, window_context=window_context):
                    source = EncodingsConnection()
                    source.init_state()
                    source.cuda_device_context = context
                    source.encodings = ("rgb", "h264")
                    source.core_encodings = ("rgb24", "h264")
                    source.rgb_formats = ("RGB", "BGRX")
                    window = SimpleNamespace(
                        cuda_device_context=window_context,
                        server_encodings=("rgb",), server_core_encodings=("rgb24",),
                        encodings=("rgb",), core_encodings=("rgb24",), rgb_formats=("RGB",),
                    )
                    source.window_sources = {1: window}
                    server = SimpleNamespace(encodings=("rgb", "h264"), core_encodings=("rgb24", "h264"))
                    with patch.object(source, "wants_cuda_device", return_value=False):
                        source.reinit_encodings(server)
                    self.assertEqual(window.server_encodings, server.encodings)
                    self.assertEqual(window.server_core_encodings, server.core_encodings)
                    self.assertEqual(window.encodings, source.encodings)
                    self.assertEqual(window.core_encodings, source.core_encodings)
                    self.assertEqual(window.rgb_formats, source.rgb_formats)
                    self.assertIs(window.cuda_device_context, window_context or context)


if __name__ == "__main__":
    unittest.main()
