# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Minimal H.264 Annex-B parser, just enough to recover the colour range
(the VUI `video_full_range_flag`) from a bitstream.

Some decoder libraries (ie: openh264) do not expose this flag through their API,
but the SPS is present in the bitstream we feed them, so we can parse it ourselves.
"""

from xpra.common import SizedBuffer
from xpra.log import Logger

log = Logger("encoding")

NAL_SPS = 7
# VCL NAL unit types (coded slices); the SPS always precedes these:
VCL_NAL_TYPES = (1, 2, 3, 4, 5)

# profiles which carry the chroma_format_idc block in the SPS:
HIGH_PROFILES = (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 144)


class BitReader:
    """ reads bits from an H.264 RBSP, skipping emulation-prevention bytes (00 00 03) """

    def __init__(self, data: SizedBuffer):
        self.data = memoryview(data)
        self.size = len(self.data)
        self.byte_pos = 0
        self.bit_pos = 0
        self.zeros = 0

    def read_bit(self) -> int:
        if self.byte_pos >= self.size:
            return 0
        if self.zeros >= 2 and self.data[self.byte_pos] == 0x03:
            # emulation prevention byte:
            self.byte_pos += 1
            self.zeros = 0
            if self.byte_pos >= self.size:
                return 0
        b = self.data[self.byte_pos]
        bit = (b >> (7 - self.bit_pos)) & 1
        self.bit_pos += 1
        if self.bit_pos == 8:
            self.zeros = self.zeros + 1 if b == 0 else 0
            self.byte_pos += 1
            self.bit_pos = 0
        return bit

    def read_bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self.read_bit()
        return v

    def read_ue(self) -> int:
        # exp-golomb unsigned:
        zeros = 0
        while self.read_bit() == 0 and zeros < 32:
            zeros += 1
        return ((1 << zeros) - 1) + self.read_bits(zeros)

    def read_se(self) -> int:
        # exp-golomb signed:
        ue = self.read_ue()
        if ue & 1:
            return (ue + 1) // 2
        return -(ue // 2)


def _skip_scaling_list(br: BitReader, size: int) -> None:
    last_scale = 8
    next_scale = 8
    for _ in range(size):
        if next_scale != 0:
            delta = br.read_se()
            next_scale = (last_scale + delta + 256) % 256
        last_scale = last_scale if next_scale == 0 else next_scale


def parse_sps_full_range(rbsp: SizedBuffer) -> bool | None:
    """
    Parse an H.264 SPS RBSP (without the 1-byte NAL header) and return its
    VUI `video_full_range_flag`, or None if the SPS carries no video signal type.
    """
    br = BitReader(rbsp)
    profile_idc = br.read_bits(8)
    br.read_bits(8)                     # constraint_set flags + reserved
    br.read_bits(8)                     # level_idc
    br.read_ue()                        # seq_parameter_set_id
    if profile_idc in HIGH_PROFILES:
        chroma_format_idc = br.read_ue()
        if chroma_format_idc == 3:
            br.read_bit()               # separate_colour_plane_flag
        br.read_ue()                    # bit_depth_luma_minus8
        br.read_ue()                    # bit_depth_chroma_minus8
        br.read_bit()                   # qpprime_y_zero_transform_bypass_flag
        if br.read_bit():               # seq_scaling_matrix_present_flag
            count = 8 if chroma_format_idc != 3 else 12
            for i in range(count):
                if br.read_bit():       # seq_scaling_list_present_flag[i]
                    _skip_scaling_list(br, 16 if i < 6 else 64)
    br.read_ue()                        # log2_max_frame_num_minus4
    pic_order_cnt_type = br.read_ue()
    if pic_order_cnt_type == 0:
        br.read_ue()                    # log2_max_pic_order_cnt_lsb_minus4
    elif pic_order_cnt_type == 1:
        br.read_bit()                   # delta_pic_order_always_zero_flag
        br.read_se()                    # offset_for_non_ref_pic
        br.read_se()                    # offset_for_top_to_bottom_field
        for _ in range(br.read_ue()):   # num_ref_frames_in_pic_order_cnt_cycle
            br.read_se()
    br.read_ue()                        # max_num_ref_frames
    br.read_bit()                       # gaps_in_frame_num_value_allowed_flag
    br.read_ue()                        # pic_width_in_mbs_minus1
    br.read_ue()                        # pic_height_in_map_units_minus1
    if not br.read_bit():               # frame_mbs_only_flag
        br.read_bit()                   # mb_adaptive_frame_field_flag
    br.read_bit()                       # direct_8x8_inference_flag
    if br.read_bit():                   # frame_cropping_flag
        br.read_ue()                    # frame_crop_left_offset
        br.read_ue()                    # frame_crop_right_offset
        br.read_ue()                    # frame_crop_top_offset
        br.read_ue()                    # frame_crop_bottom_offset
    if not br.read_bit():               # vui_parameters_present_flag
        return None
    if br.read_bit():                   # aspect_ratio_info_present_flag
        if br.read_bits(8) == 255:      # aspect_ratio_idc == Extended_SAR
            br.read_bits(16)            # sar_width
            br.read_bits(16)            # sar_height
    if br.read_bit():                   # overscan_info_present_flag
        br.read_bit()                   # overscan_appropriate_flag
    if not br.read_bit():               # video_signal_type_present_flag
        return None
    br.read_bits(3)                     # video_format
    return bool(br.read_bit())          # video_full_range_flag


def iter_annexb_nals(data: SizedBuffer):
    """ yield (nal_unit_type, payload memoryview) for each NAL in an Annex-B stream """
    mv = memoryview(data)
    n = len(mv)
    i = 0
    nal_start = -1
    while i + 2 < n:
        if mv[i] == 0 and mv[i + 1] == 0 and mv[i + 2] == 1:
            if nal_start >= 0:
                end = i
                while end > nal_start and mv[end - 1] == 0:  # trim trailing zero byte(s)
                    end -= 1
                yield mv[nal_start] & 0x1f, mv[nal_start + 1:end]
            nal_start = i + 3
            i = nal_start
        else:
            i += 1
    if nal_start >= 0:
        yield mv[nal_start] & 0x1f, mv[nal_start + 1:n]


def get_video_full_range(data: SizedBuffer) -> bool | None:
    """
    Return the colour range signalled by the first SPS in an H.264 Annex-B stream,
    or None if there is no SPS (ie: a non-keyframe) or it carries no video signal type.
    """
    try:
        for nal_type, payload in iter_annexb_nals(data):
            if nal_type == NAL_SPS:
                return parse_sps_full_range(payload)
            if nal_type in VCL_NAL_TYPES:
                break                   # the SPS always precedes the coded slices
    except Exception as e:
        log("get_video_full_range(%i bytes) parsing failed: %s", len(data), e)
    return None
