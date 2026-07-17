/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: libva encoder - C implementation.
 * ABOUTME: Minimal VA-API H.264/VP8/VP9 encoder using NV12 staging copies and key/P frames. */

#include "va_encode.h"
#include "va_common.h"

#include <va/va.h>
#include <va/va_enc_h264.h>
#include <va/va_enc_vp8.h>
#include <va/va_enc_vp9.h>

#ifdef _WIN32
#include <windows.h>
#include <io.h>     /* close() */
#else
#include <dirent.h>
#include <unistd.h>
#endif

#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define LIBVA_IDR_INTERVAL 60
#define LIBVA_LOG2_MAX_FRAME_NUM_MINUS4 4
#define LIBVA_LOG2_MAX_PIC_ORDER_CNT_LSB_MINUS4 4
#define LIBVA_FRAME_NUM_BITS (LIBVA_LOG2_MAX_FRAME_NUM_MINUS4 + 4)
#define LIBVA_POC_LSB_BITS (LIBVA_LOG2_MAX_PIC_ORDER_CNT_LSB_MINUS4 + 4)
#define LIBVA_H264_POC_TYPE 2

static libva_log_fn g_log_fn = NULL;
static char g_device[256] = "";
static char g_vendor[256] = "";
static char g_error[256] = "";
static int g_h264_supported = 0;
static VAProfile g_h264_profile = VAProfileH264ConstrainedBaseline;
static VAEntrypoint g_h264_entrypoint = VAEntrypointEncSlice;
static int g_vp8_supported = 0;
static VAEntrypoint g_vp8_entrypoint = VAEntrypointEncSlice;
static int g_vp9_supported = 0;
static VAEntrypoint g_vp9_entrypoint = VAEntrypointEncSlice;
static int g_major = 0;
static int g_minor = 0;

void libva_encode_set_log(libva_log_fn fn) {
    g_log_fn = fn;
}

static void libva_log(const char *fmt, ...) {
    if (!g_log_fn)
        return;
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    g_log_fn(buf);
}

static long long usec_now(void) {
#ifdef _WIN32
    LARGE_INTEGER freq, count;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&count);
    return (long long)(count.QuadPart * 1000000LL / freq.QuadPart);
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
#endif
}

struct BitWriter {
    uint8_t data[256];
    int byte_pos;
    int bit_pos;
};

struct LibVAEncoder {
    int             fd;
    VADisplay       display;
    VAConfigID      config;
    VAContextID     context;
    VASurfaceID     src_surface;
    VASurfaceID     recon_surfaces[2];
    uint8_t        *bitstream_data;
    size_t          bitstream_size;
    int             width;
    int             height;
    int             width_mbs;
    int             height_mbs;
    int             surface_width;
    int             surface_height;
    int             frames;
    int             quality;
    int             speed;
    int             qp;
    int             vp_qindex;
    LibVACodec      codec;
    VAProfile       profile;
    VAEntrypoint    entrypoint;
    int             have_reference;
    int             ref_surface_index;
    int             ref_frame_num;
    int             ref_poc_lsb;
    int             full_range;     /* colour range to signal in the headers (video_full_range_flag) */
    int             last_status;
    char            last_error[256];
    char            device[256];
    char            vendor[256];
};

static int quality_to_qp(int quality) {
    int q = 51 - (clamp_int(quality, 0, 100) * 50 + 50) / 100;
    return clamp_int(q, 1, 51);
}

static int quality_to_vp_qindex(int quality) {
    int q = 127 - (clamp_int(quality, 0, 100) * 123 + 50) / 100;
    return clamp_int(q, 4, 127);
}

static int h264_profile_idc(VAProfile profile) {
    switch (profile) {
        case VAProfileH264High:
            return 100;
        case VAProfileH264Main:
            return 77;
        case VAProfileH264ConstrainedBaseline:
        default:
            return 66;
    }
}

static int h264_constraint_flags(VAProfile profile) {
    switch (profile) {
        case VAProfileH264ConstrainedBaseline:
            return 0xc0;
        default:
            return 0;
    }
}

static int h264_level_idc(const LibVAEncoder *enc) {
    int mbs = enc->width_mbs * enc->height_mbs;

    if (mbs <= 3600)
        return 31;
    if (mbs <= 5120)
        return 32;
    if (mbs <= 8192)
        return 41;
    if (mbs <= 8704)
        return 42;
    if (mbs <= 22080)
        return 50;
    return 51;
}

static LibVAEncodeStatus set_error(LibVAEncoder *enc, VAStatus status, const char *context) {
    if (enc) {
        enc->last_status = (int)status;
        snprintf(enc->last_error, sizeof(enc->last_error), "%s failed: %s (%d)",
                 context, vaErrorStr(status), (int)status);
        libva_log("libva encode error: %s", enc->last_error);
    }
    return LIBVA_ENC_ERROR;
}

const char* libva_encode_status_str(LibVAEncodeStatus status) {
    switch (status) {
        case LIBVA_ENC_OK:            return "ok";
        case LIBVA_ENC_ERROR:         return "error";
        case LIBVA_ENC_NOT_AVAILABLE: return "not_available";
        default:                      return "unknown";
    }
}

static void bw_init(struct BitWriter *bw) {
    memset(bw, 0, sizeof(*bw));
}

static void bw_bit(struct BitWriter *bw, int bit) {
    if (bw->byte_pos >= (int)sizeof(bw->data))
        return;
    if (bit)
        bw->data[bw->byte_pos] |= (uint8_t)(1 << (7 - bw->bit_pos));
    bw->bit_pos++;
    if (bw->bit_pos == 8) {
        bw->bit_pos = 0;
        bw->byte_pos++;
    }
}

static void bw_bits(struct BitWriter *bw, unsigned int value, int bits) {
    int i;
    for (i = bits - 1; i >= 0; i--)
        bw_bit(bw, (value >> i) & 1);
}

static void bw_ue(struct BitWriter *bw, unsigned int value) {
    unsigned int code = value + 1;
    int bits = 0;
    unsigned int tmp = code;
    while (tmp) {
        bits++;
        tmp >>= 1;
    }
    for (int i = 0; i < bits - 1; i++)
        bw_bit(bw, 0);
    bw_bits(bw, code, bits);
}

static void bw_se(struct BitWriter *bw, int value) {
    unsigned int code = (value <= 0) ? (unsigned int)(-value * 2) : (unsigned int)(value * 2 - 1);
    bw_ue(bw, code);
}

static int bw_finish(struct BitWriter *bw) {
    bw_bit(bw, 1);
    while (bw->bit_pos)
        bw_bit(bw, 0);
    return bw->byte_pos;
}

static int bw_bit_length(const struct BitWriter *bw) {
    return bw->byte_pos * 8 + bw->bit_pos;
}

static int bw_byte_length(const struct BitWriter *bw) {
    return bw->byte_pos + (bw->bit_pos ? 1 : 0);
}

static int write_start_code(uint8_t *dst, uint8_t nal) {
    dst[0] = 0;
    dst[1] = 0;
    dst[2] = 0;
    dst[3] = 1;
    dst[4] = nal;
    return 5;
}

static int append_ebsp(uint8_t *dst, int dst_size, const uint8_t *src, int src_size) {
    int off = 0;
    int zeros = 0;

    for (int i = 0; i < src_size; i++) {
        uint8_t b = src[i];
        if (zeros >= 2 && b <= 3) {
            if (off >= dst_size)
                return 0;
            dst[off++] = 3;
            zeros = 0;
        }
        if (off >= dst_size)
            return 0;
        dst[off++] = b;
        zeros = (b == 0) ? zeros + 1 : 0;
    }
    return off;
}

static int write_escaped_nal(uint8_t *dst, int dst_size, uint8_t nal,
                             const uint8_t *rbsp, int rbsp_size) {
    int off, bytes;

    if (dst_size < 6)
        return 0;
    off = write_start_code(dst, nal);
    bytes = append_ebsp(dst + off, dst_size - off, rbsp, rbsp_size);
    if (!bytes)
        return 0;
    return off + bytes;
}

static int make_aud(uint8_t *dst, int dst_size, int is_idr) {
    int off;

    if (dst_size < 6)
        return 0;
    off = write_start_code(dst, 0x09);
    dst[off++] = is_idr ? 0x10 : 0x30;
    return off;
}

