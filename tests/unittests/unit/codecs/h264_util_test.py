#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import typedict
from xpra.codecs import loader
from xpra.codecs.checks import make_test_image
from xpra.codecs.h264_util import get_pic_order_cnt_type, get_video_full_range
from xpra.codecs.constants import ColorRange


class BitWriter:

    def __init__(self):
        self.bits: list[int] = []

    def u(self, n: int, value: int) -> None:
        self.bits += [(value >> (n - 1 - i)) & 1 for i in range(n)]

    def ue(self, value: int) -> None:
        code = value + 1
        self.u(code.bit_length() * 2 - 1, code)

    def se(self, value: int) -> None:
        self.ue(2 * value - 1 if value > 0 else -2 * value)

    def nal(self, header: int) -> bytes:
        # rbsp trailing bits, then pad to a byte:
        bits = self.bits + [1]
        bits += [0] * (-len(bits) % 8)
        data = bytes(int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8))
        return b"\x00\x00\x00\x01" + bytes((header, )) + data


def make_sps(profile_idc: int, pic_order_cnt_type: int, scaling_matrix=False, full_range=None) -> bytes:
    w = BitWriter()
    w.u(8, profile_idc)
    w.u(8, 0)                   # constraint flags
    w.u(8, 40)                  # level_idc
    w.ue(0)                     # seq_parameter_set_id
    if profile_idc == 100:
        w.ue(1)                 # chroma_format_idc
        w.ue(0)                 # bit_depth_luma_minus8
        w.ue(0)                 # bit_depth_chroma_minus8
        w.u(1, 0)               # qpprime_y_zero_transform_bypass_flag
        w.u(1, int(scaling_matrix))
        if scaling_matrix:
            # the first list is present with a single non-zero delta, the others are not:
            w.u(1, 1)
            w.se(1)
            for _ in range(15):
                w.se(0)
            for _ in range(7):
                w.u(1, 0)
    w.ue(0)                     # log2_max_frame_num_minus4
    w.ue(pic_order_cnt_type)
    if pic_order_cnt_type == 0:
        w.ue(4)                 # log2_max_pic_order_cnt_lsb_minus4
    elif pic_order_cnt_type == 1:
        w.u(1, 0)
        w.se(-1)
        w.se(2)
        w.ue(2)
        w.se(3)
        w.se(-4)
    w.ue(1)                     # max_num_ref_frames
    w.u(1, 0)                   # gaps_in_frame_num_value_allowed_flag
    w.ue(119)                   # pic_width_in_mbs_minus1
    w.ue(67)                    # pic_height_in_map_units_minus1
    w.u(1, 1)                   # frame_mbs_only_flag
    w.u(1, 1)                   # direct_8x8_inference_flag
    w.u(1, 0)                   # frame_cropping_flag
    w.u(1, int(full_range is not None))
    if full_range is not None:
        w.u(1, 0)               # aspect_ratio_info_present_flag
        w.u(1, 0)               # overscan_info_present_flag
        w.u(1, 1)               # video_signal_type_present_flag
        w.u(3, 5)               # video_format
        w.u(1, int(full_range))
    return w.nal(0x67)


# a coded slice, which never carries an SPS:
SLICE = b"\x00\x00\x00\x01\x41\x9a\x00\x10"


class PicOrderCntTypeTest(unittest.TestCase):

    def test_types(self):
        for profile_idc in (66, 77, 100):
            for pic_order_cnt_type in (0, 1, 2):
                stream = make_sps(profile_idc, pic_order_cnt_type) + b"\x00\x00\x00\x01\x68\xce\x38\x80" + SLICE
                self.assertEqual(get_pic_order_cnt_type(stream), pic_order_cnt_type,
                                 f"wrong type for profile {profile_idc}")

    def test_scaling_matrix(self):
        self.assertEqual(get_pic_order_cnt_type(make_sps(100, 2, scaling_matrix=True)), 2)
        self.assertEqual(get_pic_order_cnt_type(make_sps(100, 0, scaling_matrix=True)), 0)

    def test_full_range_still_parsed(self):
        # the colour range parser reads the same start of the SPS:
        for pic_order_cnt_type in (0, 1, 2):
            for full_range, expected in ((True, ColorRange.FULL), (False, ColorRange.STUDIO)):
                sps = make_sps(100, pic_order_cnt_type, full_range=full_range)
                self.assertEqual(get_video_full_range(sps), expected)
            self.assertEqual(get_video_full_range(make_sps(66, pic_order_cnt_type)), ColorRange.UNKNOWN)

    def test_no_sps(self):
        self.assertEqual(get_pic_order_cnt_type(b""), -1)
        self.assertEqual(get_pic_order_cnt_type(SLICE), -1)
        # the SPS must come before the slices:
        self.assertEqual(get_pic_order_cnt_type(SLICE + make_sps(66, 2)), -1)

    def test_truncated_sps(self):
        self.assertEqual(get_pic_order_cnt_type(b"\x00\x00\x00\x01\x67"), -1)
        self.assertEqual(get_pic_order_cnt_type(b"\x00\x00\x00\x01\x67\x42\x00\x28"), -1)

    def test_encoders(self):
        w, h = 128, 128
        tested = []
        for enc_name in ("enc_x264", "enc_openh264"):
            enc_mod = loader.load_codec(enc_name)
            if not enc_mod:
                continue
            encoder = enc_mod.Encoder()
            encoder.init_context("h264", w, h, "YUV420P", typedict({"dst-formats": ["YUV420P"]}))
            try:
                data = encoder.compress_image(make_test_image("YUV420P", w, h), typedict())[0]
            finally:
                encoder.clean()
            self.assertIn(get_pic_order_cnt_type(data), (0, 1, 2), f"{enc_name} stream not parsed")
            tested.append(enc_name)
        if not tested:
            self.skipTest("no H.264 encoder available")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
