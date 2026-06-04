/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: libva decoder - C implementation.
 * ABOUTME: Minimal VA-API H.264 decoder with NV12/YUV444 output extraction. */

#include "va_decode.h"
#include "va_common.h"

#include <va/va.h>
#include <va/va_dec_vp8.h>
#include <va/va_dec_vp9.h>

#include <dirent.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define LIBVA_LOG2_MAX_FRAME_NUM_MINUS4 4
#define LIBVA_LOG2_MAX_PIC_ORDER_CNT_LSB_MINUS4 4
#define LIBVA_FRAME_NUM_BITS (LIBVA_LOG2_MAX_FRAME_NUM_MINUS4 + 4)
#define LIBVA_POC_LSB_BITS (LIBVA_LOG2_MAX_PIC_ORDER_CNT_LSB_MINUS4 + 4)

static libva_log_fn g_log_fn = NULL;
static char g_device[256] = "";
static char g_vendor[256] = "";
static char g_error[256] = "";
static int g_major = 0;
static int g_minor = 0;
static int g_h264_420_supported = 0;
static VAProfile g_h264_420_profile = VAProfileH264ConstrainedBaseline;
static int g_h264_444_supported = 0;
static VAProfile g_h264_444_profile = VAProfileH264High;
static int g_vp8_420_supported = 0;
static int g_vp9_420_supported = 0;
static int g_vp9_444_supported = 0;

struct H264Params;

struct LibVADecoder {
    int             fd;
    VADisplay       display;
    VAConfigID      config;
    VAContextID     context;
    VASurfaceID     surfaces[4];
    int             surface_index;
    int             width;
    int             height;
    int             surface_width;
    int             surface_height;
    LibVACodec      codec;
    VAProfile       profile;
    unsigned int    rt_format;
    int             output_444;
    unsigned long   frames;
    int             have_reference;
    int             ref_surface_index;
    int             ref_frame_num;
    int             ref_poc_lsb;
    struct H264Params *h264_params;
    uint8_t        *planes[3];
    size_t          plane_caps[3];
    int             last_status;
    char            last_error[256];
    char            device[256];
    char            vendor[256];
};

struct BitReader {
    const uint8_t *data;
    int size;
    int byte_pos;
    int bit_pos;
    int zeros;
    int bits_read;
};

struct H264Params {
    int valid_sps;
    int valid_pps;
    int chroma_format_idc;
    int separate_colour_plane_flag;
    int log2_max_frame_num_minus4;
    int pic_order_cnt_type;
    int log2_max_pic_order_cnt_lsb_minus4;
    int delta_pic_order_always_zero_flag;
    int max_num_ref_frames;
    int gaps_in_frame_num_value_allowed_flag;
    int width_mbs_minus1;
    int height_mbs_minus1;
    int frame_mbs_only_flag;
    int mb_adaptive_frame_field_flag;
    int direct_8x8_inference_flag;
    int entropy_coding_mode_flag;
    int weighted_pred_flag;
    int weighted_bipred_idc;
    int transform_8x8_mode_flag;
    int pic_order_present_flag;
    int deblocking_filter_control_present_flag;
    int redundant_pic_cnt_present_flag;
    int constrained_intra_pred_flag;
    int num_ref_idx_l0_active_minus1;
    int num_ref_idx_l1_active_minus1;
    int pic_init_qp_minus26;
    int pic_init_qs_minus26;
    int chroma_qp_index_offset;
    int second_chroma_qp_index_offset;
};

static void init_h264_params(struct H264Params *params);

struct H264SliceInfo {
    int offset;
    int size;
    int nal_type;
    int nal_ref_idc;
    int first_mb;
    int slice_type;
    int frame_num;
    int poc_lsb;
    int num_ref_idx_l0_active_minus1;
    int num_ref_idx_l1_active_minus1;
    int direct_spatial_mv_pred_flag;
    int cabac_init_idc;
    int slice_qp_delta;
    int disable_deblocking_filter_idc;
    int slice_alpha_c0_offset_div2;
    int slice_beta_offset_div2;
    int luma_log2_weight_denom;
    int chroma_log2_weight_denom;
    uint8_t luma_weight_l0_flag;
    int16_t luma_weight_l0[32];
    int16_t luma_offset_l0[32];
    uint8_t chroma_weight_l0_flag;
    int16_t chroma_weight_l0[32][2];
    int16_t chroma_offset_l0[32][2];
    int bit_offset;
};