static int make_sps(LibVAEncoder *enc, uint8_t *dst, int dst_size) {
    struct BitWriter bw;
    int bytes;
    int crop_right = (enc->width_mbs * 16 - enc->width) / 2;
    int crop_bottom = (enc->height_mbs * 16 - enc->height) / 2;

    if (dst_size < 64)
        return 0;
    bw_init(&bw);
    bw_bits(&bw, (unsigned int)h264_profile_idc(enc->profile), 8);
    bw_bits(&bw, (unsigned int)h264_constraint_flags(enc->profile), 8);
    bw_bits(&bw, (unsigned int)h264_level_idc(enc), 8);
    bw_ue(&bw, 0);                    /* seq_parameter_set_id */
    if (enc->profile == VAProfileH264High) {
        bw_ue(&bw, 1);                /* chroma_format_idc: 4:2:0 */
        bw_ue(&bw, 0);                /* bit_depth_luma_minus8 */
        bw_ue(&bw, 0);                /* bit_depth_chroma_minus8 */
        bw_bit(&bw, 0);               /* qpprime_y_zero_transform_bypass_flag */
        bw_bit(&bw, 0);               /* seq_scaling_matrix_present_flag */
    }
    bw_ue(&bw, LIBVA_LOG2_MAX_FRAME_NUM_MINUS4);
    bw_ue(&bw, LIBVA_H264_POC_TYPE);  /* pic_order_cnt_type */
    if (LIBVA_H264_POC_TYPE == 0)
        bw_ue(&bw, LIBVA_LOG2_MAX_PIC_ORDER_CNT_LSB_MINUS4);
    bw_ue(&bw, 1);                    /* max_num_ref_frames */
    bw_bit(&bw, 0);                   /* gaps_in_frame_num_value_allowed_flag */
    bw_ue(&bw, (unsigned int)enc->width_mbs - 1);
    bw_ue(&bw, (unsigned int)enc->height_mbs - 1);
    bw_bit(&bw, 1);                   /* frame_mbs_only_flag */
    bw_bit(&bw, 1);                   /* direct_8x8_inference_flag */
    bw_bit(&bw, crop_right || crop_bottom);
    if (crop_right || crop_bottom) {
        bw_ue(&bw, 0);
        bw_ue(&bw, (unsigned int)crop_right);
        bw_ue(&bw, 0);
        bw_ue(&bw, (unsigned int)crop_bottom);
    }
    bw_bit(&bw, 1);                   /* vui_parameters_present_flag */
    bw_bit(&bw, 0);                   /* aspect_ratio_info_present_flag */
    bw_bit(&bw, 0);                   /* overscan_info_present_flag */
    bw_bit(&bw, 1);                   /* video_signal_type_present_flag */
    bw_bits(&bw, 5, 3);               /* video_format = 5 (unspecified) */
    bw_bit(&bw, enc->full_range ? 1 : 0);  /* video_full_range_flag */
    bw_bit(&bw, 0);                   /* colour_description_present_flag */
    bw_bit(&bw, 0);                   /* chroma_loc_info_present_flag */
    bw_bit(&bw, 1);                   /* timing_info_present_flag */
    bw_bits(&bw, 1, 32);              /* num_units_in_tick */
    bw_bits(&bw, 60, 32);             /* time_scale */
    bw_bit(&bw, 1);                   /* fixed_frame_rate_flag */
    bw_bit(&bw, 0);                   /* nal_hrd_parameters_present_flag */
    bw_bit(&bw, 0);                   /* vcl_hrd_parameters_present_flag */
    bw_bit(&bw, 0);                   /* pic_struct_present_flag */
    bw_bit(&bw, 1);                   /* bitstream_restriction_flag */
    bw_bit(&bw, 1);                   /* motion_vectors_over_pic_boundaries_flag */
    bw_ue(&bw, 0);                    /* max_bytes_per_pic_denom */
    bw_ue(&bw, 0);                    /* max_bits_per_mb_denom */
    bw_ue(&bw, 16);                   /* log2_max_mv_length_horizontal */
    bw_ue(&bw, 16);                   /* log2_max_mv_length_vertical */
    bw_ue(&bw, 0);                    /* max_num_reorder_frames */
    bw_ue(&bw, 1);                    /* max_dec_frame_buffering */
    bytes = bw_finish(&bw);
    return write_escaped_nal(dst, dst_size, 0x67, bw.data, bytes);
}

static int make_pps(LibVAEncoder *enc, uint8_t *dst, int dst_size) {
    struct BitWriter bw;
    int bytes;

    (void)enc;
    if (dst_size < 32)
        return 0;
    bw_init(&bw);
    bw_ue(&bw, 0);                    /* pic_parameter_set_id */
    bw_ue(&bw, 0);                    /* seq_parameter_set_id */
    bw_bit(&bw, 0);                   /* entropy_coding_mode_flag */
    bw_bit(&bw, 0);                   /* pic_order_present_flag */
    bw_ue(&bw, 0);                    /* num_slice_groups_minus1 */
    bw_ue(&bw, 0);                    /* num_ref_idx_l0_active_minus1 */
    bw_ue(&bw, 0);                    /* num_ref_idx_l1_active_minus1 */
    bw_bit(&bw, 0);                   /* weighted_pred_flag */
    bw_bits(&bw, 0, 2);               /* weighted_bipred_idc */
    bw_se(&bw, enc->qp - 26);         /* pic_init_qp_minus26 */
    bw_se(&bw, 0);                    /* pic_init_qs_minus26 */
    bw_se(&bw, 0);                    /* chroma_qp_index_offset */
    bw_bit(&bw, 1);                   /* deblocking_filter_control_present_flag */
    bw_bit(&bw, 0);                   /* constrained_intra_pred_flag */
    bw_bit(&bw, 0);                   /* redundant_pic_cnt_present_flag */
    bytes = bw_finish(&bw);
    return write_escaped_nal(dst, dst_size, 0x68, bw.data, bytes);
}

static int make_h264_sequence_header(LibVAEncoder *enc, uint8_t *dst, int dst_size) {
    int off = 0, bytes;

    bytes = make_sps(enc, dst + off, dst_size - off);
    if (!bytes)
        return 0;
    off += bytes;
    bytes = make_pps(enc, dst + off, dst_size - off);
    if (!bytes)
        return 0;
    return off + bytes;
}

static int make_slice_header(LibVAEncoder *enc, uint8_t *dst, int dst_size,
                             int is_idr, int frame_num, int poc_lsb, int *bit_length) {
    struct BitWriter bw;
    int off = 0, bytes;

    (void)enc;
    if (dst_size < 32)
        return 0;
    off += write_start_code(dst + off, is_idr ? 0x65 : 0x41);
    bw_init(&bw);
    bw_ue(&bw, 0);                    /* first_mb_in_slice */
    bw_ue(&bw, is_idr ? 7 : 5);       /* all slices are I or P */
    bw_ue(&bw, 0);                    /* pic_parameter_set_id */
    bw_bits(&bw, (unsigned int)frame_num, LIBVA_FRAME_NUM_BITS);
    if (is_idr)
        bw_ue(&bw, 0);                /* idr_pic_id */
    if (LIBVA_H264_POC_TYPE == 0)
        bw_bits(&bw, (unsigned int)poc_lsb, LIBVA_POC_LSB_BITS);
    if (!is_idr) {
        bw_bit(&bw, 0);               /* num_ref_idx_active_override_flag */
        bw_bit(&bw, 0);               /* ref_pic_list_modification_flag_l0 */
    }
    if (is_idr) {
        bw_bit(&bw, 0);               /* no_output_of_prior_pics_flag */
        bw_bit(&bw, 0);               /* long_term_reference_flag */
    } else {
        bw_bit(&bw, 0);               /* adaptive_ref_pic_marking_mode_flag */
    }
    bw_se(&bw, 0);                    /* slice_qp_delta */
    bw_ue(&bw, 0);                    /* disable_deblocking_filter_idc */
    bw_se(&bw, 0);                    /* slice_alpha_c0_offset_div2 */
    bw_se(&bw, 0);                    /* slice_beta_offset_div2 */
    bytes = bw_byte_length(&bw);
    bytes = append_ebsp(dst + off, dst_size - off, bw.data, bytes);
    if (!bytes)
        return 0;
    *bit_length = off * 8 + bw_bit_length(&bw) + (bytes - bw_byte_length(&bw)) * 8;
    return off + bytes;
}

