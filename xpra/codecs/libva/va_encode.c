/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: libva H.264 encoder - C implementation.
 * ABOUTME: Minimal VA-API AVC encoder using NV12 staging copies and IDR frames. */

#include "va_encode.h"

#include <va/va.h>
#include <va/va_drm.h>
#include <va/va_enc_h264.h>

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define LIBVA_H264_LEVEL_IDC 51

#ifndef VA_CHECK_VERSION
#define VA_CHECK_VERSION(major, minor, micro) \
    ((VA_MAJOR_VERSION > (major)) || \
     (VA_MAJOR_VERSION == (major) && VA_MINOR_VERSION > (minor)) || \
     (VA_MAJOR_VERSION == (major) && VA_MINOR_VERSION == (minor) && VA_MICRO_VERSION >= (micro)))
#endif

static libva_log_fn g_log_fn = NULL;
static char g_device[256] = "";
static char g_vendor[256] = "";
static char g_error[256] = "";
static VAProfile g_profile = VAProfileH264ConstrainedBaseline;
static VAEntrypoint g_entrypoint = VAEntrypointEncSlice;
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
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
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
    VASurfaceID     recon_surface;
    uint8_t        *bitstream_data;
    size_t          bitstream_size;
    int             width;
    int             height;
    int             width_mbs;
    int             height_mbs;
    int             frames;
    int             quality;
    int             speed;
    int             qp;
    VAProfile       profile;
    VAEntrypoint    entrypoint;
    int             last_status;
    char            last_error[256];
    char            device[256];
    char            vendor[256];
};

static int roundup(int n, int m) {
    return (n + m - 1) & ~(m - 1);
}

static int clamp_int(int value, int low, int high) {
    if (value < low)
        return low;
    if (value > high)
        return high;
    return value;
}

static int quality_to_qp(int quality) {
    int q = 51 - (clamp_int(quality, 0, 100) * 50 + 50) / 100;
    return clamp_int(q, 1, 51);
}