void libva_decode_set_log(libva_log_fn fn) {
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

static LibVADecodeStatus set_error(LibVADecoder *dec, VAStatus status, const char *context) {
    if (dec) {
        dec->last_status = (int)status;
        snprintf(dec->last_error, sizeof(dec->last_error), "%s failed: %s (%d)",
                 context, vaErrorStr(status), (int)status);
        libva_log("libva decode error: %s", dec->last_error);
    }
    return LIBVA_DEC_ERROR;
}

static LibVADecodeStatus set_message(LibVADecoder *dec, LibVADecodeStatus status, const char *message) {
    if (dec) {
        dec->last_status = (int)status;
        snprintf(dec->last_error, sizeof(dec->last_error), "%s", message);
        libva_log("libva decode error: %s", dec->last_error);
    } else {
        snprintf(g_error, sizeof(g_error), "%s", message);
    }
    return status;
}

const char* libva_decode_status_str(LibVADecodeStatus status) {
    switch (status) {
        case LIBVA_DEC_OK:            return "ok";
        case LIBVA_DEC_ERROR:         return "error";
        case LIBVA_DEC_NOT_AVAILABLE: return "not_available";
        case LIBVA_DEC_UNSUPPORTED:   return "unsupported";
        default:                      return "unknown";
    }
}

const char* libva_decode_format_str(LibVADecodeFormat format) {
    switch (format) {
        case LIBVA_DEC_FMT_NV12:    return "NV12";
        case LIBVA_DEC_FMT_YUV444P: return "YUV444P";
        case LIBVA_DEC_FMT_XYUV:    return "XYUV";
        case LIBVA_DEC_FMT_AYUV:    return "AYUV";
        default:                    return "unknown";
    }
}

static int vld_supported(VADisplay display, VAProfile profile, unsigned int rt_format) {
    VAEntrypoint entrypoints[32];
    int nentrypoints = 0;
    VAConfigAttrib attr;
    VAStatus status = vaQueryConfigEntrypoints(display, profile, entrypoints, &nentrypoints);
    if (status != VA_STATUS_SUCCESS) {
        snprintf(g_error, sizeof(g_error), "vaQueryConfigEntrypoints(%s) failed: %s (%d)",
                 h264_profile_name(profile), vaErrorStr(status), (int)status);
        return 0;
    }
    if (!entrypoint_supported(entrypoints, nentrypoints, VAEntrypointVLD))
        return 0;
    attr.type = VAConfigAttribRTFormat;
    attr.value = 0;
    status = vaGetConfigAttributes(display, profile, VAEntrypointVLD, &attr, 1);
    if (status != VA_STATUS_SUCCESS) {
        snprintf(g_error, sizeof(g_error), "vaGetConfigAttributes(%s, VLD) failed: %s (%d)",
                 h264_profile_name(profile), vaErrorStr(status), (int)status);
        return 0;
    }
    return (attr.value & rt_format) != 0;
}

static int try_device(const char *device) {
    int fd = -1, major = 0, minor = 0;
    VADisplay display = NULL;
    char vendor[256] = "";
    VAProfile profiles[64];
    int nprofiles = 0;
    int h264_420 = 0, h264_444 = 0, vp8_420 = 0, vp9_420 = 0, vp9_444 = 0;
    VAProfile h264_420_profile = VAProfileH264ConstrainedBaseline;
    VAProfile h264_444_profile = VAProfileH264High;
    VAStatus status;

    if (!libva_open_display(device, &fd, &display, &major, &minor, vendor, sizeof(vendor),
                            g_error, sizeof(g_error)))
        return 0;

    status = vaQueryConfigProfiles(display, profiles, &nprofiles);
    if (status != VA_STATUS_SUCCESS) {
        snprintf(g_error, sizeof(g_error), "vaQueryConfigProfiles failed: %s (%d)",
                 vaErrorStr(status), (int)status);
        vaTerminate(display);
        close(fd);
        return 0;
    }

    static const VAProfile h264_profiles[] = {
        VAProfileH264High,
        VAProfileH264Main,
        VAProfileH264ConstrainedBaseline,
    };
    for (unsigned int i = 0; i < sizeof(h264_profiles) / sizeof(h264_profiles[0]); i++) {
        VAProfile profile = h264_profiles[i];
        if (profile_supported(profiles, nprofiles, profile) &&
            vld_supported(display, profile, VA_RT_FORMAT_YUV420)) {
            h264_420 = 1;
            h264_420_profile = profile;
            break;
        }
    }
    for (unsigned int i = 0; i < sizeof(h264_profiles) / sizeof(h264_profiles[0]); i++) {
        VAProfile profile = h264_profiles[i];
        if (profile_supported(profiles, nprofiles, profile) &&
            vld_supported(display, profile, VA_RT_FORMAT_YUV444)) {
            h264_444 = 1;
            h264_444_profile = profile;
            break;
        }
    }
    if (profile_supported(profiles, nprofiles, VAProfileVP8Version0_3))
        vp8_420 = vld_supported(display, VAProfileVP8Version0_3, VA_RT_FORMAT_YUV420);
    if (profile_supported(profiles, nprofiles, VAProfileVP9Profile0))
        vp9_420 = vld_supported(display, VAProfileVP9Profile0, VA_RT_FORMAT_YUV420);
    if (profile_supported(profiles, nprofiles, VAProfileVP9Profile1))
        vp9_444 = vld_supported(display, VAProfileVP9Profile1, VA_RT_FORMAT_YUV444);

    vaTerminate(display);
    close(fd);
    if (h264_420 || h264_444 || vp8_420 || vp9_420 || vp9_444) {
        snprintf(g_device, sizeof(g_device), "%s", device);
        snprintf(g_vendor, sizeof(g_vendor), "%s", vendor);
        g_major = major;
        g_minor = minor;
        g_h264_420_supported = h264_420;
        g_h264_420_profile = h264_420_profile;
        g_h264_444_supported = h264_444;
        g_h264_444_profile = h264_444_profile;
        g_vp8_420_supported = vp8_420;
        g_vp9_420_supported = vp9_420;
        g_vp9_444_supported = vp9_444;
        libva_log("libva decode: selected %s (%s), h264-420=%d h264-444=%d vp8-420=%d vp9-420=%d vp9-444=%d",
                  g_device, g_vendor, h264_420, h264_444, vp8_420, vp9_420, vp9_444);
    }
    return h264_420 || h264_444 || vp8_420 || vp9_420 || vp9_444;
}

LibVADecodeStatus libva_decode_startup(void) {
    const char *env_device = getenv("XPRA_LIBVA_DEVICE");
    DIR *dir;
    struct dirent *entry;

    g_error[0] = 0;
    if (env_device && env_device[0]) {
        if (try_device(env_device))
            return LIBVA_DEC_OK;
        return LIBVA_DEC_NOT_AVAILABLE;
    }
    if (try_device("/dev/dri/renderD128"))
        return LIBVA_DEC_OK;
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
                return LIBVA_DEC_OK;
            }
        }
        closedir(dir);
    }
    if (!g_error[0])
        snprintf(g_error, sizeof(g_error), "no VA-API render node found");
    return LIBVA_DEC_NOT_AVAILABLE;
}

void libva_decode_shutdown(void) {
    libva_log("libva decode shutdown");
}

const char *libva_decode_get_device(void) {
    return g_device;
}

const char *libva_decode_get_vendor(void) {
    return g_vendor;
}

const char *libva_decode_get_last_error(void) {
    return g_error;
}

int libva_decode_get_major(void) {
    return g_major;
}

int libva_decode_get_minor(void) {
    return g_minor;
}

int libva_decode_supports(const char *encoding, const char *colorspace) {
    LibVACodec codec;
    if (!g_device[0] && libva_decode_startup() != LIBVA_DEC_OK)
        return 0;
    if (!codec_from_name(encoding, &codec))
        return 0;
    if (codec == LIBVA_CODEC_H264) {
        if (strcmp(colorspace, "YUV420P") == 0)
            return g_h264_420_supported;
        if (strcmp(colorspace, "YUV444P") == 0)
            return g_h264_444_supported;
    }
    /* VP8/VP9 VLD probing is kept visible in get_info(), but v1 does not
     * advertise specs until their probability/header parser is complete. */
    return 0;
}

static void fill_invalid_picture(VAPictureH264 *pic) {
    memset(pic, 0, sizeof(*pic));
    pic->picture_id = VA_INVALID_SURFACE;
    pic->flags = VA_PICTURE_H264_INVALID;
}

static void destroy_buffers(LibVADecoder *dec, VABufferID *buffers, int count) {
    for (int i = 0; i < count; i++) {
        if (buffers[i] != VA_INVALID_ID) {
            vaDestroyBuffer(dec->display, buffers[i]);
            buffers[i] = VA_INVALID_ID;
        }
    }
}

