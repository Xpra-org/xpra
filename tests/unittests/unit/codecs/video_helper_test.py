#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.codecs import video


class VideoHelperTest(unittest.TestCase):

    def test_module_discovery(self):
        with patch.object(video, "find_spec", return_value=None):
            self.assertFalse(video.has_codec_module("missing"))
        with patch.object(video, "find_spec", return_value=object()):
            self.assertTrue(video.has_codec_module("present"))
        with patch.object(video, "find_spec", side_effect=ImportError):
            self.assertFalse(video.has_codec_module("broken"))

    def test_filter_and_option_parsing(self):
        result = video.filt("enc", "encoders", ("x264:quality=80", "no-vpx", "unknown"),
                            lambda: ["enc_x264", "enc_vpx"], ("x264", "vpx"))
        self.assertEqual(result, {"enc_x264": {"quality": "80"}})
        self.assertEqual(video.parse_video_option("enc_x264"), ("enc_x264", {}))
        self.assertEqual(video.parse_video_option("enc_x264:speed=50"), ("enc_x264", {"speed": "50"}))
        self.assertEqual(video.filt("enc", "encoders", ("none",), list, ()), {})

    def test_clone_gpu_and_module_initialization(self):
        spec = SimpleNamespace(gpu_cost=10, cpu_cost=1)
        original = {"h264": {"YUV420P": [spec]}}
        clone = video.deepish_clone_dict(original)
        self.assertEqual(clone, original)
        self.assertIsNot(clone["h264"]["YUV420P"], original["h264"]["YUV420P"])
        self.assertEqual(video.get_gpu_options({"RGB": {"YUV420P": [spec]}}), {"RGB": [spec]})
        module = Mock()
        with patch.object(video, "load_codec", side_effect=(module, None, RuntimeError("bad"))):
            modules = video.init_modules("enc", {"x264": {}, "vpx": {}, "openh264": {}})
        self.assertEqual(modules, {"enc_x264": module})

    def test_csc_modes(self):
        decoder = SimpleNamespace(codec_type="decoder", encoding="h264", input_colorspace="YUV420P",
                                  output_colorspaces=("RGB",))
        converter = SimpleNamespace(codec_type="csc", input_colorspace="YUV444P", output_colorspaces=("RGB",))
        helper = video.VideoHelper()
        helper.decoder_modules = {"decoder": SimpleNamespace(get_specs=lambda: [decoder])}
        helper.csc_modules = {"csc": SimpleNamespace(get_specs=lambda: [converter])}
        self.assertEqual(helper.get_server_full_csc_modes("RGB"), {"h264": ["YUV420P"]})
        self.assertEqual(helper.get_server_full_csc_modes_for_rgb("RGB"), {"h264": ["YUV420P"]})


if __name__ == "__main__":
    unittest.main()