static int h264_encode_supported(VADisplay display) {
    static const VAProfile candidate_profiles[] = {
        VAProfileH264ConstrainedBaseline,
        VAProfileH264Main,
        VAProfileH264High,
    };
    static const VAEntrypoint candidate_entrypoints[] = {
        VAEntrypointEncSlice,
        VAEntrypointEncSliceLP,
    };
    VAProfile profiles[64];
    VAEntrypoint entrypoints[32];
    int nprofiles = 0;
    int nentrypoints = 0;
    VAStatus status;
    VAConfigAttrib attrs[3];

    status = vaQueryConfigProfiles(display, profiles, &nprofiles);
    if (status != VA_STATUS_SUCCESS) {
        snprintf(g_error, sizeof(g_error), "vaQueryConfigProfiles failed: %s (%d)",
                 vaErrorStr(status), (int)status);
        return 0;
    }
    for (unsigned int p = 0; p < sizeof(candidate_profiles) / sizeof(candidate_profiles[0]); p++) {
        VAProfile profile = candidate_profiles[p];
        if (!profile_supported(profiles, nprofiles, profile))
            continue;
        status = vaQueryConfigEntrypoints(display, profile, entrypoints, &nentrypoints);
        if (status != VA_STATUS_SUCCESS) {
            snprintf(g_error, sizeof(g_error), "vaQueryConfigEntrypoints(%s) failed: %s (%d)",
                     h264_profile_name(profile), vaErrorStr(status), (int)status);
            continue;
        }
        for (unsigned int e = 0; e < sizeof(candidate_entrypoints) / sizeof(candidate_entrypoints[0]); e++) {
            VAEntrypoint entrypoint = candidate_entrypoints[e];
            int entrypoint_found = 0;
            for (int i = 0; i < nentrypoints; i++) {
                if (entrypoints[i] == entrypoint) {
                    entrypoint_found = 1;
                    break;
                }
            }
            if (!entrypoint_found)
                continue;
            attrs[0].type = VAConfigAttribRTFormat;
            attrs[1].type = VAConfigAttribRateControl;
            attrs[2].type = VAConfigAttribEncPackedHeaders;
            status = vaGetConfigAttributes(display, profile, entrypoint, attrs, 3);
            if (status != VA_STATUS_SUCCESS) {
                snprintf(g_error, sizeof(g_error), "vaGetConfigAttributes(%s, %s) failed: %s (%d)",
                         h264_profile_name(profile), entrypoint_name(entrypoint), vaErrorStr(status), (int)status);
                continue;
            }
            if (!(attrs[0].value & VA_RT_FORMAT_YUV420)) {
                snprintf(g_error, sizeof(g_error), "%s/%s does not support VA_RT_FORMAT_YUV420 encode surfaces",
                         h264_profile_name(profile), entrypoint_name(entrypoint));
                continue;
            }
            if (!(attrs[1].value & VA_RC_CQP)) {
                snprintf(g_error, sizeof(g_error), "%s/%s does not support VA_RC_CQP rate control",
                         h264_profile_name(profile), entrypoint_name(entrypoint));
                continue;
            }
            if ((attrs[2].value & (VA_ENC_PACKED_HEADER_SEQUENCE |
                                   VA_ENC_PACKED_HEADER_SLICE)) !=
                (VA_ENC_PACKED_HEADER_SEQUENCE |
                 VA_ENC_PACKED_HEADER_SLICE)) {
                snprintf(g_error, sizeof(g_error),
                         "%s/%s does not support required packed H.264 headers: %#x",
                         h264_profile_name(profile), entrypoint_name(entrypoint), attrs[2].value);
                continue;
            }
            g_h264_profile = profile;
            g_h264_entrypoint = entrypoint;
            return 1;
        }
    }
    snprintf(g_error, sizeof(g_error),
             "VAEntrypointEncSlice/EncSliceLP is not supported for H.264 constrained-baseline/main/high");
    return 0;
}

static int vpx_encode_supported(VADisplay display, VAProfile profile, const char *name,
                                VAEntrypoint *selected_entrypoint) {
    static const VAEntrypoint candidate_entrypoints[] = {
        VAEntrypointEncSlice,
        VAEntrypointEncSliceLP,
    };
    VAProfile profiles[64];
    VAEntrypoint entrypoints[32];
    int nprofiles = 0;
    int nentrypoints = 0;
    VAStatus status;
    VAConfigAttrib attrs[2];

    status = vaQueryConfigProfiles(display, profiles, &nprofiles);
    if (status != VA_STATUS_SUCCESS) {
        snprintf(g_error, sizeof(g_error), "vaQueryConfigProfiles failed: %s (%d)",
                 vaErrorStr(status), (int)status);
        return 0;
    }
    if (!profile_supported(profiles, nprofiles, profile)) {
        snprintf(g_error, sizeof(g_error), "%s profile is not supported", name);
        return 0;
    }
    status = vaQueryConfigEntrypoints(display, profile, entrypoints, &nentrypoints);
    if (status != VA_STATUS_SUCCESS) {
        snprintf(g_error, sizeof(g_error), "vaQueryConfigEntrypoints(%s) failed: %s (%d)",
                 name, vaErrorStr(status), (int)status);
        return 0;
    }
    for (unsigned int e = 0; e < sizeof(candidate_entrypoints) / sizeof(candidate_entrypoints[0]); e++) {
        VAEntrypoint entrypoint = candidate_entrypoints[e];
        int entrypoint_found = 0;
        for (int i = 0; i < nentrypoints; i++) {
            if (entrypoints[i] == entrypoint) {
                entrypoint_found = 1;
                break;
            }
        }
        if (!entrypoint_found)
            continue;
        attrs[0].type = VAConfigAttribRTFormat;
        attrs[1].type = VAConfigAttribRateControl;
        status = vaGetConfigAttributes(display, profile, entrypoint, attrs, 2);
        if (status != VA_STATUS_SUCCESS) {
            snprintf(g_error, sizeof(g_error), "vaGetConfigAttributes(%s, %s) failed: %s (%d)",
                     name, entrypoint_name(entrypoint), vaErrorStr(status), (int)status);
            continue;
        }
        if (!(attrs[0].value & VA_RT_FORMAT_YUV420)) {
            snprintf(g_error, sizeof(g_error), "%s/%s does not support VA_RT_FORMAT_YUV420 encode surfaces",
                     name, entrypoint_name(entrypoint));
            continue;
        }
        if (!(attrs[1].value & VA_RC_CQP)) {
            snprintf(g_error, sizeof(g_error), "%s/%s does not support VA_RC_CQP rate control",
                     name, entrypoint_name(entrypoint));
            continue;
        }
        *selected_entrypoint = entrypoint;
        return 1;
    }
    snprintf(g_error, sizeof(g_error), "VAEntrypointEncSlice/EncSliceLP is not supported for %s", name);
    return 0;
}

static int vp8_encode_supported(VADisplay display) {
    return vpx_encode_supported(display, VAProfileVP8Version0_3, "VP8", &g_vp8_entrypoint);
}

static int vp9_encode_supported(VADisplay display) {
    return vpx_encode_supported(display, VAProfileVP9Profile0, "VP9 profile 0", &g_vp9_entrypoint);
}

static int try_device(const char *device) {
    int fd = -1, major = 0, minor = 0;
    VADisplay display = NULL;
    char vendor[256] = "";
    int h264_ok, vp8_ok, vp9_ok;

    if (!libva_open_display(device, &fd, &display, &major, &minor, vendor, sizeof(vendor),
                            g_error, sizeof(g_error)))
        return 0;
    h264_ok = h264_encode_supported(display);
    vp8_ok = vp8_encode_supported(display);
    vp9_ok = vp9_encode_supported(display);
    vaTerminate(display);
    libva_x11_close(display);
    if (fd >= 0)
        close(fd);
    if (h264_ok || vp8_ok || vp9_ok) {
        snprintf(g_device, sizeof(g_device), "%s", device);
        snprintf(g_vendor, sizeof(g_vendor), "%s", vendor);
        g_major = major;
        g_minor = minor;
        g_h264_supported = h264_ok;
        g_vp8_supported = vp8_ok;
        g_vp9_supported = vp9_ok;
        if (h264_ok) {
            libva_log("libva encode: selected H.264 %s profile with %s",
                      h264_profile_name(g_h264_profile), entrypoint_name(g_h264_entrypoint));
        }
        if (vp8_ok) {
            libva_log("libva encode: selected VP8 profile with %s",
                      entrypoint_name(g_vp8_entrypoint));
        }
        if (vp9_ok) {
            libva_log("libva encode: selected VP9 profile 0 with %s",
                      entrypoint_name(g_vp9_entrypoint));
        }
    }
    return h264_ok || vp8_ok || vp9_ok;
}