LibVADecodeStatus libva_decoder_create(LibVADecoder **out, const char *encoding,
                                       int width, int height, const char *colorspace) {
    LibVACodec codec;
    LibVADecoder *dec;
    VAStatus status;
    VAConfigAttrib attr;
    VASurfaceAttrib surface_attrs[2];
    int major = 0, minor = 0;

    if (!out)
        return LIBVA_DEC_ERROR;
    *out = NULL;
    if (!codec_from_name(encoding, &codec))
        return LIBVA_DEC_NOT_AVAILABLE;
    if (width <= 0 || height <= 0)
        return LIBVA_DEC_ERROR;
    if (!g_device[0] && libva_decode_startup() != LIBVA_DEC_OK)
        return LIBVA_DEC_NOT_AVAILABLE;
    if (!libva_decode_supports(encoding, colorspace))
        return LIBVA_DEC_NOT_AVAILABLE;

    dec = (LibVADecoder *)calloc(1, sizeof(LibVADecoder));
    if (!dec)
        return LIBVA_DEC_ERROR;
    dec->h264_params = (struct H264Params *)calloc(1, sizeof(*dec->h264_params));
    if (!dec->h264_params) {
        free(dec);
        return LIBVA_DEC_ERROR;
    }
    init_h264_params(dec->h264_params);
    dec->fd = -1;
    dec->config = VA_INVALID_ID;
    dec->context = VA_INVALID_ID;
    for (int i = 0; i < 4; i++)
        dec->surfaces[i] = VA_INVALID_SURFACE;
    dec->width = width;
    dec->height = height;
    dec->surface_width = roundup(width, 16);
    dec->surface_height = roundup(height, 16);
    dec->codec = codec;
    dec->rt_format = VA_RT_FORMAT_YUV420;
    dec->profile = g_h264_420_profile;
    if (strcmp(colorspace, "YUV444P") == 0) {
        dec->rt_format = VA_RT_FORMAT_YUV444;
        dec->profile = g_h264_444_profile;
        dec->output_444 = 1;
    }
    dec->last_status = VA_STATUS_SUCCESS;
    snprintf(dec->device, sizeof(dec->device), "%s", g_device);

    if (!libva_open_display(dec->device, &dec->fd, &dec->display, &major, &minor,
                            dec->vendor, sizeof(dec->vendor),
                            g_error, sizeof(g_error))) {
        libva_decoder_destroy(dec);
        return LIBVA_DEC_NOT_AVAILABLE;
    }

    attr.type = VAConfigAttribRTFormat;
    attr.value = dec->rt_format;
    status = vaCreateConfig(dec->display, dec->profile, VAEntrypointVLD, &attr, 1, &dec->config);
    if (status != VA_STATUS_SUCCESS) {
        set_error(dec, status, "vaCreateConfig");
        libva_decoder_destroy(dec);
        return LIBVA_DEC_ERROR;
    }

    memset(surface_attrs, 0, sizeof(surface_attrs));
    surface_attrs[0].type = VASurfaceAttribPixelFormat;
    surface_attrs[0].flags = VA_SURFACE_ATTRIB_SETTABLE;
    surface_attrs[0].value.type = VAGenericValueTypeInteger;
    surface_attrs[0].value.value.i = dec->output_444 ? VA_FOURCC_444P : VA_FOURCC_NV12;
    surface_attrs[1].type = VASurfaceAttribUsageHint;
    surface_attrs[1].flags = VA_SURFACE_ATTRIB_SETTABLE;
    surface_attrs[1].value.type = VAGenericValueTypeInteger;
    surface_attrs[1].value.value.i = VA_SURFACE_ATTRIB_USAGE_HINT_DECODER;
    status = vaCreateSurfaces(dec->display, dec->rt_format,
                              (unsigned int)dec->surface_width,
                              (unsigned int)dec->surface_height,
                              dec->surfaces, 4, surface_attrs, 2);
    if (status != VA_STATUS_SUCCESS) {
        set_error(dec, status, "vaCreateSurfaces");
        libva_decoder_destroy(dec);
        return LIBVA_DEC_ERROR;
    }

    status = vaCreateContext(dec->display, dec->config,
                             dec->surface_width, dec->surface_height,
                             VA_PROGRESSIVE, dec->surfaces, 4, &dec->context);
    if (status != VA_STATUS_SUCCESS) {
        set_error(dec, status, "vaCreateContext");
        libva_decoder_destroy(dec);
        return LIBVA_DEC_ERROR;
    }

    libva_log("libva %s decoder create: %dx%d surface=%dx%d colorspace=%s profile=%s device=%s vendor=%s",
              codec_name(dec->codec), width, height, dec->surface_width, dec->surface_height,
              colorspace, h264_profile_name(dec->profile), dec->device, dec->vendor);
    *out = dec;
    return LIBVA_DEC_OK;
}

void libva_decoder_destroy(LibVADecoder *dec) {
    if (!dec)
        return;
    if (dec->display) {
        if (dec->context != VA_INVALID_ID)
            vaDestroyContext(dec->display, dec->context);
        for (int i = 0; i < 4; i++) {
            if (dec->surfaces[i] != VA_INVALID_SURFACE)
                vaDestroySurfaces(dec->display, &dec->surfaces[i], 1);
        }
        if (dec->config != VA_INVALID_ID)
            vaDestroyConfig(dec->display, dec->config);
        vaTerminate(dec->display);
    }
    if (dec->fd >= 0)
        close(dec->fd);
    for (int i = 0; i < 3; i++)
        free(dec->planes[i]);
    free(dec->h264_params);
    free(dec);
}

static void br_init(struct BitReader *br, const uint8_t *data, int size) {
    memset(br, 0, sizeof(*br));
    br->data = data;
    br->size = size;
}

static int br_read_bit(struct BitReader *br) {
    int bit;
    if (br->byte_pos >= br->size)
        return 0;
    if (br->zeros >= 2 && br->data[br->byte_pos] == 0x03) {
        br->byte_pos++;
        br->zeros = 0;
        if (br->byte_pos >= br->size)
            return 0;
    }
    bit = (br->data[br->byte_pos] >> (7 - br->bit_pos)) & 1;
    br->bit_pos++;
    br->bits_read++;
    if (br->bit_pos == 8) {
        uint8_t b = br->data[br->byte_pos];
        br->zeros = b == 0 ? br->zeros + 1 : 0;
        br->byte_pos++;
        br->bit_pos = 0;
    }
    return bit;
}

static int br_bits_left(const struct BitReader *br) {
    int bits = br->size * 8 - br->byte_pos * 8 - br->bit_pos;
    return bits > 0 ? bits : 0;
}

static unsigned int br_bits(struct BitReader *br, int bits) {
    unsigned int v = 0;
    for (int i = 0; i < bits; i++)
        v = (v << 1) | (unsigned int)br_read_bit(br);
    return v;
}

static unsigned int br_ue(struct BitReader *br) {
    int zeros = 0;
    while (zeros < 32 && br_read_bit(br) == 0)
        zeros++;
    if (zeros == 0)
        return 0;
    return ((1U << zeros) - 1U) + br_bits(br, zeros);
}