static const char *h264_profile_name(VAProfile profile) {
    switch (profile) {
        case VAProfileH264ConstrainedBaseline:
            return "constrained-baseline";
        case VAProfileH264Main:
            return "main";
        case VAProfileH264High:
            return "high";
        default:
            return "unknown";
    }
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

static const char *entrypoint_name(VAEntrypoint entrypoint) {
    switch (entrypoint) {
        case VAEntrypointEncSlice:
            return "EncSlice";
        case VAEntrypointEncSliceLP:
            return "EncSliceLP";
        default:
            return "unknown";
    }
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

static int write_start_code(uint8_t *dst, uint8_t nal) {
    dst[0] = 0;
    dst[1] = 0;
    dst[2] = 0;
    dst[3] = 1;
    dst[4] = nal;
    return 5;
}

static int make_sps(LibVAEncoder *enc, uint8_t *dst, int dst_size) {
    struct BitWriter bw;
    int off, bytes;
    int crop_right = (enc->width_mbs * 16 - enc->width) / 2;
    int crop_bottom = (enc->height_mbs * 16 - enc->height) / 2;

    if (dst_size < 64)
        return 0;
    off = write_start_code(dst, 0x67);
    bw_init(&bw);
    bw_bits(&bw, (unsigned int)h264_profile_idc(enc->profile), 8);
    bw_bits(&bw, (unsigned int)h264_constraint_flags(enc->profile), 8);
    bw_bits(&bw, LIBVA_H264_LEVEL_IDC, 8);
    bw_ue(&bw, 0);                    /* seq_parameter_set_id */
    if (enc->profile == VAProfileH264High) {
        bw_ue(&bw, 1);                /* chroma_format_idc: 4:2:0 */
        bw_ue(&bw, 0);                /* bit_depth_luma_minus8 */
        bw_ue(&bw, 0);                /* bit_depth_chroma_minus8 */
        bw_bit(&bw, 0);               /* qpprime_y_zero_transform_bypass_flag */
        bw_bit(&bw, 0);               /* seq_scaling_matrix_present_flag */
    }
    bw_ue(&bw, 0);                    /* log2_max_frame_num_minus4 */
    bw_ue(&bw, 0);                    /* pic_order_cnt_type */
    bw_ue(&bw, 0);                    /* log2_max_pic_order_cnt_lsb_minus4 */
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
    bw_bit(&bw, 0);                   /* vui_parameters_present_flag */
    bytes = bw_finish(&bw);
    memcpy(dst + off, bw.data, bytes);
    return off + bytes;
}

static int make_pps(LibVAEncoder *enc, uint8_t *dst, int dst_size) {
    struct BitWriter bw;
    int off, bytes;

    (void)enc;
    if (dst_size < 32)
        return 0;
    off = write_start_code(dst, 0x68);
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
    memcpy(dst + off, bw.data, bytes);
    return off + bytes;
}

static int make_slice_header(LibVAEncoder *enc, uint8_t *dst, int dst_size) {
    struct BitWriter bw;
    int off, bytes;

    (void)enc;
    if (dst_size < 32)
        return 0;
    off = write_start_code(dst, 0x65); /* IDR, nal_ref_idc=3 */
    bw_init(&bw);
    bw_ue(&bw, 0);                    /* first_mb_in_slice */
    bw_ue(&bw, 2);                    /* slice_type: I */
    bw_ue(&bw, 0);                    /* pic_parameter_set_id */
    bw_bits(&bw, 0, 4);               /* frame_num */
    bw_ue(&bw, 0);                    /* idr_pic_id */
    bw_bits(&bw, 0, 4);               /* pic_order_cnt_lsb */
    bw_se(&bw, 0);                    /* slice_qp_delta */
    bw_ue(&bw, 0);                    /* disable_deblocking_filter_idc */
    bw_se(&bw, 0);                    /* slice_alpha_c0_offset_div2 */
    bw_se(&bw, 0);                    /* slice_beta_offset_div2 */
    bytes = bw_finish(&bw);
    memcpy(dst + off, bw.data, bytes);
    return off + bytes;
}

static int open_display(const char *device, int *fd_out, VADisplay *display_out,
                        int *major_out, int *minor_out, char *vendor, size_t vendor_size) {
    int fd = open(device, O_RDWR | O_CLOEXEC);
    VADisplay display;
    VAStatus status;
    const char *vstr;

    *fd_out = -1;
    *display_out = NULL;
    if (fd < 0)
        return 0;
    display = vaGetDisplayDRM(fd);
    if (!display) {
        snprintf(g_error, sizeof(g_error), "vaGetDisplayDRM failed for %.200s", device);
        close(fd);
        return 0;
    }
    status = vaInitialize(display, major_out, minor_out);
    if (status != VA_STATUS_SUCCESS) {
        snprintf(g_error, sizeof(g_error), "vaInitialize failed for %.160s: %s (%d)",
                 device, vaErrorStr(status), (int)status);
        close(fd);
        return 0;
    }
    vstr = vaQueryVendorString(display);
    snprintf(vendor, vendor_size, "%s", vstr ? vstr : "");
    *fd_out = fd;
    *display_out = display;
    return 1;
}

static int profile_supported(const VAProfile *profiles, int nprofiles, VAProfile profile) {
    for (int i = 0; i < nprofiles; i++) {
        if (profiles[i] == profile)
            return 1;
    }
    return 0;
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
                                   VA_ENC_PACKED_HEADER_PICTURE |
                                   VA_ENC_PACKED_HEADER_SLICE)) !=
                (VA_ENC_PACKED_HEADER_SEQUENCE |
                 VA_ENC_PACKED_HEADER_PICTURE |
                 VA_ENC_PACKED_HEADER_SLICE)) {
                snprintf(g_error, sizeof(g_error),
                         "%s/%s does not support required packed H.264 headers: %#x",
                         h264_profile_name(profile), entrypoint_name(entrypoint), attrs[2].value);
                continue;
            }
            g_profile = profile;
            g_entrypoint = entrypoint;
            return 1;
        }
    }
    snprintf(g_error, sizeof(g_error),
             "VAEntrypointEncSlice/EncSliceLP is not supported for H.264 constrained-baseline/main/high");
    return 0;
}