#ifdef _WIN32
LibVAEncodeStatus libva_encode_startup(void) {
    g_error[0] = 0;
    if (try_device("")) {
        libva_log("libva encode startup: using (%s)", g_vendor);
        return LIBVA_ENC_OK;
    }
    if (!g_error[0])
        snprintf(g_error, sizeof(g_error), "no VA-API adapter found");
    libva_log("libva encode startup: no VA-API H.264, VP8 or VP9 CQP encoder found: %s", g_error);
    return LIBVA_ENC_NOT_AVAILABLE;
}
#else
LibVAEncodeStatus libva_encode_startup(void) {
    const char *env_device = getenv("XPRA_LIBVA_DEVICE");
    DIR *dir;
    struct dirent *entry;

    g_error[0] = 0;
    if (env_device && env_device[0]) {
        if (try_device(env_device)) {
            libva_log("libva encode startup: using %s (%s)", g_device, g_vendor);
            return LIBVA_ENC_OK;
        }
        libva_log("libva encode startup: %s does not provide H.264, VP8 or VP9 CQP encode: %s",
                  env_device, g_error);
        return LIBVA_ENC_NOT_AVAILABLE;
    }
    if (try_device("/dev/dri/renderD128")) {
        libva_log("libva encode startup: using %s (%s)", g_device, g_vendor);
        return LIBVA_ENC_OK;
    }
    dir = opendir("/dev/dri");
    if (dir) {
        while ((entry = readdir(dir))) {
            char path[256];
            if (strncmp(entry->d_name, "renderD", 7) != 0)
                continue;
            snprintf(path, sizeof(path), "/dev/dri/%.200s", entry->d_name);
            if (strcmp(path, "/dev/dri/renderD128") == 0)
                continue;
            if (try_device(path)) {
                closedir(dir);
                libva_log("libva encode startup: using %s (%s)", g_device, g_vendor);
                return LIBVA_ENC_OK;
            }
        }
        closedir(dir);
    }
    if (!g_error[0])
        snprintf(g_error, sizeof(g_error), "no VA-API render node found");
    libva_log("libva encode startup: no VA-API H.264, VP8 or VP9 CQP encoder found: %s", g_error);
    return LIBVA_ENC_NOT_AVAILABLE;
}
#endif

void libva_encode_shutdown(void) {
    libva_log("libva encode shutdown");
}

const char *libva_encode_get_device(void) {
    return g_device;
}

const char *libva_encode_get_vendor(void) {
    return g_vendor;
}

const char *libva_encode_get_last_error(void) {
    return g_error;
}

int libva_encode_get_major(void) {
    return g_major;
}

int libva_encode_get_minor(void) {
    return g_minor;
}

static void fill_invalid_picture(VAPictureH264 *pic) {
    memset(pic, 0, sizeof(*pic));
    pic->picture_id = VA_INVALID_SURFACE;
    pic->flags = VA_PICTURE_H264_INVALID;
}

static LibVAEncodeStatus create_packed_header(LibVAEncoder *enc, uint32_t type,
                                              const uint8_t *data, int size, int bit_length,
                                              VABufferID *param_out, VABufferID *data_out) {
    VAEncPackedHeaderParameterBuffer param;
    VAStatus status;

    memset(&param, 0, sizeof(param));
    param.type = type;
    param.bit_length = (uint32_t)bit_length;
    param.has_emulation_bytes = 1;
    status = vaCreateBuffer(enc->display, enc->context,
                            VAEncPackedHeaderParameterBufferType,
                            sizeof(param), 1, &param, param_out);
    if (status != VA_STATUS_SUCCESS)
        return set_error(enc, status, "vaCreateBuffer(packed header param)");
    status = vaCreateBuffer(enc->display, enc->context,
                            VAEncPackedHeaderDataBufferType,
                            (unsigned int)size, 1, (void *)data, data_out);
    if (status != VA_STATUS_SUCCESS)
        return set_error(enc, status, "vaCreateBuffer(packed header data)");
    return LIBVA_ENC_OK;
}

static void destroy_buffers(LibVAEncoder *enc, VABufferID *buffers, int count) {
    for (int i = 0; i < count; i++) {
        if (buffers[i] != VA_INVALID_ID) {
            vaDestroyBuffer(enc->display, buffers[i]);
            buffers[i] = VA_INVALID_ID;
        }
    }
}

LibVAEncodeStatus libva_encoder_create(LibVAEncoder **out, const char *encoding,
                                       int width, int height,
                                       int quality, int speed) {
    LibVAEncoder *enc;
    VAStatus status;
    VAConfigAttrib attrs[3];
    VASurfaceAttrib surface_attrs[2];
    VASurfaceID surfaces[3];
    int major = 0, minor = 0;

    if (!out)
        return LIBVA_ENC_ERROR;
    *out = NULL;
    LibVACodec codec;
    if (!codec_from_name(encoding, &codec))
        return LIBVA_ENC_NOT_AVAILABLE;
    if (width <= 0 || height <= 0 || (width & 1) || (height & 1))
        return LIBVA_ENC_ERROR;
    if (!g_device[0] && libva_encode_startup() != LIBVA_ENC_OK)
        return LIBVA_ENC_NOT_AVAILABLE;
    if ((codec == LIBVA_CODEC_H264 && !g_h264_supported) ||
        (codec == LIBVA_CODEC_VP8 && !g_vp8_supported) ||
        (codec == LIBVA_CODEC_VP9 && !g_vp9_supported))
        return LIBVA_ENC_NOT_AVAILABLE;

    enc = (LibVAEncoder *)calloc(1, sizeof(LibVAEncoder));
    if (!enc)
        return LIBVA_ENC_ERROR;

    enc->fd = -1;
    enc->config = VA_INVALID_ID;
    enc->context = VA_INVALID_ID;
    enc->src_surface = VA_INVALID_SURFACE;
    enc->recon_surfaces[0] = VA_INVALID_SURFACE;
    enc->recon_surfaces[1] = VA_INVALID_SURFACE;
    enc->width = width;
    enc->height = height;
    enc->width_mbs = roundup(width, 16) / 16;
    enc->height_mbs = roundup(height, 16) / 16;
    enc->surface_width = codec == LIBVA_CODEC_VP9 ? roundup(width, 64) : enc->width_mbs * 16;
    enc->surface_height = codec == LIBVA_CODEC_VP9 ? roundup(height, 64) : enc->height_mbs * 16;
    enc->quality = quality;
    enc->speed = speed;
    enc->qp = quality_to_qp(quality);
    enc->vp_qindex = quality_to_vp_qindex(quality);
    enc->codec = codec;
    if (codec == LIBVA_CODEC_H264) {
        enc->profile = g_h264_profile;
        enc->entrypoint = g_h264_entrypoint;
    } else if (codec == LIBVA_CODEC_VP8) {
        enc->profile = VAProfileVP8Version0_3;
        enc->entrypoint = g_vp8_entrypoint;
    } else {
        enc->profile = VAProfileVP9Profile0;
        enc->entrypoint = g_vp9_entrypoint;
    }
    enc->have_reference = 0;
    enc->ref_surface_index = 0;
    enc->ref_frame_num = 0;
    enc->ref_poc_lsb = 0;
    enc->full_range = 0;
    enc->last_status = VA_STATUS_SUCCESS;
    snprintf(enc->device, sizeof(enc->device), "%s", g_device);

    if (!libva_open_display(enc->device, &enc->fd, &enc->display, &major, &minor,
                            enc->vendor, sizeof(enc->vendor),
                            g_error, sizeof(g_error))) {
        snprintf(enc->last_error, sizeof(enc->last_error), "failed to open VA display for %.200s", enc->device);
        libva_encoder_destroy(enc);
        return LIBVA_ENC_NOT_AVAILABLE;
    }

    attrs[0].type = VAConfigAttribRTFormat;
    attrs[0].value = VA_RT_FORMAT_YUV420;
    attrs[1].type = VAConfigAttribRateControl;
    attrs[1].value = VA_RC_CQP;
    if (enc->codec == LIBVA_CODEC_H264) {
        attrs[2].type = VAConfigAttribEncPackedHeaders;
        attrs[2].value = VA_ENC_PACKED_HEADER_SEQUENCE |
                         VA_ENC_PACKED_HEADER_SLICE;
    }
    status = vaCreateConfig(enc->display, enc->profile,
                            enc->entrypoint, attrs, enc->codec == LIBVA_CODEC_H264 ? 3 : 2, &enc->config);
    if (status != VA_STATUS_SUCCESS) {
        set_error(enc, status, "vaCreateConfig");
        libva_encoder_destroy(enc);
        return LIBVA_ENC_ERROR;
    }

    memset(surface_attrs, 0, sizeof(surface_attrs));
    surface_attrs[0].type = VASurfaceAttribPixelFormat;
    surface_attrs[0].flags = VA_SURFACE_ATTRIB_SETTABLE;
    surface_attrs[0].value.type = VAGenericValueTypeInteger;
    surface_attrs[0].value.value.i = VA_FOURCC_NV12;
    surface_attrs[1].type = VASurfaceAttribUsageHint;
    surface_attrs[1].flags = VA_SURFACE_ATTRIB_SETTABLE;
    surface_attrs[1].value.type = VAGenericValueTypeInteger;
    surface_attrs[1].value.value.i = VA_SURFACE_ATTRIB_USAGE_HINT_ENCODER;
    status = vaCreateSurfaces(enc->display, VA_RT_FORMAT_YUV420,
                              (unsigned int)enc->surface_width,
                              (unsigned int)enc->surface_height,
                              surfaces, 3, surface_attrs, 2);
    if (status != VA_STATUS_SUCCESS) {
        set_error(enc, status, "vaCreateSurfaces");
        libva_encoder_destroy(enc);
        return LIBVA_ENC_ERROR;
    }
    enc->src_surface = surfaces[0];
    enc->recon_surfaces[0] = surfaces[1];
    enc->recon_surfaces[1] = surfaces[2];

    status = vaCreateContext(enc->display, enc->config,
                             enc->surface_width, enc->surface_height,
                             VA_PROGRESSIVE, surfaces, 3, &enc->context);
    if (status != VA_STATUS_SUCCESS) {
        set_error(enc, status, "vaCreateContext");
        libva_encoder_destroy(enc);
        return LIBVA_ENC_ERROR;
    }

    enc->bitstream_size = (size_t)enc->surface_width * enc->surface_height * 3 / 2 + 1024 * 1024;
    enc->bitstream_data = (uint8_t *)malloc(enc->bitstream_size);
    if (!enc->bitstream_data) {
        snprintf(enc->last_error, sizeof(enc->last_error), "failed to allocate encoded buffer");
        libva_encoder_destroy(enc);
        return LIBVA_ENC_ERROR;
    }

    libva_log("libva %s encoder create: %dx%d surface=%dx%d level=%d poc=%d aud=%d quality=%d speed=%d qp=%d qindex=%d device=%s vendor=%s",
              codec_name(enc->codec), width, height, enc->surface_width, enc->surface_height,
              enc->codec == LIBVA_CODEC_H264 ? h264_level_idc(enc) : 0,
              enc->codec == LIBVA_CODEC_H264 ? LIBVA_H264_POC_TYPE : 0,
              enc->codec == LIBVA_CODEC_H264,
              quality, speed, enc->qp, enc->vp_qindex, enc->device, enc->vendor);
    *out = enc;
    return LIBVA_ENC_OK;
}