static int br_se(struct BitReader *br) {
    unsigned int ue = br_ue(br);
    int v = (int)((ue + 1) >> 1);
    return (ue & 1) ? v : -v;
}

static int br_more_rbsp_data(const struct BitReader *br) {
    struct BitReader rb = *br;
    while (br_bits_left(&rb) > 0) {
        if (br_read_bit(&rb)) {
            while (br_bits_left(&rb) > 0) {
                if (br_read_bit(&rb))
                    return 1;
            }
            return 0;
        }
    }
    return 0;
}

static int find_start_code(const uint8_t *data, int size, int offset, int *prefix) {
    for (int i = offset; i + 3 < size; i++) {
        if (data[i] == 0 && data[i + 1] == 0) {
            if (data[i + 2] == 1) {
                *prefix = 3;
                return i;
            }
            if (i + 4 < size && data[i + 2] == 0 && data[i + 3] == 1) {
                *prefix = 4;
                return i;
            }
        }
    }
    return -1;
}

static void skip_h264_scaling_list(struct BitReader *br, int size) {
    int last_scale = 8;
    int next_scale = 8;
    for (int j = 0; j < size; j++) {
        if (next_scale != 0) {
            int delta_scale = br_se(br);
            next_scale = (last_scale + delta_scale + 256) & 0xff;
        }
        last_scale = next_scale == 0 ? last_scale : next_scale;
    }
}

static int parse_h264_sps(const uint8_t *nal, int size, struct H264Params *params) {
    struct BitReader br;
    int profile_idc;
    if (size < 2)
        return 0;
    br_init(&br, nal + 1, size - 1);
    profile_idc = (int)br_bits(&br, 8);
    br_bits(&br, 8);                  /* constraint flags + reserved */
    br_bits(&br, 8);                  /* level_idc */
    br_ue(&br);                       /* seq_parameter_set_id */
    params->chroma_format_idc = 1;
    params->separate_colour_plane_flag = 0;
    if (profile_idc == 100 || profile_idc == 110 || profile_idc == 122 ||
        profile_idc == 244 || profile_idc == 44 || profile_idc == 83 ||
        profile_idc == 86 || profile_idc == 118 || profile_idc == 128 ||
        profile_idc == 138 || profile_idc == 144) {
        params->chroma_format_idc = (int)br_ue(&br);
        if (params->chroma_format_idc == 3)
            params->separate_colour_plane_flag = (int)br_bits(&br, 1);
        br_ue(&br);                   /* bit_depth_luma_minus8 */
        br_ue(&br);                   /* bit_depth_chroma_minus8 */
        br_bits(&br, 1);              /* qpprime_y_zero_transform_bypass_flag */
        if (br_bits(&br, 1)) {        /* seq_scaling_matrix_present_flag */
            int count = params->chroma_format_idc != 3 ? 8 : 12;
            for (int i = 0; i < count; i++) {
                if (br_bits(&br, 1))
                    skip_h264_scaling_list(&br, i < 6 ? 16 : 64);
            }
        }
    }
    params->log2_max_frame_num_minus4 = (int)br_ue(&br);
    params->pic_order_cnt_type = (int)br_ue(&br);
    if (params->pic_order_cnt_type == 0) {
        params->log2_max_pic_order_cnt_lsb_minus4 = (int)br_ue(&br);
    } else if (params->pic_order_cnt_type == 1) {
        params->delta_pic_order_always_zero_flag = (int)br_bits(&br, 1);
        br_se(&br);                   /* offset_for_non_ref_pic */
        br_se(&br);                   /* offset_for_top_to_bottom_field */
        int count = (int)br_ue(&br);
        for (int i = 0; i < count; i++)
            br_se(&br);
    }
    params->max_num_ref_frames = (int)br_ue(&br);
    params->gaps_in_frame_num_value_allowed_flag = (int)br_bits(&br, 1);
    params->width_mbs_minus1 = (int)br_ue(&br);
    params->height_mbs_minus1 = (int)br_ue(&br);
    params->frame_mbs_only_flag = (int)br_bits(&br, 1);
    if (!params->frame_mbs_only_flag)
        params->mb_adaptive_frame_field_flag = (int)br_bits(&br, 1);
    params->direct_8x8_inference_flag = (int)br_bits(&br, 1);
    params->valid_sps = 1;
    return 1;
}

static int parse_h264_pps(const uint8_t *nal, int size, struct H264Params *params) {
    struct BitReader br;
    int num_slice_groups_minus1;
    if (size < 2)
        return 0;
    br_init(&br, nal + 1, size - 1);
    br_ue(&br);                       /* pic_parameter_set_id */
    br_ue(&br);                       /* seq_parameter_set_id */
    params->entropy_coding_mode_flag = (int)br_bits(&br, 1);
    params->pic_order_present_flag = (int)br_bits(&br, 1);
    num_slice_groups_minus1 = (int)br_ue(&br);
    if (num_slice_groups_minus1 != 0)
        return 0;
    params->num_ref_idx_l0_active_minus1 = (int)br_ue(&br);
    params->num_ref_idx_l1_active_minus1 = (int)br_ue(&br);
    params->weighted_pred_flag = (int)br_bits(&br, 1);
    params->weighted_bipred_idc = (int)br_bits(&br, 2);
    params->pic_init_qp_minus26 = br_se(&br);
    params->pic_init_qs_minus26 = br_se(&br);
    params->chroma_qp_index_offset = br_se(&br);
    params->deblocking_filter_control_present_flag = (int)br_bits(&br, 1);
    params->constrained_intra_pred_flag = (int)br_bits(&br, 1);
    params->redundant_pic_cnt_present_flag = (int)br_bits(&br, 1);
    params->second_chroma_qp_index_offset = params->chroma_qp_index_offset;
    if (br_more_rbsp_data(&br)) {
        params->transform_8x8_mode_flag = (int)br_bits(&br, 1);
        if (br_bits(&br, 1)) {        /* pic_scaling_matrix_present_flag */
            int count = 6;
            if (params->transform_8x8_mode_flag)
                count += params->chroma_format_idc == 3 ? 6 : 2;
            for (int i = 0; i < count; i++) {
                if (br_bits(&br, 1))
                    skip_h264_scaling_list(&br, i < 6 ? 16 : 64);
            }
        }
        params->second_chroma_qp_index_offset = br_se(&br);
    }
    params->valid_pps = 1;
    return 1;
}

static void init_h264_params(struct H264Params *params) {
    memset(params, 0, sizeof(*params));
    params->chroma_format_idc = 1;
    params->log2_max_frame_num_minus4 = LIBVA_LOG2_MAX_FRAME_NUM_MINUS4;
    params->log2_max_pic_order_cnt_lsb_minus4 = LIBVA_LOG2_MAX_PIC_ORDER_CNT_LSB_MINUS4;
    params->max_num_ref_frames = 1;
    params->frame_mbs_only_flag = 1;
    params->direct_8x8_inference_flag = 1;
    params->deblocking_filter_control_present_flag = 1;
}

