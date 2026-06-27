#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra import seccomp
from xpra.client.subsystem import encoding
from xpra.seccomp import draw as seccomp_draw


class SeccompTest(unittest.TestCase):

    def test_filter_video_decoder_options(self):
        with patch.object(seccomp, "LINUX", True), \
             patch.object(seccomp, "ENABLED", True), \
             patch.object(seccomp, "is_available", return_value=True):
            filtered = encoding.Encodings.filter_video_decoder_options(type("C", (), {"video_decoders": ("all", "no-vpl")})())
        self.assertEqual(filtered, ("all", "no-vpl", "no-nvdec"))

    def test_install_draw_thread_noop_when_disabled(self):
        with patch.object(seccomp, "is_enabled", return_value=False):
            self.assertFalse(seccomp_draw.install_thread())


if __name__ == "__main__":
    unittest.main()