void libva_encoder_destroy(LibVAEncoder *enc) {
    if (!enc)
        return;
    if (enc->display) {
        if (enc->context != VA_INVALID_ID)
            vaDestroyContext(enc->display, enc->context);
        if (enc->src_surface != VA_INVALID_SURFACE)
            vaDestroySurfaces(enc->display, &enc->src_surface, 1);
        if (enc->recon_surfaces[0] != VA_INVALID_SURFACE)
            vaDestroySurfaces(enc->display, &enc->recon_surfaces[0], 1);
        if (enc->recon_surfaces[1] != VA_INVALID_SURFACE)
            vaDestroySurfaces(enc->display, &enc->recon_surfaces[1], 1);
        if (enc->config != VA_INVALID_ID)
            vaDestroyConfig(enc->display, enc->config);
        vaTerminate(enc->display);
        libva_x11_close(enc->display);
    }
    if (enc->fd >= 0)
        close(enc->fd);
    free(enc->bitstream_data);
    free(enc);
}

static LibVAEncodeStatus upload_nv12(LibVAEncoder *enc,
                                     const uint8_t *y, int y_stride,
                                     const uint8_t *uv, int uv_stride,
                                     int *us_copy) {
    VAImage image;
    void *data = NULL;
    VAStatus status;
    long long t0, t1;

    if (y_stride < enc->width || uv_stride < enc->width)
        return set_error(enc, VA_STATUS_ERROR_INVALID_PARAMETER, "invalid NV12 stride");

    t0 = usec_now();
    status = vaDeriveImage(enc->display, enc->src_surface, &image);
    if (status != VA_STATUS_SUCCESS)
        return set_error(enc, status, "vaDeriveImage");
    if (image.format.fourcc != VA_FOURCC_NV12) {
        vaDestroyImage(enc->display, image.image_id);
        snprintf(enc->last_error, sizeof(enc->last_error), "derived surface is not NV12: %#x", image.format.fourcc);
        return LIBVA_ENC_ERROR;
    }
    status = vaMapBuffer(enc->display, image.buf, &data);
    if (status != VA_STATUS_SUCCESS) {
        vaDestroyImage(enc->display, image.image_id);
        return set_error(enc, status, "vaMapBuffer(surface)");
    }
    for (int row = 0; row < enc->height; row++) {
        memcpy((uint8_t *)data + image.offsets[0] + (size_t)row * image.pitches[0],
               y + (size_t)row * y_stride,
               enc->width);
    }
    for (int row = 0; row < enc->height / 2; row++) {
        memcpy((uint8_t *)data + image.offsets[1] + (size_t)row * image.pitches[1],
               uv + (size_t)row * uv_stride,
               enc->width);
    }
    vaUnmapBuffer(enc->display, image.buf);
    vaDestroyImage(enc->display, image.image_id);
    t1 = usec_now();
    *us_copy = (int)(t1 - t0);
    return LIBVA_ENC_OK;
}

static LibVAEncodeStatus append_coded_buffer(LibVAEncoder *enc, VABufferID coded_buf,
                                             LibVAEncodedFrame *frame) {
    VACodedBufferSegment *segment = NULL;
    VAStatus status;
    size_t offset = 0;

    status = vaMapBuffer(enc->display, coded_buf, (void **)&segment);
    if (status != VA_STATUS_SUCCESS)
        return set_error(enc, status, "vaMapBuffer(coded)");
    while (segment) {
        if (segment->status & (VA_CODED_BUF_STATUS_FRAME_SIZE_OVERFLOW |
                               VA_CODED_BUF_STATUS_BAD_BITSTREAM)) {
            vaUnmapBuffer(enc->display, coded_buf);
            snprintf(enc->last_error, sizeof(enc->last_error),
                     "coded buffer status indicates bad output: %#x", segment->status);
            return LIBVA_ENC_ERROR;
        }
        if (offset + segment->size > enc->bitstream_size) {
            vaUnmapBuffer(enc->display, coded_buf);
            snprintf(enc->last_error, sizeof(enc->last_error),
                     "coded buffer too large: %zu > %zu", offset + segment->size, enc->bitstream_size);
            return LIBVA_ENC_ERROR;
        }
        memcpy(enc->bitstream_data + offset, segment->buf, segment->size);
        offset += segment->size;
        segment = (VACodedBufferSegment *)segment->next;
    }
    vaUnmapBuffer(enc->display, coded_buf);
    frame->data = enc->bitstream_data;
    frame->size = (int)offset;
    return LIBVA_ENC_OK;
}

static LibVAEncodeStatus prepend_h264_aud(LibVAEncoder *enc, LibVAEncodedFrame *frame, int is_idr) {
    uint8_t aud[8];
    int aud_size;

    if (!enc || enc->codec != LIBVA_CODEC_H264 || !frame || !frame->data)
        return LIBVA_ENC_OK;
    /* an AUD must be the first NAL unit of the access unit it delimits:
     * a trailing AUD logically belongs to the next access unit and makes
     * low-latency decoders (openh264 DecodeFrameNoDelay) hold the frame back */
    aud_size = make_aud(aud, sizeof(aud), is_idr);
    if (aud_size <= 0)
        return LIBVA_ENC_ERROR;
    if ((size_t)frame->size + (size_t)aud_size > enc->bitstream_size) {
        snprintf(enc->last_error, sizeof(enc->last_error),
                 "not enough room for leading H.264 AUD: %d + %d > %zu",
                 frame->size, aud_size, enc->bitstream_size);
        return LIBVA_ENC_ERROR;
    }
    memmove(enc->bitstream_data + aud_size, enc->bitstream_data, (size_t)frame->size);
    memcpy(enc->bitstream_data, aud, (size_t)aud_size);
    frame->size += aud_size;
    return LIBVA_ENC_OK;
}

static int h264_start_code_size(const uint8_t *data, int size, int pos) {
    if (pos + 3 <= size && data[pos] == 0 && data[pos + 1] == 0 && data[pos + 2] == 1)
        return 3;
    if (pos + 4 <= size && data[pos] == 0 && data[pos + 1] == 0 &&
        data[pos + 2] == 0 && data[pos + 3] == 1)
        return 4;
    return 0;
}

static int h264_find_start_code(const uint8_t *data, int size, int pos, int *start_code_size) {
    for (int i = pos; i + 3 <= size; i++) {
        int sc_size = h264_start_code_size(data, size, i);
        if (sc_size) {
            *start_code_size = sc_size;
            return i;
        }
    }
    *start_code_size = 0;
    return -1;
}

static const char *h264_nal_type_name(int nal_type) {
    switch (nal_type) {
        case 1:  return "slice";
        case 5:  return "IDR";
        case 6:  return "SEI";
        case 7:  return "SPS";
        case 8:  return "PPS";
        case 9:  return "AUD";
        case 10: return "EOSEQ";
        case 11: return "EOSTREAM";
        default: return "NAL";
    }
}

