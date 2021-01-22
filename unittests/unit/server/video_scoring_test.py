#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.server.window.video_scoring import (
    get_quality_score, get_speed_score,
    get_pipeline_score, get_encoder_dimensions,
    )


class TestVideoScoring(unittest.TestCase):

    def test_quality_score(self):
        csc_spec = AdHocStruct()
        csc_spec.quality = 50
        encoder_spec = AdHocStruct()
        encoder_spec.quality = 50
        encoder_spec.has_lossless_mode = False
        s1 = get_quality_score("YUV420P", csc_spec, encoder_spec, (1, 1))
        s2 = get_quality_score("BGRA", csc_spec, encoder_spec, (1, 1))
        assert s2>s1
        encoder_spec.has_lossless_mode = True
        s3 = get_quality_score("BGRA", csc_spec, encoder_spec, (1, 1))
        assert s3>s2
        s4 = get_quality_score("YUV420P", csc_spec, encoder_spec, (1, 1), min_quality=50)
        assert s4<s1
        s5 = get_quality_score("YUV420P", csc_spec, encoder_spec, (2, 2))
        assert s5>s2

    def test_speed_score(self):
        csc_spec = AdHocStruct()
        csc_spec.speed = 50
        encoder_spec = AdHocStruct()
        encoder_spec.speed = 50
        encoder_spec.has_lossless_mode = True
        s1 = get_speed_score("YUV420P", csc_spec, encoder_spec, (1, 1))
        s2 = get_speed_score("YUV420P", csc_spec, encoder_spec, (2, 2))
        assert s2>s1
        s3 = get_speed_score("YUV420P", csc_spec, encoder_spec, (1, 1), min_speed=60)
        assert s3<s2

    def test_pipeline_score(self):
        MINW = 32
        MINH = 32
        MAXW = 3840
        MAXH = 2160
        encoder_spec = AdHocStruct()
        encoder_spec.width_mask = 0xfffe
        encoder_spec.height_mask = 0xfffe
        encoder_spec.quality = 100
        encoder_spec.speed = 100
        encoder_spec.size_efficiency = 50
        encoder_spec.min_w = MINW
        encoder_spec.max_w = MAXW
        encoder_spec.min_h = MINH
        encoder_spec.max_h = MAXH
        encoder_spec.setup_cost = 10
        encoder_spec.score_boost = 0
        encoder_spec.gpu_cost = 0
        encoder_spec.cpu_cost = 10
        encoder_spec.codec_type = "test codec"
        test_csc_spec = AdHocStruct()
        test_csc_spec.width_mask = 0xffff
        test_csc_spec.height_mask = 0xffff
        test_csc_spec.score_boost = 0
        test_csc_spec.quality = 10
        test_csc_spec.speed = 20
        test_csc_spec.setup_cost = 10
        test_csc_spec.get_runtime_factor = lambda : 10
        test_csc_spec.codec_class = AdHocStruct
        current_csc = AdHocStruct()
        current_csc.get_dst_format = lambda : "BGRA"
        current_csc.get_src_height = lambda : 1080
        current_csc.get_src_width = lambda : 1920
        for rgb_format in ("BGRA", "RGB"):
            for csc_spec in (None, test_csc_spec):
                for can_scale in (True, False):
                    test_csc_spec.can_scale = can_scale
                    encoder_spec.can_scale = can_scale
                    for has_lossless_mode in (True, False):
                        encoder_spec.has_lossless_mode = has_lossless_mode
                        for scaling in ((1, 1), (2, 3)):
                            #too small:
                            for w, h in ((MINW-1, MINH+1), (MINW+1, MINH-1)):
                                s = get_pipeline_score(rgb_format, csc_spec, encoder_spec,
                                               w, h, scaling,
                                               100, 10,
                                               100, 10,
                                               None, None,
                                               0, 10, True)
                                assert s is None

                            s = get_pipeline_score(rgb_format, csc_spec, encoder_spec,
                                           1920, 1080, scaling,
                                           100, 10,
                                           100, 10,
                                           current_csc, None,
                                           0, 10, True)
                            if can_scale is False and scaling!=(1, 1):
                                assert s is None
                                continue
                            #mask will round down, so this should be OK:
                            s = get_pipeline_score(rgb_format, csc_spec, encoder_spec,
                                           MAXW+1, MAXH+1, scaling,
                                           100, 10,
                                           100, 10,
                                           None, None,
                                           0, 10, True)
                            assert s
                            if scaling==(1, 1):
                                #but this is not:
                                s = get_pipeline_score(rgb_format, csc_spec, encoder_spec,
                                               MAXW+2, MAXH+2, scaling,
                                               100, 10,
                                               100, 10,
                                               None, None,
                                               0, 10, True)
                                assert s is None

    def test_encoder_dimensions(self):
        encoder_spec = AdHocStruct()
        encoder_spec.width_mask = 0xfffe
        encoder_spec.height_mask = 0xfffe
        w, h = get_encoder_dimensions(encoder_spec, 101, 101)
        assert w==100 and h==100
        encoder_spec = AdHocStruct()
        encoder_spec.width_mask = 0xfffe
        encoder_spec.height_mask = 0xfffe
        w, h = get_encoder_dimensions(encoder_spec, 102, 102, (1, 2))
        assert w==50 and h==50


def main():
    unittest.main()

if __name__ == '__main__':
    main()
