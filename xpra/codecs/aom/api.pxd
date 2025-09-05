# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, initializedcheck=False, cdivision=True, always_allow_keywords=False

from libc.stdint cimport uint8_t, uint32_t, int64_t


ctypedef long aom_codec_caps_t
ctypedef long aom_codec_flags_t
ctypedef int64_t aom_codec_pts_t
ctypedef uint32_t aom_codec_frame_flags_t


cdef extern from "aom/aom_image.h":
    ctypedef enum aom_img_fmt_t:
        AOM_IMG_FMT_NONE
        AOM_IMG_FMT_I420
        AOM_IMG_FMT_I422
        AOM_IMG_FMT_I444
        AOM_IMG_FMT_YV12
        AOM_IMG_FMT_AOMYV12
        AOM_IMG_FMT_AOMI420
        # AOM_IMG_FMT_NV12
        AOM_IMG_FMT_I42016
        AOM_IMG_FMT_YV1216
        AOM_IMG_FMT_I42216
        AOM_IMG_FMT_I44416
        AOM_IMG_FMT_PLANAR

    ctypedef enum aom_color_primaries:
        AOM_CICP_CP_UNSPECIFIED
        AOM_CICP_CP_BT_709
        AOM_CICP_CP_BT_470M
        AOM_CICP_CP_BT_470BG
        AOM_CICP_CP_SMPTE_170M
        AOM_CICP_CP_SMPTE_240M
        AOM_CICP_CP_FILM
        AOM_CICP_CP_BT_2020_NCL
        AOM_CICP_CP_BT_2020_CL

    ctypedef enum aom_transfer_characteristics:
        AOM_CICP_TC_UNSPECIFIED
        AOM_CICP_TC_BT_709
        AOM_CICP_TC_BT_470M
        AOM_CICP_TC_BT_470BG
        AOM_CICP_TC_SMPTE_170M
        AOM_CICP_TC_SMPTE_240M
        AOM_CICP_TC_LINEAR
        AOM_CICP_TC_LOG_100
        AOM_CICP_TC_LOG_316
        AOM_CICP_TC_BT_2020_10_BIT
        AOM_CICP_TC_BT_2020_12_BIT

    ctypedef enum aom_matrix_coefficients:
        AOM_CICP_MC_UNSPECIFIED
        AOM_CICP_MC_BT_709
        AOM_CICP_MC_UNSPECIFIED_FALLBACK
        AOM_CICP_MC_FCC
        AOM_CICP_MC_BT_470BG
        AOM_CICP_MC_SMPTE_170M
        AOM_CICP_MC_SMPTE_240M
        AOM_CICP_MC_YCGCO
        AOM_CICP_MC_BT_2020_NCL
        AOM_CICP_MC_BT_2020_CL

    ctypedef enum aom_color_range_t:
        AOM_CR_UNSPECIFIED
        AOM_CR_FULL_RANGE
        AOM_CR_LIMITED

    ctypedef enum aom_chroma_sample_position:
        AOM_CSP_UNKNOWN
        AOM_CSP_VERTICAL
        AOM_CSP_COLOCATED
        AOM_CSP_UNSPECIFIED
        AOM_CSP_LEFT
        AOM_CSP_TOPLEFT
        AOM_CSP_TOPRIGHT

    ctypedef enum aom_metadata_insert_flags_t:
        AOM_METADATA_INSERT_FLAG_NONE
        AOM_METADATA_INSERT_FLAG_ITUT_T35
        AOM_METADATA_INSERT_FLAG_DISPLAY_COLOUR_VOLUME
        AOM_METADATA_INSERT_FLAG_MASTERING_DISPLAY
        AOM_METADATA_INSERT_FLAG_CONTENT_LIGHT_LEVEL

    ctypedef struct aom_metadata_t:
        aom_metadata_insert_flags_t flags
        int itut_t35_country_code
        int itut_t35_terminal_provider_code
        int itut_t35_terminal_provider_oriented_code
        int itut_t35_terminal_provider_specific_code
        int display_primaries_x[3]
        int display_primaries_y[3]
        int white_point_x
        int white_point_y
        int max_display_mastering_luminance
        int min_display_mastering_luminance
        int max_content_light_level
        int max_frame_average_light_level

    ctypedef struct aom_image_t:
        aom_img_fmt_t fmt
        aom_color_primaries color_primaries
        aom_transfer_characteristics transfer_characteristics
        aom_matrix_coefficients matrix_coefficients
        int monochrome
        aom_chroma_sample_position chroma_sample_position
        aom_color_range_t range
        int w  # Width of the image in pixels
        int h  # Height of the image in pixels
        int bit_depth
        int d_w  # Display width
        int d_h  # Display height
        int r_w  # Render width
        int r_h  # Render height
        int x_chroma_shift  # Chroma subsampling horizontal shift
        int y_chroma_shift  # Chroma subsampling vertical shift

        uint8_t *planes[3]  # Pointers to the planes of the image
        int stride[3]      # Strides for each plane
        size_t sz  # Size of the image in bytes
        int bps

        int temporal_id  # Temporal ID of the frame
        int spatial_id  # Spatial ID of the frame
        void *user_priv  # User private data pointer

    aom_image_t *aom_img_alloc(aom_image_t *img, aom_img_fmt_t fmt, int w, int h, int align) nogil
    aom_image_t *aom_img_wrap(
        aom_image_t *img, uint8_t *planes[3], int strides[3],
        aom_img_fmt_t fmt, int w, int h, int bit_depth,
        int d_w, int d_h, int r_w, int r_h,
        int x_chroma_shift, int y_chroma_shift) nogil
    aom_image_t *aom_img_alloc_with_border(
        aom_image_t *img, aom_img_fmt_t fmt, int w, int h, int align,
        int border_left, int border_right, int border_top, int border_bottom) nogil
    void aom_img_free(aom_image_t *img) nogil
    int aom_img_plane_width(const aom_image_t *img, int plane) nogil
    int aom_img_plane_height(const aom_image_t *img, int plane) nogil
    int aom_img_add_metadata(aom_image_t *img, aom_metadata_t *metadata, aom_metadata_insert_flags_t flags) nogil