static void log_h264_nals(LibVAEncoder *enc, const LibVAEncodedFrame *frame) {
    char summary[512];
    int pos, sc_size, count = 0;
    size_t off = 0;

    if (!enc || enc->codec != LIBVA_CODEC_H264 || !frame || !frame->data || frame->size <= 0)
        return;
    if (enc->frames >= 5 && getenv("XPRA_LIBVA_H264_NAL_DEBUG") == NULL)
        return;
    summary[0] = 0;
    pos = h264_find_start_code(frame->data, frame->size, 0, &sc_size);
    while (pos >= 0) {
        int nal_start = pos + sc_size;
        int next_sc_size = 0;
        int next = h264_find_start_code(frame->data, frame->size, nal_start, &next_sc_size);
        int nal_end = next >= 0 ? next : frame->size;
        int nal_size = nal_end - nal_start;
        int nal_type = nal_size > 0 ? frame->data[nal_start] & 0x1f : -1;

        if (nal_size > 0) {
            int written = snprintf(summary + off, sizeof(summary) - off, "%s%d:%s/%d",
                                   count ? " " : "", nal_type, h264_nal_type_name(nal_type), nal_size);
            if (written < 0 || (size_t)written >= sizeof(summary) - off)
                break;
            off += (size_t)written;
            count++;
        }
        if (next < 0)
            break;
        pos = next;
        sc_size = next_sc_size;
    }
    libva_log("libva h264 frame %d nals: %s", enc->frames + 1, summary[0] ? summary : "none");
}

static LibVAEncodeStatus h264_encoder_encode(LibVAEncoder *enc,
                                             const uint8_t *y, int y_stride,
                                             const uint8_t *uv, int uv_stride,
                                             LibVAEncodedFrame *frame) {
    VABufferID buffers[9];
    int nbuf = 0;
    VABufferID coded_buf = VA_INVALID_ID;
    VAEncSequenceParameterBufferH264 seq;
    VAEncPictureParameterBufferH264 pic;
    VAEncSliceParameterBufferH264 slice;
    uint8_t seq_header[256], sh[64];
    int seq_header_size, sh_size;
    int sh_bits = 0;
    int gop_frame, is_idr, frame_num, poc_lsb, recon_index;
    VASurfaceID recon_surface;
    VAStatus status;
    LibVAEncodeStatus estatus;
    long long t0, t1, t2;

    if (!enc || !y || !uv || !frame)
        return LIBVA_ENC_ERROR;
    memset(frame, 0, sizeof(*frame));
    for (int i = 0; i < (int)(sizeof(buffers) / sizeof(buffers[0])); i++)
        buffers[i] = VA_INVALID_ID;

    estatus = upload_nv12(enc, y, y_stride, uv, uv_stride, &frame->us_copy);
    if (estatus != LIBVA_ENC_OK)
        return estatus;
    gop_frame = enc->frames % LIBVA_IDR_INTERVAL;
    is_idr = !enc->have_reference || gop_frame == 0;
    frame_num = is_idr ? 0 : gop_frame;
    poc_lsb = (frame_num * 2) & ((1 << LIBVA_POC_LSB_BITS) - 1);
    recon_index = enc->frames & 1;
    recon_surface = enc->recon_surfaces[recon_index];

    status = vaCreateBuffer(enc->display, enc->context, VAEncCodedBufferType,
                            (unsigned int)enc->bitstream_size, 1, NULL, &coded_buf);
    if (status != VA_STATUS_SUCCESS)
        return set_error(enc, status, "vaCreateBuffer(coded)");
    buffers[nbuf++] = coded_buf;

    memset(&seq, 0, sizeof(seq));
    seq.seq_parameter_set_id = 0;
    seq.level_idc = (uint8_t)h264_level_idc(enc);
    seq.intra_period = LIBVA_IDR_INTERVAL;
    seq.intra_idr_period = LIBVA_IDR_INTERVAL;
    seq.ip_period = 1;
    seq.bits_per_second = 0;
    seq.max_num_ref_frames = 1;
    seq.picture_width_in_mbs = (uint16_t)enc->width_mbs;
    seq.picture_height_in_mbs = (uint16_t)enc->height_mbs;
    seq.seq_fields.bits.chroma_format_idc = 1;
    seq.seq_fields.bits.frame_mbs_only_flag = 1;
    seq.seq_fields.bits.direct_8x8_inference_flag = 1;
    seq.seq_fields.bits.log2_max_frame_num_minus4 = LIBVA_LOG2_MAX_FRAME_NUM_MINUS4;
    seq.seq_fields.bits.pic_order_cnt_type = LIBVA_H264_POC_TYPE;
    if (LIBVA_H264_POC_TYPE == 0)
        seq.seq_fields.bits.log2_max_pic_order_cnt_lsb_minus4 = LIBVA_LOG2_MAX_PIC_ORDER_CNT_LSB_MINUS4;
    seq.bit_depth_luma_minus8 = 0;
    seq.bit_depth_chroma_minus8 = 0;
    seq.vui_parameters_present_flag = 1;
    seq.vui_fields.bits.timing_info_present_flag = 1;
    seq.vui_fields.bits.fixed_frame_rate_flag = 1;
    seq.vui_fields.bits.bitstream_restriction_flag = 1;
    seq.vui_fields.bits.motion_vectors_over_pic_boundaries_flag = 1;
    seq.vui_fields.bits.log2_max_mv_length_horizontal = 16;
    seq.vui_fields.bits.log2_max_mv_length_vertical = 16;
    seq.num_units_in_tick = 1;
    seq.time_scale = 60;
    if (enc->width_mbs * 16 != enc->width || enc->height_mbs * 16 != enc->height) {
        seq.frame_cropping_flag = 1;
        seq.frame_crop_right_offset = (uint32_t)(enc->width_mbs * 16 - enc->width) / 2;
        seq.frame_crop_bottom_offset = (uint32_t)(enc->height_mbs * 16 - enc->height) / 2;
    }
    status = vaCreateBuffer(enc->display, enc->context, VAEncSequenceParameterBufferType,
                            sizeof(seq), 1, &seq, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(sequence)");
    }
    if (is_idr) {
        seq_header_size = make_h264_sequence_header(enc, seq_header, sizeof(seq_header));
        if (seq_header_size <= 0) {
            destroy_buffers(enc, buffers, nbuf);
            snprintf(enc->last_error, sizeof(enc->last_error), "failed to create H.264 sequence header");
            return LIBVA_ENC_ERROR;
        }
        if (create_packed_header(enc, VAEncPackedHeaderSequence,
                                 seq_header, seq_header_size, seq_header_size * 8,
                                 &buffers[nbuf], &buffers[nbuf + 1]) != LIBVA_ENC_OK) {
            destroy_buffers(enc, buffers, nbuf + 2);
            return LIBVA_ENC_ERROR;
        }
        nbuf += 2;
    }

    memset(&pic, 0, sizeof(pic));
    pic.CurrPic.picture_id = recon_surface;
    pic.CurrPic.frame_idx = (uint32_t)frame_num;
    pic.CurrPic.flags = VA_PICTURE_H264_SHORT_TERM_REFERENCE;
    pic.CurrPic.TopFieldOrderCnt = poc_lsb;
    pic.CurrPic.BottomFieldOrderCnt = poc_lsb;
    for (int i = 0; i < 16; i++)
        fill_invalid_picture(&pic.ReferenceFrames[i]);
    if (!is_idr) {
        pic.ReferenceFrames[0].picture_id = enc->recon_surfaces[enc->ref_surface_index];
        pic.ReferenceFrames[0].frame_idx = (uint32_t)enc->ref_frame_num;
        pic.ReferenceFrames[0].flags = VA_PICTURE_H264_SHORT_TERM_REFERENCE;
        pic.ReferenceFrames[0].TopFieldOrderCnt = enc->ref_poc_lsb;
        pic.ReferenceFrames[0].BottomFieldOrderCnt = enc->ref_poc_lsb;
    }
    pic.coded_buf = coded_buf;
    pic.pic_parameter_set_id = 0;
    pic.seq_parameter_set_id = 0;
    pic.last_picture = 0;
    pic.frame_num = (uint16_t)frame_num;
    pic.pic_init_qp = (uint8_t)enc->qp;
    pic.num_ref_idx_l0_active_minus1 = 0;
    pic.num_ref_idx_l1_active_minus1 = 0;
    pic.chroma_qp_index_offset = 0;
    pic.second_chroma_qp_index_offset = 0;
    pic.pic_fields.bits.idr_pic_flag = is_idr;
    pic.pic_fields.bits.reference_pic_flag = 1;
    pic.pic_fields.bits.entropy_coding_mode_flag = 0;
    pic.pic_fields.bits.deblocking_filter_control_present_flag = 1;
    status = vaCreateBuffer(enc->display, enc->context, VAEncPictureParameterBufferType,
                            sizeof(pic), 1, &pic, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(picture)");
    }
    memset(&slice, 0, sizeof(slice));
    slice.macroblock_address = 0;
    slice.num_macroblocks = (uint32_t)(enc->width_mbs * enc->height_mbs);
    slice.macroblock_info = VA_INVALID_ID;
    slice.slice_type = is_idr ? 7 : 5;
    slice.pic_parameter_set_id = 0;
    slice.idr_pic_id = 0;
    slice.pic_order_cnt_lsb = LIBVA_H264_POC_TYPE == 0 ? (uint16_t)poc_lsb : 0;
    slice.num_ref_idx_l0_active_minus1 = 0;
    slice.num_ref_idx_l1_active_minus1 = 0;
    for (int i = 0; i < 32; i++) {
        fill_invalid_picture(&slice.RefPicList0[i]);
        fill_invalid_picture(&slice.RefPicList1[i]);
    }
    if (!is_idr) {
        slice.RefPicList0[0].picture_id = enc->recon_surfaces[enc->ref_surface_index];
        slice.RefPicList0[0].frame_idx = (uint32_t)enc->ref_frame_num;
        slice.RefPicList0[0].flags = VA_PICTURE_H264_SHORT_TERM_REFERENCE;
        slice.RefPicList0[0].TopFieldOrderCnt = enc->ref_poc_lsb;
        slice.RefPicList0[0].BottomFieldOrderCnt = enc->ref_poc_lsb;
    }
    slice.slice_qp_delta = 0;
    slice.disable_deblocking_filter_idc = 0;
    slice.slice_alpha_c0_offset_div2 = 0;
    slice.slice_beta_offset_div2 = 0;
    sh_size = make_slice_header(enc, sh, sizeof(sh), is_idr, frame_num, poc_lsb, &sh_bits);
    if (sh_size <= 0 || sh_bits <= 0) {
        destroy_buffers(enc, buffers, nbuf);
        snprintf(enc->last_error, sizeof(enc->last_error), "failed to create H.264 slice header");
        return LIBVA_ENC_ERROR;
    }
    if (create_packed_header(enc, VAEncPackedHeaderSlice, sh, sh_size, sh_bits,
                             &buffers[nbuf], &buffers[nbuf + 1]) != LIBVA_ENC_OK) {
        destroy_buffers(enc, buffers, nbuf + 2);
        return LIBVA_ENC_ERROR;
    }
    nbuf += 2;
    status = vaCreateBuffer(enc->display, enc->context, VAEncSliceParameterBufferType,
                            sizeof(slice), 1, &slice, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(slice)");
    }

    t0 = usec_now();
    status = vaBeginPicture(enc->display, enc->context, enc->src_surface);
    if (status == VA_STATUS_SUCCESS)
        status = vaRenderPicture(enc->display, enc->context, buffers + 1, nbuf - 1);
    if (status == VA_STATUS_SUCCESS)
        status = vaEndPicture(enc->display, enc->context);
    t1 = usec_now();
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "VA encode submit");
    }

    status = vaSyncSurface(enc->display, enc->src_surface);
    t2 = usec_now();
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaSyncSurface");
    }
    estatus = append_coded_buffer(enc, coded_buf, frame);
    destroy_buffers(enc, buffers, nbuf);
    if (estatus != LIBVA_ENC_OK)
        return estatus;
    estatus = prepend_h264_aud(enc, frame, is_idr);
    if (estatus != LIBVA_ENC_OK)
        return estatus;
    log_h264_nals(enc, frame);
    frame->us_submit = (int)(t1 - t0);
    frame->us_sync = (int)(t2 - t1);
    frame->frame_type = is_idr ? LIBVA_ENC_FRAME_IDR : LIBVA_ENC_FRAME_P;
    enc->have_reference = 1;
    enc->ref_surface_index = recon_index;
    enc->ref_frame_num = frame_num;
    enc->ref_poc_lsb = poc_lsb;
    enc->frames++;
    return LIBVA_ENC_OK;
}

