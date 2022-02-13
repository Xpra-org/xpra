# This file is part of Xpra.
# Copyright (C) 2012-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from libc.stdint cimport uintptr_t, uint8_t

ctypedef long vpx_img_fmt_t
ctypedef void vpx_codec_iface_t


cdef extern from "vpx/vpx_codec.h":
    ctypedef const void *vpx_codec_iter_t
    ctypedef long vpx_codec_flags_t
    ctypedef int vpx_codec_err_t
    ctypedef struct vpx_codec_ctx_t:
        pass
    const char *vpx_codec_error(vpx_codec_ctx_t  *ctx)
    vpx_codec_err_t vpx_codec_destroy(vpx_codec_ctx_t *ctx)
    const char *vpx_codec_version_str()
    const char *vpx_codec_build_config()
    vpx_codec_err_t vpx_codec_control_(vpx_codec_ctx_t *ctx, int ctrl_id, int value)
    const char *vpx_codec_err_to_string(vpx_codec_err_t err)

cdef extern from "vpx/vpx_image.h":
    cdef int VPX_IMG_FMT_I420
    cdef int VPX_IMG_FMT_I444
    cdef int VPX_IMG_FMT_I44416
    cdef int VPX_IMG_FMT_HIGHBITDEPTH
    ctypedef struct vpx_image_t:
        unsigned int w
        unsigned int h
        unsigned int d_w
        unsigned int d_h
        vpx_img_fmt_t fmt
        vpx_color_space_t cs
        vpx_color_range_t range
        unsigned char *planes[4]
        int stride[4]
        int bps
        unsigned int x_chroma_shift
        unsigned int y_chroma_shift

    ctypedef enum vpx_color_space_t:
        VPX_CS_UNKNOWN
        VPX_CS_BT_601
        VPX_CS_BT_709
        VPX_CS_SMPTE_170
        VPX_CS_SMPTE_240
        VPX_CS_BT_2020
        VPX_CS_RESERVED
        VPX_CS_SRGB

    ctypedef enum vpx_color_range_t:
        VPX_CR_STUDIO_RANGE
        VPX_CR_FULL_RANGE
