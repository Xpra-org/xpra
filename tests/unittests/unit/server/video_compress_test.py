#!/usr/bin/env python3

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server.window.compress import WindowSource
from xpra.server.window.video_compress import WindowVideoSource
from xpra.util.objects import typedict


class NonVideoEncodingsTest(unittest.TestCase):

    def test_client_properties_exclude_unregistered_encodings(self):
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.common_encodings = ("jpeg",)
        source.core_encodings = ("jpeg",)
        source.picture_encodings = ("jpeg", "webp")
        source._encoders = {"jpeg": Mock()}
        source.scroll_min_percent = 0
        source.scroll_preference = 100
        source.video_subregion = SimpleNamespace(supported=True)
        source.scaling_control = 0
        source.edge_encoding = ""
        source.full_csc_modes = typedict()

        def set_core_encodings(window_source, properties) -> None:
            window_source.core_encodings = properties.strtupleget("encodings.core", ())

        properties = typedict({"encodings.core": ("jpeg", "webp")})
        with patch.object(WindowSource, "do_set_client_properties", set_core_encodings):
            source.do_set_client_properties(properties)

        self.assertEqual(source.non_video_encodings, ("jpeg",))


class ScalingCacheTest(unittest.TestCase):

    def test_candidate_limits_override_generic_scaling(self):
        source = WindowVideoSource.__new__(WindowVideoSource)
        source.video_helper = Mock()
        source.video_helper.get_csc_specs.return_value = {}
        encoder_spec = SimpleNamespace(
            can_scale=True,
            codec_type="test",
            max_w=2048,
            max_h=2048,
            output_colorspaces=("RGB",),
        )
        source.video_helper.get_encoder_specs.return_value = {"RGB": (encoder_spec,)}
        source._current_quality = source._current_speed = 50
        source._fixed_min_quality = source._fixed_min_speed = 0
        source.content_types = ()
        source.is_shadow = False
        source.video_max_size = (4096, 4096)
        source.video_subregion = None
        source.full_csc_modes = typedict({"h264": ("RGB",)})
        source.encoding_options = typedict()
        source._csc_encoder = source._video_encoder = None
        source.matches_video_subregion = Mock(return_value=None)
        source.get_video_fps = Mock(return_value=0)
        source.is_cancelled = Mock(return_value=False)
        source.calculate_scaling = Mock(side_effect=((1, 1), (2, 3)))

        with patch("xpra.server.window.video_compress.get_pipeline_score", return_value=(1,)) as score:
            source.get_video_pipeline_options(("h264",), 3000, 2000, "RGB")

        self.assertEqual(
            tuple(call.args for call in source.calculate_scaling.call_args_list),
            ((3000, 2000, 4096, 4096), (3000, 2000, 2048, 2048)),
        )
        self.assertEqual(score.call_args.args[5], (2, 3))


if __name__ == "__main__":
    unittest.main()