static LibVAEncodeStatus vp8_encoder_encode(LibVAEncoder *enc,
                                            const uint8_t *y, int y_stride,
                                            const uint8_t *uv, int uv_stride,
                                            LibVAEncodedFrame *frame) {
    VABufferID buffers[4];
    int nbuf = 0;
    VABufferID coded_buf = VA_INVALID_ID;
    VAEncSequenceParameterBufferVP8 seq;
    VAEncPictureParameterBufferVP8 pic;
    VAQMatrixBufferVP8 qmatrix;
    int gop_frame, is_key, recon_index;
    VASurfaceID recon_surface;
    VAStatus status;
    LibVAEncodeStatus estatus;
    long long t0, t1, t2;

    if (!enc || !y || !uv || !frame)
        return LIBVA_ENC_ERROR;
    memset(frame, 0, sizeof(*frame));
    for (int i = 0; i < (int)(sizeof(buffers) / sizeof(buffers[0])); i++)
        buffers[i] = VA_INVALID_ID;

    estatus = upload_nv12(enc, y, y_stride, uv, uv_stride, &frame->us_copy);
    if (estatus != LIBVA_ENC_OK)
        return estatus;
    gop_frame = enc->frames % LIBVA_IDR_INTERVAL;
    is_key = !enc->have_reference || gop_frame == 0;
    recon_index = enc->frames & 1;
    recon_surface = enc->recon_surfaces[recon_index];

    status = vaCreateBuffer(enc->display, enc->context, VAEncCodedBufferType,
                            (unsigned int)enc->bitstream_size, 1, NULL, &coded_buf);
    if (status != VA_STATUS_SUCCESS)
        return set_error(enc, status, "vaCreateBuffer(coded)");
    buffers[nbuf++] = coded_buf;

    memset(&seq, 0, sizeof(seq));
    seq.frame_width = (uint32_t)enc->width;
    seq.frame_height = (uint32_t)enc->height;
    seq.frame_width_scale = 0;
    seq.frame_height_scale = 0;
    seq.error_resilient = 0;
    seq.kf_auto = 0;
    seq.kf_min_dist = LIBVA_IDR_INTERVAL;
    seq.kf_max_dist = LIBVA_IDR_INTERVAL;
    seq.bits_per_second = 0;
    seq.intra_period = LIBVA_IDR_INTERVAL;
    for (int i = 0; i < 4; i++)
        seq.reference_frames[i] = VA_INVALID_SURFACE;
    status = vaCreateBuffer(enc->display, enc->context, VAEncSequenceParameterBufferType,
                            sizeof(seq), 1, &seq, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(VP8 sequence)");
    }

    memset(&pic, 0, sizeof(pic));
    pic.reconstructed_frame = recon_surface;
    pic.ref_last_frame = is_key ? VA_INVALID_SURFACE : enc->recon_surfaces[enc->ref_surface_index];
    pic.ref_gf_frame = VA_INVALID_SURFACE;
    pic.ref_arf_frame = VA_INVALID_SURFACE;
    pic.coded_buf = coded_buf;
    pic.ref_flags.bits.force_kf = is_key;
    pic.ref_flags.bits.no_ref_last = is_key;
    pic.ref_flags.bits.no_ref_gf = 1;
    pic.ref_flags.bits.no_ref_arf = 1;
    pic.ref_flags.bits.first_ref = is_key ? 0 : 1;
    pic.pic_flags.bits.frame_type = is_key ? 0 : 1;
    pic.pic_flags.bits.version = 0;
    pic.pic_flags.bits.show_frame = 1;
    pic.pic_flags.bits.color_space = 0;
    pic.pic_flags.bits.recon_filter_type = 0;
    pic.pic_flags.bits.loop_filter_type = 1;
    pic.pic_flags.bits.auto_partitions = 0;
    pic.pic_flags.bits.num_token_partitions = 0;
    pic.pic_flags.bits.clamping_type = 1;
    pic.pic_flags.bits.refresh_entropy_probs = 1;
    pic.pic_flags.bits.refresh_last = 1;
    pic.pic_flags.bits.mb_no_coeff_skip = 1;
    pic.pic_flags.bits.forced_lf_adjustment = is_key;
    pic.loop_filter_level[0] = 16;
    pic.loop_filter_level[1] = 16;
    pic.loop_filter_level[2] = 16;
    pic.loop_filter_level[3] = 16;
    pic.sharpness_level = 0;
    pic.clamp_qindex_high = (uint8_t)enc->vp_qindex;
    pic.clamp_qindex_low = (uint8_t)enc->vp_qindex;
    status = vaCreateBuffer(enc->display, enc->context, VAEncPictureParameterBufferType,
                            sizeof(pic), 1, &pic, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(VP8 picture)");
    }

    memset(&qmatrix, 0, sizeof(qmatrix));
    for (int i = 0; i < 4; i++)
        qmatrix.quantization_index[i] = (uint16_t)enc->vp_qindex;
    status = vaCreateBuffer(enc->display, enc->context, VAQMatrixBufferType,
                            sizeof(qmatrix), 1, &qmatrix, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(VP8 qmatrix)");
    }

    t0 = usec_now();
    status = vaBeginPicture(enc->display, enc->context, enc->src_surface);
    if (status == VA_STATUS_SUCCESS)
        status = vaRenderPicture(enc->display, enc->context, buffers + 1, nbuf - 1);
    if (status == VA_STATUS_SUCCESS)
        status = vaEndPicture(enc->display, enc->context);
    t1 = usec_now();
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "VA VP8 encode submit");
    }

    status = vaSyncSurface(enc->display, enc->src_surface);
    t2 = usec_now();
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaSyncSurface");
    }
    estatus = append_coded_buffer(enc, coded_buf, frame);
    destroy_buffers(enc, buffers, nbuf);
    if (estatus != LIBVA_ENC_OK)
        return estatus;
    frame->us_submit = (int)(t1 - t0);
    frame->us_sync = (int)(t2 - t1);
    frame->frame_type = is_key ? LIBVA_ENC_FRAME_I : LIBVA_ENC_FRAME_P;
    enc->have_reference = 1;
    enc->ref_surface_index = recon_index;
    enc->frames++;
    return LIBVA_ENC_OK;
}

