#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.codecs.codec_constants import video_spec
from xpra.server.window import window_video_source
from xpra.server.window.window_video_source import WindowVideoSource
from xpra.util import typedict


class VideoQualitySelectionTest(unittest.TestCase):

    def test_subsampling_inside_the_encoder_is_lossy(self):
        encoder = video_spec(
            encoding="h264", input_colorspace="BGRX", output_colorspaces=(), has_lossless_mode=False,
            codec_class=object, codec_type="test",
        )
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.video_helper = Mock()
        source.video_helper.get_encoder_specs.return_value = {"BGRX": (encoder,)}
        source.video_helper.get_csc_specs.return_value = {}
        source._fixed_min_quality = 0
        source._current_speed = 50
        source._fixed_min_speed = 0
        source.video_max_size = (4096, 4096)
        source.video_subregion = None
        source.full_csc_modes = typedict({"h264": ("NV12", "YUV420P", "YUV422P", "YUV444P")})
        source.encoding_options = typedict()
        source._csc_encoder = None
        source._video_encoder = None
        source.matches_video_subregion = Mock(return_value=None)
        source.get_video_fps = Mock(return_value=0)
        source.is_cancelled = Mock(return_value=False)
        with patch.multiple(window_video_source, FORCE_CSC=False, PREFERRED_ENCODING_ORDER=("h264",)):
            for output_colorspaces, text, quality, shadow, penalty in (
                (("YUV420P",), True, 50, False, None),
                (("NV12",), True, 50, False, None),
                (("YUV422P",), True, 50, False, None),
                (("YUV420P",), False, 100, False, 0),
                (("YUV420P",), False, 50, True, -40),
                (("YUV420P", "YUV422P"), False, 50, True, -40),
                (("YUV420P",), False, 50, False, 0),
                (("YUV444P",), True, 100, True, 0),
                (("YUV420P", "YUV444P"), True, 100, True, 0),
            ):
                with self.subTest(output_colorspaces=output_colorspaces, text=text, quality=quality, shadow=shadow):
                    encoder.output_colorspaces = output_colorspaces
                    source.content_type = "text" if text else ""
                    source._current_quality = quality
                    source.is_shadow = shadow
                    with patch.object(window_video_source, "get_pipeline_score", return_value=(1,)) as scorer:
                        scores = source.get_video_pipeline_options(("h264",), 128, 128, "BGRX")
                    if penalty is None:
                        scorer.assert_not_called()
                        self.assertEqual(scores, ())
                    else:
                        scorer.assert_called_once()
                        self.assertEqual(scorer.call_args.args[12], penalty)
                        self.assertEqual(scores, ((1,),))


if __name__ == '__main__':
    unittest.main()