static void fill_h264_default_iq_matrix(VAIQMatrixBufferH264 *iq) {
    memset(iq, 0, sizeof(*iq));
    for (int i = 0; i < 6; i++) {
        for (int j = 0; j < 16; j++)
            iq->ScalingList4x4[i][j] = 16;
    }
    for (int i = 0; i < 2; i++) {
        for (int j = 0; j < 64; j++)
            iq->ScalingList8x8[i][j] = 16;
    }
}

static void parse_h264_params(const uint8_t *data, int size, struct H264Params *params) {
    int prefix = 0;
    int start;
    start = find_start_code(data, size, 0, &prefix);
    while (start >= 0) {
        int nal = start + prefix;
        int next_prefix = 0;
        int next = find_start_code(data, size, nal + 1, &next_prefix);
        int end = next >= 0 ? next : size;
        if (nal < end) {
            int type = data[nal] & 0x1f;
            if (type == 7)
                parse_h264_sps(data + nal, end - nal, params);
            else if (type == 8)
                parse_h264_pps(data + nal, end - nal, params);
        }
        start = next;
        prefix = next_prefix;
    }
}

static int skip_h264_ref_pic_list_modification(struct BitReader *br, int slice_type_mod) {
    int flags = slice_type_mod == 1 ? 2 : 1;
    if (slice_type_mod == 2 || slice_type_mod == 4)
        return 1;
    for (int list = 0; list < flags; list++) {
        if (br_bits(br, 1)) {         /* ref_pic_list_modification_flag_l[01] */
            unsigned int op;
            do {
                op = br_ue(br);       /* modification_of_pic_nums_idc */
                if (op == 0 || op == 1)
                    br_ue(br);        /* abs_diff_pic_num_minus1 */
                else if (op == 2)
                    br_ue(br);        /* long_term_pic_num */
                else if (op == 4 || op == 5)
                    br_ue(br);        /* abs_diff_view_idx_minus1 */
            } while (op != 3 && br_bits_left(br) > 0);
        }
    }
    return 1;
}

static void skip_h264_dec_ref_pic_marking(struct BitReader *br, int nal_type, int nal_ref_idc) {
    if (!nal_ref_idc)
        return;
    if (nal_type == 5) {
        br_bits(br, 1);               /* no_output_of_prior_pics_flag */
        br_bits(br, 1);               /* long_term_reference_flag */
        return;
    }
    if (br_bits(br, 1)) {             /* adaptive_ref_pic_marking_mode_flag */
        unsigned int op;
        do {
            op = br_ue(br);           /* memory_management_control_operation */
            if (op == 1 || op == 3)
                br_ue(br);            /* difference_of_pic_nums_minus1 */
            if (op == 2)
                br_ue(br);            /* long_term_pic_num */
            if (op == 3 || op == 6)
                br_ue(br);            /* long_term_frame_idx */
            if (op == 4)
                br_ue(br);            /* max_long_term_frame_idx_plus1 */
        } while (op != 0 && br_bits_left(br) > 0);
    }
}

static void init_h264_weight_defaults(struct H264SliceInfo *si) {
    int luma_weight = 1 << si->luma_log2_weight_denom;
    int chroma_weight = 1 << si->chroma_log2_weight_denom;
    for (int i = 0; i < 32; i++) {
        si->luma_weight_l0[i] = (int16_t)luma_weight;
        si->luma_offset_l0[i] = 0;
        for (int c = 0; c < 2; c++) {
            si->chroma_weight_l0[i][c] = (int16_t)chroma_weight;
            si->chroma_offset_l0[i][c] = 0;
        }
    }
}

static void parse_h264_pred_weight_table(struct BitReader *br, const struct H264Params *params,
                                         struct H264SliceInfo *si) {
    int l0_refs = clamp_int(si->num_ref_idx_l0_active_minus1, 0, 31);
    si->luma_log2_weight_denom = (int)br_ue(br);
    if (params->chroma_format_idc != 0)
        si->chroma_log2_weight_denom = (int)br_ue(br);
    init_h264_weight_defaults(si);
    for (int i = 0; i <= l0_refs; i++) {
        if (br_bits(br, 1)) {
            if (i == 0)
                si->luma_weight_l0_flag = 1;
            si->luma_weight_l0[i] = (int16_t)br_se(br);
            si->luma_offset_l0[i] = (int16_t)br_se(br);
        }
        if (params->chroma_format_idc != 0 && br_bits(br, 1)) {
            if (i == 0)
                si->chroma_weight_l0_flag = 1;
            for (int c = 0; c < 2; c++) {
                si->chroma_weight_l0[i][c] = (int16_t)br_se(br);
                si->chroma_offset_l0[i][c] = (int16_t)br_se(br);
            }
        }
    }
}

static int parse_h264_slice_header(const uint8_t *slice, int size, int nal_type,
                                   const struct H264Params *params,
                                   struct H264SliceInfo *si) {
    struct BitReader br;
    int pic_parameter_set_id;
    int slice_type_mod;
    if (size < 2)
        return 0;
    br_init(&br, slice + 1, size - 1);
    si->first_mb = (int)br_ue(&br);
    si->slice_type = (int)br_ue(&br);
    slice_type_mod = si->slice_type % 5;
    pic_parameter_set_id = (int)br_ue(&br);
    if (pic_parameter_set_id != 0)
        return 0;
    if (params->separate_colour_plane_flag)
        br_bits(&br, 2);              /* colour_plane_id */
    si->frame_num = (int)br_bits(&br, params->log2_max_frame_num_minus4 + 4);
    if (!params->frame_mbs_only_flag) {
        int field_pic_flag = (int)br_bits(&br, 1);
        if (field_pic_flag)
            return 0;
    }
    if (nal_type == 5) {
        br_ue(&br);                   /* idr_pic_id */
    }
    if (params->pic_order_cnt_type == 0) {
        si->poc_lsb = (int)br_bits(&br, params->log2_max_pic_order_cnt_lsb_minus4 + 4);
        if (params->pic_order_present_flag)
            br_se(&br);               /* delta_pic_order_cnt_bottom */
    } else if (params->pic_order_cnt_type == 1 && !params->delta_pic_order_always_zero_flag) {
        br_se(&br);                   /* delta_pic_order_cnt[0] */
        if (params->pic_order_present_flag)
            br_se(&br);               /* delta_pic_order_cnt[1] */
    }
    if (params->redundant_pic_cnt_present_flag)
        br_ue(&br);                   /* redundant_pic_cnt */
    si->num_ref_idx_l0_active_minus1 = params->num_ref_idx_l0_active_minus1;
    si->num_ref_idx_l1_active_minus1 = params->num_ref_idx_l1_active_minus1;
    if (slice_type_mod == 1)
        si->direct_spatial_mv_pred_flag = (int)br_bits(&br, 1);
    if (slice_type_mod == 0 || slice_type_mod == 1 || slice_type_mod == 3) {
        int num_ref_idx_active_override_flag = (int)br_bits(&br, 1);
        if (num_ref_idx_active_override_flag) {
            si->num_ref_idx_l0_active_minus1 = (int)br_ue(&br);
            if (slice_type_mod == 1)
                si->num_ref_idx_l1_active_minus1 = (int)br_ue(&br);
        }
    }
    if (!skip_h264_ref_pic_list_modification(&br, slice_type_mod))
        return 0;
    if ((params->weighted_pred_flag && (slice_type_mod == 0 || slice_type_mod == 3)) ||
        (params->weighted_bipred_idc == 1 && slice_type_mod == 1))
        parse_h264_pred_weight_table(&br, params, si);
    else
        init_h264_weight_defaults(si);
    skip_h264_dec_ref_pic_marking(&br, nal_type, si->nal_ref_idc);
    if (params->entropy_coding_mode_flag && slice_type_mod != 2 && slice_type_mod != 4)
        si->cabac_init_idc = (int)br_ue(&br);
    si->slice_qp_delta = br_se(&br);
    if (params->deblocking_filter_control_present_flag) {
        si->disable_deblocking_filter_idc = (int)br_ue(&br);
        if (si->disable_deblocking_filter_idc != 1) {
            si->slice_alpha_c0_offset_div2 = br_se(&br);
            si->slice_beta_offset_div2 = br_se(&br);
        }
    }
    si->bit_offset = 8 + br.bits_read;
    return 1;
}

