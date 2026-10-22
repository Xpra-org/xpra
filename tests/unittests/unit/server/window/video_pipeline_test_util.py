# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from types import SimpleNamespace
from unittest.mock import Mock

from xpra.codecs.constants import CSCSpec, VideoSpec
from xpra.util.objects import typedict


class UnusedCodec:
    def __init__(self):
        raise AssertionError("pipeline selection must not instantiate codecs")


def encoder_spec(codec_type="encoder", **kwargs) -> VideoSpec:
    return VideoSpec(codec_class=UnusedCodec, codec_type=codec_type, encoding="h264",
                     output_colorspaces=("YUV420P", "YUV444P", "RGB"), **kwargs)


def csc_spec(codec_type="csc", **kwargs) -> CSCSpec:
    return CSCSpec(codec_class=UnusedCodec, codec_type=codec_type, **kwargs)


def make_source(encoders=None, converters=None):
    # Only the source adapter tests need the full window implementation.
    from xpra.server.window.video_compress import WindowVideoSource
    source = WindowVideoSource.__new__(WindowVideoSource)
    encoders = {"h264": {"RGB": (encoder_spec(),)}} if encoders is None else encoders
    converters = {} if converters is None else converters
    source.video_helper = Mock()
    source.video_helper.get_encoder_specs.side_effect = lambda encoding: encoders.get(encoding, {})
    source.video_helper.get_csc_specs.side_effect = lambda src_format: converters
    source._current_quality = 50
    source._fixed_min_quality = 0
    source._current_speed = 50
    source._fixed_min_speed = 0
    source.content_types = ()
    source.is_shadow = False
    source.video_max_size = (4096, 4096)
    source.video_subregion = None
    source.full_csc_modes = typedict({"h264": ("YUV420P", "YUV444P", "RGB")})
    source.encoding_options = typedict()
    source._csc_encoder = None
    source._video_encoder = None
    source.matches_video_subregion = Mock(return_value=None)
    source.subregion_is_video = Mock(return_value=False)
    source.get_video_fps = Mock(return_value=20)
    source.is_cancelled = Mock(return_value=False)
    source.calculate_scaling = Mock(return_value=(1, 1))
    source.last_pipeline_params = ("old",)
    source.last_pipeline_scores = ("old",)
    source.last_pipeline_time = 10
    return source


def current_encoder(spec, width=640, height=480, src_format="RGB"):
    return SimpleNamespace(get_type=lambda: spec.codec_type, get_src_format=lambda: src_format,
                           get_width=lambda: width, get_height=lambda: height)


def current_csc(spec, width=640, height=480, dst_format="YUV420P"):
    return SimpleNamespace(get_type=lambda: spec.codec_type, get_dst_format=lambda: dst_format,
                           get_src_width=lambda: width, get_src_height=lambda: height)