static int try_device(const char *device) {
    int fd = -1, major = 0, minor = 0;
    VADisplay display = NULL;
    char vendor[256] = "";
    int ok = open_display(device, &fd, &display, &major, &minor, vendor, sizeof(vendor));
    if (!ok)
        return 0;
    ok = h264_encode_supported(display);
    vaTerminate(display);
    close(fd);
    if (ok) {
        snprintf(g_device, sizeof(g_device), "%s", device);
        snprintf(g_vendor, sizeof(g_vendor), "%s", vendor);
        g_major = major;
        g_minor = minor;
        libva_log("libva encode: selected H.264 %s profile with %s",
                  h264_profile_name(g_profile), entrypoint_name(g_entrypoint));
    }
    return ok;
}

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
        libva_log("libva encode startup: %s does not provide H.264 CQP packed-header encode: %s",
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
    libva_log("libva encode startup: no VA-API H.264 CQP packed-header encoder found: %s", g_error);
    return LIBVA_ENC_NOT_AVAILABLE;
}

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
                                              const uint8_t *data, int size,
                                              VABufferID *param_out, VABufferID *data_out) {
    VAEncPackedHeaderParameterBuffer param;
    VAStatus status;

    memset(&param, 0, sizeof(param));
    param.type = type;
    param.bit_length = (uint32_t)size * 8;
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

LibVAEncodeStatus libva_encoder_create(LibVAEncoder **out, int width, int height,
                                       int quality, int speed) {
    LibVAEncoder *enc;
    VAStatus status;
    VAConfigAttrib attrs[3];
    VASurfaceAttrib surface_attrs[2];
    VASurfaceID surfaces[2];
    int major = 0, minor = 0;

    if (!out)
        return LIBVA_ENC_ERROR;
    *out = NULL;
    if (width <= 0 || height <= 0 || (width & 1) || (height & 1))
        return LIBVA_ENC_ERROR;
    if (!g_device[0] && libva_encode_startup() != LIBVA_ENC_OK)
        return LIBVA_ENC_NOT_AVAILABLE;

    enc = (LibVAEncoder *)calloc(1, sizeof(LibVAEncoder));
    if (!enc)
        return LIBVA_ENC_ERROR;

    enc->fd = -1;
    enc->config = VA_INVALID_ID;
    enc->context = VA_INVALID_ID;
    enc->src_surface = VA_INVALID_SURFACE;
    enc->recon_surface = VA_INVALID_SURFACE;
    enc->width = width;
    enc->height = height;
    enc->width_mbs = roundup(width, 16) / 16;
    enc->height_mbs = roundup(height, 16) / 16;
    enc->quality = quality;
    enc->speed = speed;
    enc->qp = quality_to_qp(quality);
    enc->profile = g_profile;
    enc->entrypoint = g_entrypoint;
    enc->last_status = VA_STATUS_SUCCESS;
    snprintf(enc->device, sizeof(enc->device), "%s", g_device);

    if (!open_display(enc->device, &enc->fd, &enc->display, &major, &minor, enc->vendor, sizeof(enc->vendor))) {
        snprintf(enc->last_error, sizeof(enc->last_error), "failed to open VA display for %.200s", enc->device);
        libva_encoder_destroy(enc);
        return LIBVA_ENC_NOT_AVAILABLE;
    }

    attrs[0].type = VAConfigAttribRTFormat;
    attrs[0].value = VA_RT_FORMAT_YUV420;
    attrs[1].type = VAConfigAttribRateControl;
    attrs[1].value = VA_RC_CQP;
    attrs[2].type = VAConfigAttribEncPackedHeaders;
    attrs[2].value = VA_ENC_PACKED_HEADER_SEQUENCE |
                     VA_ENC_PACKED_HEADER_PICTURE |
                     VA_ENC_PACKED_HEADER_SLICE;
    status = vaCreateConfig(enc->display, enc->profile,
                            enc->entrypoint, attrs, 3, &enc->config);
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
                              (unsigned int)enc->width_mbs * 16,
                              (unsigned int)enc->height_mbs * 16,
                              surfaces, 2, surface_attrs, 2);
    if (status != VA_STATUS_SUCCESS) {
        set_error(enc, status, "vaCreateSurfaces");
        libva_encoder_destroy(enc);
        return LIBVA_ENC_ERROR;
    }
    enc->src_surface = surfaces[0];
    enc->recon_surface = surfaces[1];

    status = vaCreateContext(enc->display, enc->config,
                             enc->width_mbs * 16, enc->height_mbs * 16,
                             VA_PROGRESSIVE, surfaces, 2, &enc->context);
    if (status != VA_STATUS_SUCCESS) {
        set_error(enc, status, "vaCreateContext");
        libva_encoder_destroy(enc);
        return LIBVA_ENC_ERROR;
    }

    enc->bitstream_size = (size_t)enc->width_mbs * enc->height_mbs * 16 * 16 * 3 / 2 + 1024 * 1024;
    enc->bitstream_data = (uint8_t *)malloc(enc->bitstream_size);
    if (!enc->bitstream_data) {
        snprintf(enc->last_error, sizeof(enc->last_error), "failed to allocate encoded buffer");
        libva_encoder_destroy(enc);
        return LIBVA_ENC_ERROR;
    }

    libva_log("libva encoder create: %dx%d quality=%d speed=%d qp=%d device=%s vendor=%s",
              width, height, quality, speed, enc->qp, enc->device, enc->vendor);
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
        if (enc->recon_surface != VA_INVALID_SURFACE)
            vaDestroySurfaces(enc->display, &enc->recon_surface, 1);
        if (enc->config != VA_INVALID_ID)
            vaDestroyConfig(enc->display, enc->config);
        vaTerminate(enc->display);
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
    frame->frame_type = LIBVA_ENC_FRAME_IDR;
    return LIBVA_ENC_OK;
}