static int collect_h264_slices(const uint8_t *data, int size, const struct H264Params *params,
                               struct H264SliceInfo *slices, int max_slices) {
    int prefix = 0;
    int count = 0;
    int start = find_start_code(data, size, 0, &prefix);
    while (start >= 0) {
        int nal = start + prefix;
        int next_prefix = 0;
        int next = find_start_code(data, size, nal + 1, &next_prefix);
        int end = next >= 0 ? next : size;
        if (nal < end) {
            int type = data[nal] & 0x1f;
            if (type == 1 || type == 5) {
                if (count >= max_slices)
                    return -1;
                memset(&slices[count], 0, sizeof(slices[count]));
                slices[count].offset = nal;
                slices[count].size = end - nal;
                slices[count].nal_type = type;
                slices[count].nal_ref_idc = (data[nal] >> 5) & 3;
                if (!parse_h264_slice_header(data + nal, end - nal, type, params, &slices[count]))
                    return -1;
                count++;
            }
        }
        start = next;
        prefix = next_prefix;
    }
    return count;
}

static int ensure_plane(LibVADecoder *dec, int plane, size_t size) {
    uint8_t *p;
    if (dec->plane_caps[plane] >= size)
        return 1;
    p = (uint8_t *)realloc(dec->planes[plane], size);
    if (!p) {
        snprintf(dec->last_error, sizeof(dec->last_error), "failed to allocate decoded plane %d", plane);
        return 0;
    }
    dec->planes[plane] = p;
    dec->plane_caps[plane] = size;
    return 1;
}

static LibVADecodeStatus map_output(LibVADecoder *dec, VASurfaceID surface,
                                    LibVADecodedFrame *frame) {
    VAImage image;
    VAStatus status;
    void *data = NULL;
    long long t0, t1, t2;
    int w = dec->width;
    int h = dec->height;

    t0 = usec_now();
    status = vaDeriveImage(dec->display, surface, &image);
    if (status != VA_STATUS_SUCCESS)
        return set_error(dec, status, "vaDeriveImage");
    status = vaMapBuffer(dec->display, image.buf, &data);
    t1 = usec_now();
    if (status != VA_STATUS_SUCCESS) {
        vaDestroyImage(dec->display, image.image_id);
        return set_error(dec, status, "vaMapBuffer(output)");
    }

    memset(frame, 0, sizeof(*frame));
    frame->width = w;
    frame->height = h;
    frame->depth = dec->output_444 ? 24 : 24;
    if (image.format.fourcc == VA_FOURCC_NV12) {
        size_t ysize = (size_t)w * h;
        size_t uvsize = (size_t)w * ((h + 1) / 2);
        if (!ensure_plane(dec, 0, ysize) || !ensure_plane(dec, 1, uvsize)) {
            vaUnmapBuffer(dec->display, image.buf);
            vaDestroyImage(dec->display, image.image_id);
            return LIBVA_DEC_ERROR;
        }
        for (int row = 0; row < h; row++)
            memcpy(dec->planes[0] + (size_t)row * w,
                   (uint8_t *)data + image.offsets[0] + (size_t)row * image.pitches[0], w);
        for (int row = 0; row < (h + 1) / 2; row++)
            memcpy(dec->planes[1] + (size_t)row * w,
                   (uint8_t *)data + image.offsets[1] + (size_t)row * image.pitches[1], w);
        frame->planes[0] = dec->planes[0];
        frame->planes[1] = dec->planes[1];
        frame->strides[0] = w;
        frame->strides[1] = w;
        frame->sizes[0] = (int)ysize;
        frame->sizes[1] = (int)uvsize;
        frame->nplanes = 2;
        frame->bytes_per_pixel = 1;
        frame->format = LIBVA_DEC_FMT_NV12;
    } else if (image.format.fourcc == VA_FOURCC_444P) {
        size_t psize = (size_t)w * h;
        for (int p = 0; p < 3; p++) {
            if (!ensure_plane(dec, p, psize)) {
                vaUnmapBuffer(dec->display, image.buf);
                vaDestroyImage(dec->display, image.image_id);
                return LIBVA_DEC_ERROR;
            }
            for (int row = 0; row < h; row++)
                memcpy(dec->planes[p] + (size_t)row * w,
                       (uint8_t *)data + image.offsets[p] + (size_t)row * image.pitches[p], w);
            frame->planes[p] = dec->planes[p];
            frame->strides[p] = w;
            frame->sizes[p] = (int)psize;
        }
        frame->nplanes = 3;
        frame->bytes_per_pixel = 1;
        frame->format = LIBVA_DEC_FMT_YUV444P;
    } else if (image.format.fourcc == VA_FOURCC_XYUV || image.format.fourcc == VA_FOURCC_AYUV) {
        int stride = w * 4;
        size_t psize = (size_t)stride * h;
        if (!ensure_plane(dec, 0, psize)) {
            vaUnmapBuffer(dec->display, image.buf);
            vaDestroyImage(dec->display, image.image_id);
            return LIBVA_DEC_ERROR;
        }
        for (int row = 0; row < h; row++)
            memcpy(dec->planes[0] + (size_t)row * stride,
                   (uint8_t *)data + image.offsets[0] + (size_t)row * image.pitches[0], stride);
        frame->planes[0] = dec->planes[0];
        frame->strides[0] = stride;
        frame->sizes[0] = (int)psize;
        frame->nplanes = 1;
        frame->depth = 32;
        frame->bytes_per_pixel = 4;
        frame->format = image.format.fourcc == VA_FOURCC_XYUV ? LIBVA_DEC_FMT_XYUV : LIBVA_DEC_FMT_AYUV;
    } else {
        snprintf(dec->last_error, sizeof(dec->last_error), "unsupported VA output fourcc %s (%#x)",
                 fourcc_name(image.format.fourcc), image.format.fourcc);
        vaUnmapBuffer(dec->display, image.buf);
        vaDestroyImage(dec->display, image.image_id);
        return LIBVA_DEC_UNSUPPORTED;
    }
    vaUnmapBuffer(dec->display, image.buf);
    vaDestroyImage(dec->display, image.image_id);
    t2 = usec_now();
    frame->us_map = (int)(t1 - t0);
    frame->us_copy = (int)(t2 - t1);
    return LIBVA_DEC_OK;
}

