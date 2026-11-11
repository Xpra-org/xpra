#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.server.source.encodings import EncodingsMixin
from xpra.util import typedict


class EncodingConnectionTest(unittest.TestCase):

    @staticmethod
    def parse(caps):
        source = EncodingsMixin()
        source.init_state()
        source.window_sources = {}
        source.scaling_control = None
        source.server_encodings = ()
        source.default_quality = source.default_min_quality = source.default_speed = source.default_min_speed = -1
        source.parse_encoding_caps(typedict(caps))
        return source

    def test_auto_refresh_delay(self):
        self.assertEqual(self.parse({}).auto_refresh_delay, 0)
        self.assertEqual(self.parse({"auto_refresh_delay": 500}).auto_refresh_delay, 500)
        for caps in (
                {"encoding": {"": "auto", "auto_refresh_delay": 150}},
                {"encoding.auto_refresh_delay": 150},
        ):
            with self.subTest(caps=caps):
                self.assertEqual(self.parse(caps).auto_refresh_delay, 150)
                # The namespaced value takes precedence over the legacy one:
                caps = dict(caps, auto_refresh_delay=500)
                source = self.parse(caps)
                self.assertEqual(source.auto_refresh_delay, 150)
                # Later encoding packets do not include the refresh delay:
                source.parse_encoding_caps(typedict({"encoding": {"": "auto", "quality": 80}}))
                self.assertEqual(source.auto_refresh_delay, 150)
                # An explicit zero still disables auto-refresh:
                source.parse_encoding_caps(typedict({"encoding": {"": "auto", "auto_refresh_delay": 0}}))
                self.assertEqual(source.auto_refresh_delay, 0)
                source.parse_encoding_caps(typedict({"auto_refresh_delay": 500}))
                self.assertEqual(source.auto_refresh_delay, 500)
                source.parse_encoding_caps(typedict({"encoding.auto_refresh_delay": 0}))
                self.assertEqual(source.auto_refresh_delay, 0)
                source.parse_encoding_caps(typedict({"auto_refresh_delay": 500}))
                source.parse_encoding_caps(typedict())
                self.assertEqual(source.auto_refresh_delay, 500)
                source.parse_encoding_caps(typedict({"auto_refresh_delay": 0}))
                self.assertEqual(source.auto_refresh_delay, 0)


if __name__ == "__main__":
    unittest.main()