LibVAEncodeStatus libva_encoder_encode(LibVAEncoder *enc,
                                       const uint8_t *y, int y_stride,
                                       const uint8_t *uv, int uv_stride,
                                       LibVAEncodedFrame *frame) {
    VABufferID buffers[11];
    int nbuf = 0;
    VABufferID coded_buf = VA_INVALID_ID;
    VAEncSequenceParameterBufferH264 seq;
    VAEncPictureParameterBufferH264 pic;
    VAEncSliceParameterBufferH264 slice;
    uint8_t sps[128], pps[64], sh[64];
    int sps_size, pps_size, sh_size;
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

    status = vaCreateBuffer(enc->display, enc->context, VAEncCodedBufferType,
                            (unsigned int)enc->bitstream_size, 1, NULL, &coded_buf);
    if (status != VA_STATUS_SUCCESS)
        return set_error(enc, status, "vaCreateBuffer(coded)");
    buffers[nbuf++] = coded_buf;

    memset(&seq, 0, sizeof(seq));
    seq.seq_parameter_set_id = 0;
    seq.level_idc = LIBVA_H264_LEVEL_IDC;
    seq.intra_period = 1;
    seq.intra_idr_period = 1;
    seq.ip_period = 1;
    seq.bits_per_second = 0;
    seq.max_num_ref_frames = 1;
    seq.picture_width_in_mbs = (uint16_t)enc->width_mbs;
    seq.picture_height_in_mbs = (uint16_t)enc->height_mbs;
    seq.seq_fields.bits.chroma_format_idc = 1;
    seq.seq_fields.bits.frame_mbs_only_flag = 1;
    seq.seq_fields.bits.direct_8x8_inference_flag = 1;
    seq.seq_fields.bits.log2_max_frame_num_minus4 = 0;
    seq.seq_fields.bits.pic_order_cnt_type = 0;
    seq.seq_fields.bits.log2_max_pic_order_cnt_lsb_minus4 = 0;
    seq.bit_depth_luma_minus8 = 0;
    seq.bit_depth_chroma_minus8 = 0;
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
    sps_size = make_sps(enc, sps, sizeof(sps));
    if (create_packed_header(enc, VAEncPackedHeaderSequence, sps, sps_size,
                             &buffers[nbuf], &buffers[nbuf + 1]) != LIBVA_ENC_OK) {
        destroy_buffers(enc, buffers, nbuf + 2);
        return LIBVA_ENC_ERROR;
    }
    nbuf += 2;

    memset(&pic, 0, sizeof(pic));
    pic.CurrPic.picture_id = enc->recon_surface;
    pic.CurrPic.frame_idx = 0;
    pic.CurrPic.flags = VA_PICTURE_H264_SHORT_TERM_REFERENCE;
    pic.CurrPic.TopFieldOrderCnt = 0;
    pic.CurrPic.BottomFieldOrderCnt = 0;
    for (int i = 0; i < 16; i++)
        fill_invalid_picture(&pic.ReferenceFrames[i]);
    pic.coded_buf = coded_buf;
    pic.pic_parameter_set_id = 0;
    pic.seq_parameter_set_id = 0;
    pic.last_picture = 0;
    pic.frame_num = 0;
    pic.pic_init_qp = (uint8_t)enc->qp;
    pic.num_ref_idx_l0_active_minus1 = 0;
    pic.num_ref_idx_l1_active_minus1 = 0;
    pic.chroma_qp_index_offset = 0;
    pic.second_chroma_qp_index_offset = 0;
    pic.pic_fields.bits.idr_pic_flag = 1;
    pic.pic_fields.bits.reference_pic_flag = 1;
    pic.pic_fields.bits.entropy_coding_mode_flag = 0;
    pic.pic_fields.bits.deblocking_filter_control_present_flag = 1;
    status = vaCreateBuffer(enc->display, enc->context, VAEncPictureParameterBufferType,
                            sizeof(pic), 1, &pic, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(picture)");
    }
    pps_size = make_pps(enc, pps, sizeof(pps));
    if (create_packed_header(enc, VAEncPackedHeaderPicture, pps, pps_size,
                             &buffers[nbuf], &buffers[nbuf + 1]) != LIBVA_ENC_OK) {
        destroy_buffers(enc, buffers, nbuf + 2);
        return LIBVA_ENC_ERROR;
    }
    nbuf += 2;

    memset(&slice, 0, sizeof(slice));
    slice.macroblock_address = 0;
    slice.num_macroblocks = (uint32_t)(enc->width_mbs * enc->height_mbs);
    slice.macroblock_info = VA_INVALID_ID;
    slice.slice_type = 2;
    slice.pic_parameter_set_id = 0;
    slice.idr_pic_id = 0;
    slice.pic_order_cnt_lsb = 0;
    slice.num_ref_idx_l0_active_minus1 = 0;
    slice.num_ref_idx_l1_active_minus1 = 0;
    for (int i = 0; i < 32; i++) {
        fill_invalid_picture(&slice.RefPicList0[i]);
        fill_invalid_picture(&slice.RefPicList1[i]);
    }
    slice.slice_qp_delta = 0;
    slice.disable_deblocking_filter_idc = 0;
    slice.slice_alpha_c0_offset_div2 = 0;
    slice.slice_beta_offset_div2 = 0;
    status = vaCreateBuffer(enc->display, enc->context, VAEncSliceParameterBufferType,
                            sizeof(slice), 1, &slice, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(enc, buffers, nbuf);
        return set_error(enc, status, "vaCreateBuffer(slice)");
    }
    sh_size = make_slice_header(enc, sh, sizeof(sh));
    if (create_packed_header(enc, VAEncPackedHeaderSlice, sh, sh_size,
                             &buffers[nbuf], &buffers[nbuf + 1]) != LIBVA_ENC_OK) {
        destroy_buffers(enc, buffers, nbuf + 2);
        return LIBVA_ENC_ERROR;
    }
    nbuf += 2;

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
    frame->us_submit = (int)(t1 - t0);
    frame->us_sync = (int)(t2 - t1);
    enc->frames++;
    return LIBVA_ENC_OK;
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
