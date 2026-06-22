#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gc
import os
import unittest
from unittest.mock import patch

from xpra.codecs.constants import (
    CodecSpec,
    get_profile,
    get_subsampling_divs,
    get_x264_preset,
    get_x264_quality,
)
from xpra.util.objects import typedict


class Codec:
    pass


class CodecConstantsTest(unittest.TestCase):

    def test_pixel_format_and_x264_boundaries(self):
        self.assertEqual(get_subsampling_divs("YUV420P10"), ((1, 1), (2, 2), (2, 2)))
        with self.assertRaises(ValueError):
            get_subsampling_divs("invalid")
        self.assertEqual(get_x264_quality(100, "high444"), 0)
        self.assertEqual(get_x264_quality(-1), 50)
        self.assertEqual(get_x264_preset(100), 0)
        self.assertGreater(get_x264_preset(0), get_x264_preset(99))

    def test_profile_precedence(self):
        options = typedict({"h264.YUV420P.profile": "specific", "h264.profile": "general"})
        self.assertEqual(get_profile(options), "specific")
        with patch.dict(os.environ, {"XPRA_H264_YUV420P_PROFILE": "environment"}, clear=False):
            self.assertEqual(get_profile(typedict()), "environment")

    def test_codec_spec_lifecycle_and_serialization(self):
        spec = CodecSpec(codec_class=Codec, codec_type="test", max_instances=2)
        self.assertEqual(spec.get_runtime_factor(), 1.0)
        instance = spec.make_instance()
        self.assertEqual(spec.get_instance_count(), 1)
        self.assertEqual(spec.get_runtime_factor(), 0.75)
        data = spec.to_dict("codec_class")
        self.assertNotIn("instances", data)
        self.assertNotIn("codec_class", data)
        second = spec.make_instance()
        self.assertEqual(spec.get_runtime_factor(), 0)
        del instance, second
        gc.collect()
        self.assertEqual(spec.get_instance_count(), 0)


if __name__ == "__main__":
    unittest.main()