static LibVAEncodeStatus vp9_encoder_encode(LibVAEncoder *enc,
                                            const uint8_t *y, int y_stride,
                                            const uint8_t *uv, int uv_stride,
                                            LibVAEncodedFrame *frame) {
    VABufferID buffers[4];
    int nbuf = 0;
    VABufferID coded_buf = VA_INVALID_ID;
    VAEncSequenceParameterBufferVP9 seq;
    VAEncPictureParameterBufferVP9 pic;
    VAEncMiscParameterTypeVP9PerSegmantParam seg;
    int gop_frame, is_key, recon_index;
    VASurfaceID recon_surface;
    VAStatus status;
    LibVAEncodeStatus estatus;
    long long t0, t1, t2;

    if (!enc || !y || !uv || !frame)
        return LIBVA_ENC_ERROR;
    memset(frame, 0, sizeof(*frame));
    for (int i = 0; i < (int)(sizeof(buffers) / sizeof(buffers[0])); i++)
        buffers[i] = VA_INVALID_ID;

    estatus = upload_nv12(enc, y, y_stride, uv, uv_stride, &frame->us_copy);
    if (estatus != LIBVA_ENC_OK)
        return estatus;
    gop_frame = enc->frames % LIBVA_IDR_INTERVAL;
    is_key = !enc->have_reference || gop_frame == 0;
    recon_index = enc->frames & 1;
    recon_surface = enc->recon_surfaces[recon_index];

    status = vaCreateBuffer(enc->display, enc->context, VAEncCodedBufferType,
                            (unsigned int)enc->bitstream_size, 1, NULL, &coded_buf);
    if (status != VA_STATUS_SUCCESS)
        return set_error(enc, status, "vaCreateBuffer(coded)");
    buffers[nbuf++] = coded_buf;

    memset(&seq, 0, sizeof(seq));
    seq.max_frame_width = (uint32_t)enc->surface_width;
    seq.max_frame_height = (uint32_t)enc->surface_height;
    seq.kf_auto = 0;
    seq.kf_min_dist = LIBVA_IDR_INTERVAL;
    seq.kf_max_dist = LIBVA_IDR_INTERVAL;
    seq.bits_per_second = 0;
    seq.intra_period = LIBVA_IDR_INTERVAL;
    status = vaCreateBuffer(enc->display, enc->context, VAEncSequenceParameterBufferType,
                            sizeof(seq), 1, &seq, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(VP9 sequence)");
    }

    memset(&pic, 0, sizeof(pic));
    pic.frame_width_src = (uint32_t)enc->width;
    pic.frame_height_src = (uint32_t)enc->height;
    pic.frame_width_dst = (uint32_t)enc->width;
    pic.frame_height_dst = (uint32_t)enc->height;
    pic.reconstructed_frame = recon_surface;
    for (int i = 0; i < 8; i++)
        pic.reference_frames[i] = VA_INVALID_SURFACE;
    if (!is_key)
        pic.reference_frames[0] = enc->recon_surfaces[enc->ref_surface_index];
    pic.coded_buf = coded_buf;
    pic.ref_flags.bits.force_kf = is_key;
    pic.ref_flags.bits.ref_frame_ctrl_l0 = is_key ? 0 : 1;
    pic.ref_flags.bits.ref_frame_ctrl_l1 = 0;
    pic.ref_flags.bits.ref_last_idx = 0;
    pic.ref_flags.bits.ref_gf_idx = 0;
    pic.ref_flags.bits.ref_arf_idx = 0;
    pic.pic_flags.bits.frame_type = is_key ? 0 : 1;
    pic.pic_flags.bits.show_frame = 1;
    pic.pic_flags.bits.error_resilient_mode = 0;
    pic.pic_flags.bits.intra_only = 0;
    pic.pic_flags.bits.allow_high_precision_mv = !is_key;
    pic.pic_flags.bits.mcomp_filter_type = 0;
    pic.pic_flags.bits.frame_parallel_decoding_mode = 1;
    pic.pic_flags.bits.reset_frame_context = is_key ? 3 : 0;
    pic.pic_flags.bits.refresh_frame_context = 1;
    pic.pic_flags.bits.frame_context_idx = 0;
    pic.pic_flags.bits.segmentation_enabled = 0;
    pic.pic_flags.bits.lossless_mode = 0;
    pic.pic_flags.bits.comp_prediction_mode = 0;
    pic.pic_flags.bits.auto_segmentation = 0;
    pic.pic_flags.bits.super_frame_flag = 0;
    pic.refresh_frame_flags = is_key ? 0xff : 0x01;
    pic.luma_ac_qindex = (uint8_t)enc->vp_qindex;
    pic.luma_dc_qindex_delta = 0;
    pic.chroma_ac_qindex_delta = 0;
    pic.chroma_dc_qindex_delta = 0;
    pic.filter_level = 16;
    pic.sharpness_level = 0;
    pic.log2_tile_rows = 0;
    pic.log2_tile_columns = 0;
    pic.skip_frame_flag = 0;
    status = vaCreateBuffer(enc->display, enc->context, VAEncPictureParameterBufferType,
                            sizeof(pic), 1, &pic, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(VP9 picture)");
    }

    memset(&seg, 0, sizeof(seg));
    status = vaCreateBuffer(enc->display, enc->context, VAQMatrixBufferType,
                            sizeof(seg), 1, &seg, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(VP9 segment)");
    }

    t0 = usec_now();
    status = vaBeginPicture(enc->display, enc->context, enc->src_surface);
    if (status == VA_STATUS_SUCCESS)
        status = vaRenderPicture(enc->display, enc->context, buffers + 1, nbuf - 1);
    if (status == VA_STATUS_SUCCESS)
        status = vaEndPicture(enc->display, enc->context);
    t1 = usec_now();
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "VA VP9 encode submit");
    }

    status = vaSyncSurface(enc->display, enc->src_surface);
    t2 = usec_now();
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaSyncSurface");
    }
    estatus = append_coded_buffer(enc, coded_buf, frame);
    destroy_buffers(enc, buffers, nbuf);
    if (estatus != LIBVA_ENC_OK)
        return estatus;
    frame->us_submit = (int)(t1 - t0);
    frame->us_sync = (int)(t2 - t1);
    frame->frame_type = is_key ? LIBVA_ENC_FRAME_I : LIBVA_ENC_FRAME_P;
    enc->have_reference = 1;
    enc->ref_surface_index = recon_index;
    enc->frames++;
    return LIBVA_ENC_OK;
}

LibVAEncodeStatus libva_encoder_encode(LibVAEncoder *enc,
                                       const uint8_t *y, int y_stride,
                                       const uint8_t *uv, int uv_stride,
                                       int full_range,
                                       LibVAEncodedFrame *frame) {
    if (!enc)
        return LIBVA_ENC_ERROR;
    if (full_range != enc->full_range) {
        /* the colour range is written into the headers (h264 SPS VUI) only on keyframes,
           so restart the GOP to emit a fresh IDR/keyframe that carries the new range: */
        enc->full_range = full_range;
        enc->frames = 0;
        enc->have_reference = 0;
    }
    switch (enc->codec) {
        case LIBVA_CODEC_H264:
            return h264_encoder_encode(enc, y, y_stride, uv, uv_stride, frame);
        case LIBVA_CODEC_VP8:
            return vp8_encoder_encode(enc, y, y_stride, uv, uv_stride, frame);
        case LIBVA_CODEC_VP9:
            return vp9_encoder_encode(enc, y, y_stride, uv, uv_stride, frame);
        default:
            return LIBVA_ENC_ERROR;
    }
}

int libva_encoder_get_width(LibVAEncoder *enc) {
    return enc ? enc->width : 0;
}

int libva_encoder_get_height(LibVAEncoder *enc) {
    return enc ? enc->height : 0;
}

int libva_encoder_get_last_status(LibVAEncoder *enc) {
    return enc ? enc->last_status : 0;
}

const char* libva_encoder_get_last_error(LibVAEncoder *enc) {
    return enc ? enc->last_error : "no encoder";
}