static LibVADecodeStatus h264_decoder_decode(LibVADecoder *dec,
                                             const uint8_t *data, int data_len,
                                             LibVADecodedFrame *frame) {
    VABufferID buffers[130];
    int nbuf = 0;
    struct H264SliceInfo slices[64];
    int nslices = 0;
    struct H264SliceInfo *first;
    int is_idr;
    int surface_index;
    VASurfaceID surface;
    VAStatus status;
    LibVADecodeStatus dstatus;
    VAPictureParameterBufferH264 pic;
    VAIQMatrixBufferH264 iq;
    VASliceParameterBufferH264 slice;
    struct H264Params params;
    long long t0, t1, t2;

    if (!dec->h264_params)
        return set_message(dec, LIBVA_DEC_ERROR, "missing H.264 decoder parameters");
    params = *dec->h264_params;
    parse_h264_params(data, data_len, &params);
    nslices = collect_h264_slices(data, data_len, &params, slices,
                                  (int)(sizeof(slices) / sizeof(slices[0])));
    if (nslices <= 0)
        return set_message(dec, nslices < 0 ? LIBVA_DEC_UNSUPPORTED : LIBVA_DEC_ERROR,
                           nslices < 0 ? "unsupported H.264 slice header" : "no H.264 slice NAL found");
    *dec->h264_params = params;
    first = &slices[0];

    for (int i = 0; i < (int)(sizeof(buffers) / sizeof(buffers[0])); i++)
        buffers[i] = VA_INVALID_ID;
    is_idr = first->nal_type == 5;
    surface_index = dec->surface_index++ & 3;
    surface = dec->surfaces[surface_index];

    memset(&pic, 0, sizeof(pic));
    pic.CurrPic.picture_id = surface;
    pic.CurrPic.frame_idx = (uint32_t)first->frame_num;
    pic.CurrPic.flags = VA_PICTURE_H264_SHORT_TERM_REFERENCE;
    pic.CurrPic.TopFieldOrderCnt = first->poc_lsb;
    pic.CurrPic.BottomFieldOrderCnt = first->poc_lsb;
    for (int i = 0; i < 16; i++)
        fill_invalid_picture(&pic.ReferenceFrames[i]);
    if (!is_idr && dec->have_reference) {
        pic.ReferenceFrames[0].picture_id = dec->surfaces[dec->ref_surface_index];
        pic.ReferenceFrames[0].frame_idx = (uint32_t)dec->ref_frame_num;
        pic.ReferenceFrames[0].flags = VA_PICTURE_H264_SHORT_TERM_REFERENCE;
        pic.ReferenceFrames[0].TopFieldOrderCnt = dec->ref_poc_lsb;
        pic.ReferenceFrames[0].BottomFieldOrderCnt = dec->ref_poc_lsb;
    }
    pic.picture_width_in_mbs_minus1 = (uint16_t)(params.valid_sps ?
                                                params.width_mbs_minus1 :
                                                (roundup(dec->width, 16) / 16 - 1));
    pic.picture_height_in_mbs_minus1 = (uint16_t)(params.valid_sps ?
                                                 params.height_mbs_minus1 :
                                                 (roundup(dec->height, 16) / 16 - 1));
    pic.bit_depth_luma_minus8 = 0;
    pic.bit_depth_chroma_minus8 = 0;
    pic.num_ref_frames = (uint8_t)params.max_num_ref_frames;
    pic.seq_fields.bits.chroma_format_idc = (uint32_t)params.chroma_format_idc;
    pic.seq_fields.bits.residual_colour_transform_flag = (uint32_t)params.separate_colour_plane_flag;
    pic.seq_fields.bits.gaps_in_frame_num_value_allowed_flag = (uint32_t)params.gaps_in_frame_num_value_allowed_flag;
    pic.seq_fields.bits.frame_mbs_only_flag = (uint32_t)params.frame_mbs_only_flag;
    pic.seq_fields.bits.mb_adaptive_frame_field_flag = (uint32_t)params.mb_adaptive_frame_field_flag;
    pic.seq_fields.bits.direct_8x8_inference_flag = (uint32_t)params.direct_8x8_inference_flag;
    pic.seq_fields.bits.log2_max_frame_num_minus4 = (uint32_t)params.log2_max_frame_num_minus4;
    pic.seq_fields.bits.pic_order_cnt_type = (uint32_t)params.pic_order_cnt_type;
    pic.seq_fields.bits.log2_max_pic_order_cnt_lsb_minus4 = (uint32_t)params.log2_max_pic_order_cnt_lsb_minus4;
    pic.seq_fields.bits.delta_pic_order_always_zero_flag = (uint32_t)params.delta_pic_order_always_zero_flag;
    pic.pic_init_qp_minus26 = (int8_t)params.pic_init_qp_minus26;
    pic.pic_init_qs_minus26 = (int8_t)params.pic_init_qs_minus26;
    pic.chroma_qp_index_offset = (int8_t)params.chroma_qp_index_offset;
    pic.second_chroma_qp_index_offset = (int8_t)params.second_chroma_qp_index_offset;
    pic.pic_fields.bits.entropy_coding_mode_flag = (uint32_t)params.entropy_coding_mode_flag;
    pic.pic_fields.bits.weighted_pred_flag = (uint32_t)params.weighted_pred_flag;
    pic.pic_fields.bits.weighted_bipred_idc = (uint32_t)params.weighted_bipred_idc;
    pic.pic_fields.bits.transform_8x8_mode_flag = (uint32_t)params.transform_8x8_mode_flag;
    pic.pic_fields.bits.pic_order_present_flag = (uint32_t)params.pic_order_present_flag;
    pic.pic_fields.bits.deblocking_filter_control_present_flag =
        (uint32_t)params.deblocking_filter_control_present_flag;
    pic.pic_fields.bits.redundant_pic_cnt_present_flag = (uint32_t)params.redundant_pic_cnt_present_flag;
    pic.pic_fields.bits.constrained_intra_pred_flag = (uint32_t)params.constrained_intra_pred_flag;
    pic.pic_fields.bits.reference_pic_flag = 1;
    pic.frame_num = (uint16_t)first->frame_num;
    status = vaCreateBuffer(dec->display, dec->context, VAPictureParameterBufferType,
                            sizeof(pic), 1, &pic, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(dec, buffers, nbuf);
        return set_error(dec, status, "vaCreateBuffer(H264 picture)");
    }

    fill_h264_default_iq_matrix(&iq);
    status = vaCreateBuffer(dec->display, dec->context, VAIQMatrixBufferType,
                            sizeof(iq), 1, &iq, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(dec, buffers, nbuf);
        return set_error(dec, status, "vaCreateBuffer(H264 iq)");
    }

    for (int s = 0; s < nslices; s++) {
        struct H264SliceInfo *si = &slices[s];
        memset(&slice, 0, sizeof(slice));
        slice.slice_data_size = (uint32_t)si->size;
        slice.slice_data_offset = 0;
        slice.slice_data_flag = VA_SLICE_DATA_FLAG_ALL;
        slice.slice_data_bit_offset = (uint16_t)si->bit_offset;
        slice.first_mb_in_slice = (uint16_t)si->first_mb;
        slice.slice_type = (uint8_t)(si->slice_type % 5);
        slice.direct_spatial_mv_pred_flag = (uint8_t)si->direct_spatial_mv_pred_flag;
        slice.num_ref_idx_l0_active_minus1 = (uint8_t)si->num_ref_idx_l0_active_minus1;
        slice.num_ref_idx_l1_active_minus1 = (uint8_t)si->num_ref_idx_l1_active_minus1;
        slice.cabac_init_idc = (uint8_t)si->cabac_init_idc;
        slice.slice_qp_delta = (int8_t)si->slice_qp_delta;
        slice.disable_deblocking_filter_idc = (uint8_t)si->disable_deblocking_filter_idc;
        slice.slice_alpha_c0_offset_div2 = (int8_t)si->slice_alpha_c0_offset_div2;
        slice.slice_beta_offset_div2 = (int8_t)si->slice_beta_offset_div2;
        slice.luma_log2_weight_denom = (uint8_t)si->luma_log2_weight_denom;
        slice.chroma_log2_weight_denom = (uint8_t)si->chroma_log2_weight_denom;
        slice.luma_weight_l0_flag = si->luma_weight_l0_flag;
        slice.chroma_weight_l0_flag = si->chroma_weight_l0_flag;
        memcpy(slice.luma_weight_l0, si->luma_weight_l0, sizeof(slice.luma_weight_l0));
        memcpy(slice.luma_offset_l0, si->luma_offset_l0, sizeof(slice.luma_offset_l0));
        memcpy(slice.chroma_weight_l0, si->chroma_weight_l0, sizeof(slice.chroma_weight_l0));
        memcpy(slice.chroma_offset_l0, si->chroma_offset_l0, sizeof(slice.chroma_offset_l0));
        for (int i = 0; i < 32; i++) {
            fill_invalid_picture(&slice.RefPicList0[i]);
            fill_invalid_picture(&slice.RefPicList1[i]);
        }
        if (!is_idr && dec->have_reference) {
            slice.RefPicList0[0].picture_id = dec->surfaces[dec->ref_surface_index];
            slice.RefPicList0[0].frame_idx = (uint32_t)dec->ref_frame_num;
            slice.RefPicList0[0].flags = VA_PICTURE_H264_SHORT_TERM_REFERENCE;
            slice.RefPicList0[0].TopFieldOrderCnt = dec->ref_poc_lsb;
            slice.RefPicList0[0].BottomFieldOrderCnt = dec->ref_poc_lsb;
        }
        status = vaCreateBuffer(dec->display, dec->context, VASliceParameterBufferType,
                                sizeof(slice), 1, &slice, &buffers[nbuf++]);
        if (status != VA_STATUS_SUCCESS) {
            destroy_buffers(dec, buffers, nbuf);
            return set_error(dec, status, "vaCreateBuffer(H264 slice)");
        }
        status = vaCreateBuffer(dec->display, dec->context, VASliceDataBufferType,
                                (unsigned int)si->size, 1, (void *)(data + si->offset), &buffers[nbuf++]);
        if (status != VA_STATUS_SUCCESS) {
            destroy_buffers(dec, buffers, nbuf);
            return set_error(dec, status, "vaCreateBuffer(H264 data)");
        }
    }

    t0 = usec_now();
    status = vaBeginPicture(dec->display, dec->context, surface);
    if (status == VA_STATUS_SUCCESS)
        status = vaRenderPicture(dec->display, dec->context, buffers, nbuf);
    if (status == VA_STATUS_SUCCESS)
        status = vaEndPicture(dec->display, dec->context);
    t1 = usec_now();
    destroy_buffers(dec, buffers, nbuf);
    if (status != VA_STATUS_SUCCESS)
        return set_error(dec, status, "VA H264 decode submit");

    status = vaSyncSurface(dec->display, surface);
    t2 = usec_now();
    if (status != VA_STATUS_SUCCESS)
        return set_error(dec, status, "vaSyncSurface");

    dstatus = map_output(dec, surface, frame);
    if (dstatus != LIBVA_DEC_OK)
        return dstatus;
    frame->us_submit = (int)(t1 - t0);
    frame->us_sync = (int)(t2 - t1);
    dec->have_reference = 1;
    dec->ref_surface_index = surface_index;
    dec->ref_frame_num = first->frame_num;
    dec->ref_poc_lsb = first->poc_lsb;
    dec->frames++;
    return LIBVA_DEC_OK;
}

LibVADecodeStatus libva_decoder_decode(LibVADecoder *dec,
                                       const uint8_t *data, int data_len,
                                       LibVADecodedFrame *frame) {
    if (!dec || !data || data_len <= 0 || !frame)
        return LIBVA_DEC_ERROR;
    if (dec->codec == LIBVA_CODEC_H264)
        return h264_decoder_decode(dec, data, data_len, frame);
    return set_message(dec, LIBVA_DEC_UNSUPPORTED, "VP8/VP9 VA decode parser is not implemented yet");
}

int libva_decoder_get_width(LibVADecoder *dec) {
    return dec ? dec->width : 0;
}

int libva_decoder_get_height(LibVADecoder *dec) {
    return dec ? dec->height : 0;
}

int libva_decoder_get_last_status(LibVADecoder *dec) {
    return dec ? dec->last_status : 0;
}

const char* libva_decoder_get_last_error(LibVADecoder *dec) {
    return dec ? dec->last_error : "no decoder";
}
