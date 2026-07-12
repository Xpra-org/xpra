#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.client.subsystem import encoding


class EncodingSeccompTest(unittest.TestCase):

    @staticmethod
    def assert_decoder_exclusions(testcase: unittest.TestCase, filtered: tuple[str, ...]) -> None:
        testcase.assertGreaterEqual(len(filtered), 3)
        testcase.assertEqual(filtered[0], "all")
        testcase.assertEqual(set(filtered[1:]), {"no-nvdec", "no-vpl"})

    def test_load_all_codecs_avoids_hardware_decode(self):
        helper = SimpleNamespace(set_modules=lambda **kwargs: None, init=lambda: None)
        client = SimpleNamespace(
            allowed_encodings=("jpeg", "webp", "jph"),
            video_decoders=("all",),
            csc_modules=(),
        )
        client.filter_video_decoder_options = lambda: ("all", "no-nvdec", "no-vpl")
        with patch.object(encoding, "load_codec") as load_codec, \
             patch.object(encoding, "getVideoHelper", return_value=helper), \
             patch("xpra.seccomp.is_enabled", return_value=True):
            # `do_load_all_codecs` holds the actual loading logic; `load_all_codecs`
            # is just the once-only lock/event wrapper around it:
            encoding.Encodings.do_load_all_codecs(client)
        loaded = [call.args[0] for call in load_codec.call_args_list]
        self.assertIn("dec_jpeg", loaded)
        self.assertIn("dec_webp", loaded)
        self.assertIn("dec_jph", loaded)
        self.assertNotIn("dec_nvjpeg", loaded)
        self.assertNotIn("nvdec", loaded)

    def test_filter_video_decoder_options(self):
        client = SimpleNamespace(video_decoders=("all", "no-vpl"))
        with patch("xpra.seccomp.is_enabled", return_value=True):
            filtered = encoding.Encodings.filter_video_decoder_options(client)
        self.assert_decoder_exclusions(self, filtered)


if __name__ == "__main__":
    unittest.main()