cdef extern from "aom/aom_decoder.h":
    int AOM_DECODER_ABI_VERSION

    ctypedef struct aom_codec_stream_info_t:
        aom_codec_pts_t pts
        aom_codec_frame_flags_t flags
        int width
        int height
        int bit_depth
        int color_space
        int subsampling_x
        int subsampling_y
        int color_range
        int frame_id

    ctypedef struct aom_codec_dec_cfg_t:
        unsigned int threads
        unsigned int w
        unsigned int h
        unsigned int allow_lowbitdepth

    aom_codec_err_t aom_codec_dec_init_ver(
        aom_codec_ctx_t *ctx,
        aom_codec_iface_t *iface,
        const aom_codec_dec_cfg_t *cfg,
        aom_codec_flags_t flags,
        int ver) nogil

    aom_codec_err_t aom_codec_peek_stream_info(
        const uint8_t *data, size_t data_sz,
        aom_codec_stream_info_t *si) nogil

    aom_codec_err_t aom_codec_get_stream_info(aom_codec_ctx_t *ctx, aom_codec_stream_info_t *si) nogil

    aom_codec_err_t aom_codec_decode(
        aom_codec_ctx_t *ctx,
        const uint8_t *data, size_t data_sz,
        void *user_priv) nogil

    ctypedef void *aom_codec_iter_t

    aom_image_t *aom_codec_get_frame(aom_codec_ctx_t *ctx, aom_codec_iter_t *iter) nogil

    # aom_codec_err_t aom_codec_set_frame_buffer_functions(
    #     aom_codec_ctx_t *ctx,
    #     aom_codec_get_frame_buffer_cb_fn_t get_frame_buffer_cb,
    #     aom_codec_release_frame_buffer_cb_fn_t release_frame_buffer_cb,
    #    void *user_priv) nogil


cdef extern from "aom/aom_codec.h":
    ctypedef enum aom_codec_err_t:
        AOM_CODEC_OK = 0
        AOM_CODEC_ERROR = -1
        AOM_CODEC_MEM_ERROR = -2
        AOM_CODEC_ABI_MISMATCH = -3
        AOM_CODEC_INCAPABLE = -4
        AOM_CODEC_UNSUP_BITSTREAM = -5
        AOM_CODEC_UNSUP_FEATURE = -6
        AOM_CODEC_CORRUPT_FRAME = -7
        AOM_CODEC_INVALID_PARAM = -8

    ctypedef enum aom_bit_depth:
        AOM_BITS_8
        AOM_BITS_10
        AOM_BITS_12

    ctypedef enum aom_superblock_size:
        AOM_SUPERBLOCK_SIZE_64X64
        AOM_SUPERBLOCK_SIZE_128X128
        AOM_SUPERBLOCK_SIZE_DYNAMIC

    int aom_codec_version() nogil
    const char *aom_codec_version_extra_str() nogil

    ctypedef struct aom_codec_iface_t:
        pass

    ctypedef struct aom_codec_ctx_t:
        const char *name                # Printable interface name
        aom_codec_iface_t *iface        # Interface pointers
        aom_codec_err_t err             # Last returned error
        const char *err_detail          # Detailed info, if available
        aom_codec_flags_t init_flags    # Flags passed at init time
        const aom_codec_dec_cfg_t *dec    # Decoder Configuration Pointer
        # const aom_codec_enc_cfg_t *enc    # Encoder Configuration Pointer
        const void *raw
        # aom_codec_priv_t *priv          # Algorithm private storage

    const char *aom_codec_iface_name(aom_codec_iface_t *iface)
    const char *aom_codec_err_to_string(aom_codec_err_t err)
    const char *aom_codec_error(const aom_codec_ctx_t *ctx)
    const char *aom_codec_error_detail(const aom_codec_ctx_t *ctx)

    aom_codec_err_t aom_codec_destroy(aom_codec_ctx_t *ctx)
    aom_codec_caps_t aom_codec_get_caps(aom_codec_iface_t *iface);

    # aom_codec_err_t aom_codec_control(aom_codec_ctx_t *ctx, int ctrl_id, ...)
    aom_codec_err_t aom_codec_set_option(aom_codec_ctx_t *ctx, const char *name, const char *value)

    ctypedef enum OBU_TYPE:
        OBU_SEQUENCE_HEADER
        OBU_TEMPORAL_DELIMITER
        OBU_FRAME_HEADER
        OBU_TILE_GROUP
        OBU_METADATA
        OBU_FRAME
        OBU_REDUNDANT_FRAME_HEADER
        OBU_TILE_LIST
        OBU_PADDING

    ctypedef enum OBU_METADATA_TYPE:
        OBU_METADATA_UNSPECIFIED
        OBU_METADATA_ITUT_T35
        OBU_METADATA_DISPLAY_COLOUR_VOLUME
        OBU_METADATA_MASTERING_DISPLAY
        OBU_METADATA_CONTENT_LIGHT_LEVEL

    const char *aom_obu_type_to_string(OBU_TYPE type)


cdef str get_format_str(aom_img_fmt_t fmt)
