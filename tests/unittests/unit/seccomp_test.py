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
from xpra.seccomp import parse as seccomp_parse
from xpra.seccomp import rfb as seccomp_rfb


class SeccompTest(unittest.TestCase):

    @staticmethod
    def assert_decoder_exclusions(testcase: unittest.TestCase, filtered: tuple[str, ...]) -> None:
        testcase.assertGreaterEqual(len(filtered), 3)
        testcase.assertEqual(filtered[0], "all")
        testcase.assertEqual(set(filtered[1:]), {"no-nvdec", "no-vpl"})

    def test_filter_video_decoder_options(self):
        with patch.object(seccomp, "LINUX", True), \
             patch.object(seccomp, "ENABLED", True), \
             patch.object(seccomp, "is_available", return_value=True):
            filtered = encoding.Encodings.filter_video_decoder_options(type("C", (), {"video_decoders": ("all", "no-vpl")})())
        self.assert_decoder_exclusions(self, filtered)

    def test_install_draw_thread_noop_when_disabled(self):
        with patch.object(seccomp, "is_enabled", return_value=False):
            self.assertFalse(seccomp_draw.install_thread())

    def test_install_parse_thread_noop_when_disabled(self):
        with patch.object(seccomp_parse, "is_enabled", return_value=False):
            self.assertFalse(seccomp_parse.install_thread())

    def test_parse_syscalls_superset_of_draw(self):
        self.assertTrue(set(seccomp_draw.DRAW_SYSCALLS).issubset(set(seccomp_parse.PARSE_SYSCALLS)))
        self.assertIn("recvfrom", seccomp_parse.PARSE_SYSCALLS)

    def test_install_rfb_read_thread_noop_when_disabled(self):
        with patch.object(seccomp_rfb, "is_enabled", return_value=False):
            self.assertFalse(seccomp_rfb.install_thread())

    def test_rfb_syscalls_match_parse(self):
        self.assertEqual(seccomp_rfb.RFB_SYSCALLS, seccomp_parse.PARSE_SYSCALLS)


if __name__ == "__main__":
    unittest.main()
