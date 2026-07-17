/* This file is part of Xpra.
 * Copyright (C) 2026 Netflix, Inc.
 * Xpra is released under the terms of the GNU GPL v2, or, at your option, any
 * later version. See the file COPYING for details.
 * ABOUTME: libva decoder - C implementation.
 * ABOUTME: Minimal VA-API H.264 decoder with NV12/YUV444 output extraction. */

#include "va_decode.h"
#include "va_common.h"
#include "va_vpx_tables.h"

#include <va/va.h>
#include <va/va_dec_vp8.h>
#include <va/va_dec_vp9.h>

#ifdef _WIN32
#include <windows.h>
#include <io.h>     /* close() */
#else
#include <dirent.h>
#include <unistd.h>
#endif

#include <stdlib.h>
#include <string.h>
#include <time.h>

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
struct VP8State;

/* H.264 decoded picture buffer: up to 16 reference frames (spec DPB
 * ceiling), progressive only (field coding is rejected at parse). */
#define H264_DPB_SIZE 16
/* surface pool: every DPB slot + the picture being decoded */
#define H264_NUM_SURFACES (H264_DPB_SIZE + 1)

struct H264DPBEntry {
    VASurfaceID surface;
    int surface_index;          /* index into LibVADecoder.surfaces */
    int frame_num;              /* FrameNum as coded */
    int top_foc;
    int bottom_foc;
    int is_long_term;
    int long_term_frame_idx;
    int in_use;
};

struct LibVADecoder {
    int             fd;
    VADisplay       display;
    VAConfigID      config;
    VAContextID     context;
    /* h264 uses the whole pool; vp8/vp9 use only the first 4 entries
     * (num_surfaces is 4 for them - their `& 3` rotation is untouched) */
    VASurfaceID     surfaces[H264_NUM_SURFACES];
    int             num_surfaces;
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
    struct H264DPBEntry dpb[H264_DPB_SIZE];
    /* picture order count state (spec 8.2.1) */
    int             poc_prev_lsb;
    int             poc_prev_msb;
    int             poc_prev_frame_num;
    int             poc_prev_frame_num_offset;
    struct H264Params *h264_params;
    struct VP8State *vp8_state;
    int             vpx_last_surface;
    int             vpx_golden_surface;
    int             vpx_alt_surface;
    VASurfaceID     vp9_refs[8];
    int             full_range;     /* colour range from the last parsed bitstream headers */
    int             vp9_color_range;
    int             vp9_bit_depth;
    int             vp9_subsampling_x;
    int             vp9_subsampling_y;
    int             vp9_loop_filter_ref_deltas[4];
    int             vp9_loop_filter_mode_deltas[2];
    int             vp9_segmentation_abs_or_delta_update;
    int             vp9_feature_enabled[8][4];
    int             vp9_feature_data[8][4];
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
    int video_full_range_flag;
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
    int delta_poc_bottom;             /* delta_pic_order_cnt_bottom (poc type 0) */
    /* dec_ref_pic_marking() */
    int idr_long_term_reference_flag;
    int adaptive_ref_pic_marking;
    int n_mmco;
    struct { int op; int arg1; int arg2; } mmco[H264_DPB_SIZE + 2];
    /* ref_pic_list_modification(), list 0 */
    int n_ref_mod_l0;
    struct { int idc; int val; } ref_mod_l0[32];
    int bit_offset;
};

struct VP8State {
    uint8_t token_probs[4][8][3][11];
    uint8_t mv_probs[2][19];
    uint8_t y_mode_probs[4];
    uint8_t uv_mode_probs[3];
    int segmentation_enabled;
    int update_mb_segmentation_map;
    int update_segment_feature_data;
    int segment_feature_mode;
    int quantizer_update_value[4];
    int lf_update_value[4];
    uint8_t segment_prob[3];
    int loop_filter_adj_enable;
    int mode_ref_lf_delta_update;
    int ref_frame_delta[4];
    int mb_mode_delta[4];
};

struct VP8BoolReader {
    const uint8_t *data;
    int size;
    int pos;
    unsigned int range;
    unsigned int value;
    int count;
};

struct VP8FrameInfo {
    int key_frame;
    int version;
    int show_frame;
    int first_part_size;
    int data_chunk_size;
    int width;
    int height;
    int filter_type;
    int loop_filter_level;
    int sharpness_level;
    int log2_partitions;
    int y_ac_qi;
    int y_dc_delta;
    int y2_dc_delta;
    int y2_ac_delta;
    int uv_dc_delta;
    int uv_ac_delta;
    int refresh_entropy_probs;
    int refresh_last;
    int refresh_golden_frame;
    int refresh_alternate_frame;
    int copy_buffer_to_golden;
    int copy_buffer_to_alternate;
    int sign_bias_golden;
    int sign_bias_alternate;
    int mb_no_coeff_skip;
    int prob_skip_false;
    int prob_intra;
    int prob_last;
    int prob_gf;
    int header_bits;
    uint32_t partition_size[8];
    struct VP8State probs;
    struct VP8BoolReader bool_state;
};

struct VP9BitReader {
    const uint8_t *data;
    int size;
    int bit_pos;
};

struct VP9FrameInfo {
    int profile;
    int bit_depth;
    int color_range;
    int subsampling_x;
    int subsampling_y;
    int frame_type;
    int show_frame;
    int error_resilient_mode;
    int intra_only;
    int reset_frame_context;
    int refresh_frame_flags;
    int ref_frame_idx[3];
    int ref_frame_sign_bias[4];
    int allow_high_precision_mv;
    int interpolation_filter;
    int refresh_frame_context;
    int frame_parallel_decoding_mode;
    int frame_context_idx;
    int frame_width;
    int frame_height;
    int render_width;
    int render_height;
    int base_q_idx;
    int delta_q_y_dc;
    int delta_q_uv_dc;
    int delta_q_uv_ac;
    int lossless;
    int loop_filter_level;
    int loop_filter_sharpness;
    int loop_filter_delta_enabled;
    int loop_filter_ref_deltas[4];
    int loop_filter_mode_deltas[2];
    int segmentation_enabled;
    int segmentation_update_map;
    int segmentation_temporal_update;
    uint8_t segmentation_tree_probs[7];
    uint8_t segmentation_pred_probs[3];
    int segmentation_abs_or_delta_update;
    int feature_enabled[8][4];
    int feature_data[8][4];
    int tile_cols_log2;
    int tile_rows_log2;
    int uncompressed_header_bytes;
    int first_partition_size;
};

static void init_vp8_state(struct VP8State *state);
static void init_vp9_state(LibVADecoder *dec);

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
        libva_x11_close(display);
        if (fd >= 0)
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
    libva_x11_close(display);
    if (fd >= 0)
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

#ifdef _WIN32
LibVADecodeStatus libva_decode_startup(void) {
    g_error[0] = 0;
    if (try_device(""))
        return LIBVA_DEC_OK;
    if (!g_error[0])
        snprintf(g_error, sizeof(g_error), "no VA-API adapter found");
    return LIBVA_DEC_NOT_AVAILABLE;
}
#else
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
    /* no render node worked: try an X11 VA display (VDPAU-backed VA
     * drivers have no DRM path at all) */
    if (try_device("x11"))
        return LIBVA_DEC_OK;
    if (!g_error[0])
        snprintf(g_error, sizeof(g_error), "no VA-API render node found");
    return LIBVA_DEC_NOT_AVAILABLE;
}
#endif

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
    if (codec == LIBVA_CODEC_VP8 && strcmp(colorspace, "YUV420P") == 0)
        return g_vp8_420_supported;
    if (codec == LIBVA_CODEC_VP9) {
        if (strcmp(colorspace, "YUV420P") == 0)
            return g_vp9_420_supported;
        if (strcmp(colorspace, "YUV444P") == 0)
            return g_vp9_444_supported;
    }
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
    dec->vp8_state = (struct VP8State *)calloc(1, sizeof(*dec->vp8_state));
    if (!dec->vp8_state) {
        free(dec->h264_params);
        free(dec);
        return LIBVA_DEC_ERROR;
    }
    init_vp8_state(dec->vp8_state);
    dec->fd = -1;
    dec->config = VA_INVALID_ID;
    dec->context = VA_INVALID_ID;
    dec->num_surfaces = codec == LIBVA_CODEC_H264 ? H264_NUM_SURFACES : 4;
    for (int i = 0; i < H264_NUM_SURFACES; i++)
        dec->surfaces[i] = VA_INVALID_SURFACE;
    for (int i = 0; i < H264_DPB_SIZE; i++)
        dec->dpb[i].surface = VA_INVALID_SURFACE;
    for (int i = 0; i < 8; i++)
        dec->vp9_refs[i] = VA_INVALID_SURFACE;
    dec->vpx_last_surface = -1;
    dec->vpx_golden_surface = -1;
    dec->vpx_alt_surface = -1;
    init_vp9_state(dec);
    dec->width = width;
    dec->height = height;
    dec->surface_width = roundup(width, 16);
    dec->surface_height = roundup(height, 16);
    dec->codec = codec;
    dec->rt_format = VA_RT_FORMAT_YUV420;
    dec->profile = g_h264_420_profile;
    if (codec == LIBVA_CODEC_VP8) {
        dec->profile = VAProfileVP8Version0_3;
    } else if (codec == LIBVA_CODEC_VP9) {
        dec->profile = strcmp(colorspace, "YUV444P") == 0 ? VAProfileVP9Profile1 : VAProfileVP9Profile0;
    } else if (strcmp(colorspace, "YUV444P") == 0) {
        dec->rt_format = VA_RT_FORMAT_YUV444;
        dec->profile = g_h264_444_profile;
        dec->output_444 = 1;
    }
    if (codec == LIBVA_CODEC_VP9 && strcmp(colorspace, "YUV444P") == 0) {
        dec->rt_format = VA_RT_FORMAT_YUV444;
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

    {
        VASurfaceAttrib qattrs[32];
        unsigned int nq = 32;
        VAStatus qst = vaQuerySurfaceAttributes(dec->display, dec->config, qattrs, &nq);
        libva_log("VP9 dbg: vaQuerySurfaceAttributes status=%d nattrs=%u", (int)qst, nq);
        for (unsigned int i = 0; i < nq && qst == VA_STATUS_SUCCESS; i++) {
            if (qattrs[i].type == VASurfaceAttribPixelFormat) {
                unsigned int fourcc = (unsigned int)qattrs[i].value.value.i;
                libva_log("VP9 dbg:   supported pixel format: %c%c%c%c (0x%08x)",
                          fourcc & 0xff, (fourcc >> 8) & 0xff,
                          (fourcc >> 16) & 0xff, (fourcc >> 24) & 0xff, fourcc);
            }
        }
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
                              dec->surfaces, (unsigned int)dec->num_surfaces,
                              surface_attrs, 2);
    if (status != VA_STATUS_SUCCESS) {
        set_error(dec, status, "vaCreateSurfaces");
        libva_decoder_destroy(dec);
        return LIBVA_DEC_ERROR;
    }

    status = vaCreateContext(dec->display, dec->config,
                             dec->surface_width, dec->surface_height,
                             VA_PROGRESSIVE, dec->surfaces, dec->num_surfaces,
                             &dec->context);
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
        for (int i = 0; i < H264_NUM_SURFACES; i++) {
            if (dec->surfaces[i] != VA_INVALID_SURFACE)
                vaDestroySurfaces(dec->display, &dec->surfaces[i], 1);
        }
        if (dec->config != VA_INVALID_ID)
            vaDestroyConfig(dec->display, dec->config);
        vaTerminate(dec->display);
        libva_x11_close(dec->display);
    }
    if (dec->fd >= 0)
        close(dec->fd);
    for (int i = 0; i < 3; i++)
        free(dec->planes[i]);
    free(dec->h264_params);
    free(dec->vp8_state);
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
    /* continue into the VUI to recover the colour range (video_full_range_flag);
     * br handles emulation-prevention bytes and returns 0 past the end of the RBSP: */
    if (br_bits(&br, 1)) {            /* frame_cropping_flag */
        br_ue(&br);                   /* frame_crop_left_offset */
        br_ue(&br);                   /* frame_crop_right_offset */
        br_ue(&br);                   /* frame_crop_top_offset */
        br_ue(&br);                   /* frame_crop_bottom_offset */
    }
    params->video_full_range_flag = 0;    /* default (studio) when not signalled */
    if (br_bits(&br, 1)) {            /* vui_parameters_present_flag */
        if (br_bits(&br, 1)) {        /* aspect_ratio_info_present_flag */
            if ((int)br_bits(&br, 8) == 255) {  /* aspect_ratio_idc == Extended_SAR */
                br_bits(&br, 16);     /* sar_width */
                br_bits(&br, 16);     /* sar_height */
            }
        }
        if (br_bits(&br, 1))          /* overscan_info_present_flag */
            br_bits(&br, 1);          /* overscan_appropriate_flag */
        if (br_bits(&br, 1)) {        /* video_signal_type_present_flag */
            br_bits(&br, 3);          /* video_format */
            params->video_full_range_flag = (int)br_bits(&br, 1);
        }
    }
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

static int parse_h264_ref_pic_list_modification(struct BitReader *br, int slice_type_mod,
                                                struct H264SliceInfo *si) {
    si->n_ref_mod_l0 = 0;
    if (slice_type_mod == 2 || slice_type_mod == 4)
        return 1;                     /* I/SI slices carry no lists */
    if (br_bits(br, 1)) {             /* ref_pic_list_modification_flag_l0 */
        unsigned int idc;
        do {
            idc = br_ue(br);          /* modification_of_pic_nums_idc */
            if (idc == 3)
                break;
            if (idc > 2)
                return 0;             /* MVC ops (4/5) not supported */
            int val = (int)br_ue(br); /* abs_diff_pic_num_minus1 / long_term_pic_num */
            if (si->n_ref_mod_l0 < 32) {
                si->ref_mod_l0[si->n_ref_mod_l0].idc = (int)idc;
                si->ref_mod_l0[si->n_ref_mod_l0].val = val;
                si->n_ref_mod_l0++;
            }
        } while (br_bits_left(br) > 0);
    }
    /* B slices would carry an L1 modification loop here; B slices are
     * rejected at slice-header parse (this decoder is IPP-only) */
    return 1;
}

static int parse_h264_dec_ref_pic_marking(struct BitReader *br, int nal_type,
                                          struct H264SliceInfo *si) {
    si->idr_long_term_reference_flag = 0;
    si->adaptive_ref_pic_marking = 0;
    si->n_mmco = 0;
    if (!si->nal_ref_idc)
        return 1;
    if (nal_type == 5) {
        br_bits(br, 1);               /* no_output_of_prior_pics_flag */
        si->idr_long_term_reference_flag = (int)br_bits(br, 1);
        return 1;
    }
    si->adaptive_ref_pic_marking = (int)br_bits(br, 1);
    if (si->adaptive_ref_pic_marking) {
        unsigned int op;
        do {
            op = br_ue(br);           /* memory_management_control_operation */
            if (op == 0)
                break;
            if (op > 6)
                return 0;
            int arg1 = 0, arg2 = 0;
            if (op == 1 || op == 3)
                arg1 = (int)br_ue(br);    /* difference_of_pic_nums_minus1 */
            if (op == 2)
                arg1 = (int)br_ue(br);    /* long_term_pic_num */
            if (op == 3 || op == 6)
                arg2 = (int)br_ue(br);    /* long_term_frame_idx */
            if (op == 4)
                arg1 = (int)br_ue(br);    /* max_long_term_frame_idx_plus1 */
            if (si->n_mmco < (int)(sizeof(si->mmco) / sizeof(si->mmco[0]))) {
                si->mmco[si->n_mmco].op = (int)op;
                si->mmco[si->n_mmco].arg1 = arg1;
                si->mmco[si->n_mmco].arg2 = arg2;
                si->n_mmco++;
            }
        } while (br_bits_left(br) > 0);
    }
    return 1;
}

/* ------------------------------------------------------------------ */
/* H.264 decoded picture buffer (progressive frames only)              */
/* ------------------------------------------------------------------ */

static void h264_dpb_flush(LibVADecoder *dec) {
    for (int i = 0; i < H264_DPB_SIZE; i++) {
        dec->dpb[i].in_use = 0;
        dec->dpb[i].surface = VA_INVALID_SURFACE;
    }
}

/* PicNum for a frame (spec 8.2.4.1: FrameNumWrap, since for frames
 * PicNum == FrameNumWrap) relative to the current frame_num */
static int h264_pic_num(const struct H264DPBEntry *e, int cur_frame_num, int max_frame_num) {
    if (e->frame_num > cur_frame_num)
        return e->frame_num - max_frame_num;
    return e->frame_num;
}

/* spec 8.2.1: picture order count, types 0 and 2 (type 1 unsupported).
 * Progressive only. Returns 0 and fills *top_foc / *bottom_foc. */
static int h264_compute_poc(LibVADecoder *dec, const struct H264Params *params,
                            const struct H264SliceInfo *si, int is_idr,
                            int *top_foc, int *bottom_foc) {
    if (params->pic_order_cnt_type == 0) {
        int max_lsb = 1 << (params->log2_max_pic_order_cnt_lsb_minus4 + 4);
        int prev_lsb = is_idr ? 0 : dec->poc_prev_lsb;
        int prev_msb = is_idr ? 0 : dec->poc_prev_msb;
        int msb;
        if (si->poc_lsb < prev_lsb && (prev_lsb - si->poc_lsb) >= max_lsb / 2)
            msb = prev_msb + max_lsb;
        else if (si->poc_lsb > prev_lsb && (si->poc_lsb - prev_lsb) > max_lsb / 2)
            msb = prev_msb - max_lsb;
        else
            msb = prev_msb;
        *top_foc = msb + si->poc_lsb;
        *bottom_foc = *top_foc + si->delta_poc_bottom;
        if (si->nal_ref_idc) {        /* prev state tracks reference pictures */
            dec->poc_prev_lsb = si->poc_lsb;
            dec->poc_prev_msb = msb;
        }
        return 0;
    }
    if (params->pic_order_cnt_type == 2) {
        int max_frame_num = 1 << (params->log2_max_frame_num_minus4 + 4);
        int offset;
        if (is_idr)
            offset = 0;
        else if (dec->poc_prev_frame_num > si->frame_num)
            offset = dec->poc_prev_frame_num_offset + max_frame_num;
        else
            offset = dec->poc_prev_frame_num_offset;
        int poc = 2 * (offset + si->frame_num);
        if (!si->nal_ref_idc)
            poc -= 1;
        *top_foc = poc;
        *bottom_foc = poc;
        dec->poc_prev_frame_num = si->frame_num;
        dec->poc_prev_frame_num_offset = offset;
        return 0;
    }
    return -1;                        /* type 1: no real encoder emits it here */
}

/* pick a surface that is not referenced by the DPB (pool = DPB size + 1,
 * so at least one is always free) */
static int h264_pick_surface(LibVADecoder *dec) {
    for (int n = 0; n < dec->num_surfaces; n++) {
        int idx = (dec->surface_index + n) % dec->num_surfaces;
        int busy = 0;
        for (int i = 0; i < H264_DPB_SIZE; i++) {
            if (dec->dpb[i].in_use && dec->dpb[i].surface_index == idx) {
                busy = 1;
                break;
            }
        }
        if (!busy) {
            dec->surface_index = (idx + 1) % dec->num_surfaces;
            return idx;
        }
    }
    return -1;
}

/* spec 8.2.5.3: sliding-window marking - make room for one more
 * reference by unmarking the short-term entry with the smallest
 * FrameNumWrap */
static void h264_dpb_sliding_window(LibVADecoder *dec, const struct H264Params *params,
                                    int cur_frame_num) {
    int max_frame_num = 1 << (params->log2_max_frame_num_minus4 + 4);
    int num_ref = params->max_num_ref_frames > 0 ? params->max_num_ref_frames : 1;
    if (num_ref > H264_DPB_SIZE)
        num_ref = H264_DPB_SIZE;
    int used = 0;
    for (int i = 0; i < H264_DPB_SIZE; i++)
        if (dec->dpb[i].in_use)
            used++;
    while (used >= num_ref) {
        int victim = -1, victim_pn = 0;
        for (int i = 0; i < H264_DPB_SIZE; i++) {
            struct H264DPBEntry *e = &dec->dpb[i];
            if (!e->in_use || e->is_long_term)
                continue;
            int pn = h264_pic_num(e, cur_frame_num, max_frame_num);
            if (victim < 0 || pn < victim_pn) {
                victim = i;
                victim_pn = pn;
            }
        }
        if (victim < 0)
            break;                    /* only long-term refs left */
        dec->dpb[victim].in_use = 0;
        used--;
    }
}

/* spec 8.2.5.4: adaptive memory control (MMCO ops 1-6) */
static void h264_dpb_apply_mmco(LibVADecoder *dec, const struct H264Params *params,
                                const struct H264SliceInfo *si, int cur_frame_num,
                                int *cur_is_long_term, int *cur_lt_idx, int *had_mmco5) {
    int max_frame_num = 1 << (params->log2_max_frame_num_minus4 + 4);
    *had_mmco5 = 0;
    for (int m = 0; m < si->n_mmco; m++) {
        int op = si->mmco[m].op;
        if (op == 1) {                /* unmark short-term */
            int pic_num = cur_frame_num - (si->mmco[m].arg1 + 1);
            for (int i = 0; i < H264_DPB_SIZE; i++) {
                struct H264DPBEntry *e = &dec->dpb[i];
                if (e->in_use && !e->is_long_term &&
                    h264_pic_num(e, cur_frame_num, max_frame_num) == pic_num)
                    e->in_use = 0;
            }
        } else if (op == 2) {         /* unmark long-term by LongTermPicNum */
            for (int i = 0; i < H264_DPB_SIZE; i++) {
                struct H264DPBEntry *e = &dec->dpb[i];
                if (e->in_use && e->is_long_term &&
                    e->long_term_frame_idx == si->mmco[m].arg1)
                    e->in_use = 0;
            }
        } else if (op == 3) {         /* short-term -> long-term */
            int pic_num = cur_frame_num - (si->mmco[m].arg1 + 1);
            for (int i = 0; i < H264_DPB_SIZE; i++) {
                struct H264DPBEntry *e = &dec->dpb[i];
                if (e->in_use && e->is_long_term &&
                    e->long_term_frame_idx == si->mmco[m].arg2)
                    e->in_use = 0;
            }
            for (int i = 0; i < H264_DPB_SIZE; i++) {
                struct H264DPBEntry *e = &dec->dpb[i];
                if (e->in_use && !e->is_long_term &&
                    h264_pic_num(e, cur_frame_num, max_frame_num) == pic_num) {
                    e->is_long_term = 1;
                    e->long_term_frame_idx = si->mmco[m].arg2;
                }
            }
        } else if (op == 4) {         /* max_long_term_frame_idx */
            int max_idx = si->mmco[m].arg1 - 1;
            for (int i = 0; i < H264_DPB_SIZE; i++) {
                struct H264DPBEntry *e = &dec->dpb[i];
                if (e->in_use && e->is_long_term && e->long_term_frame_idx > max_idx)
                    e->in_use = 0;
            }
        } else if (op == 5) {         /* unmark everything, reset numbering */
            h264_dpb_flush(dec);
            *had_mmco5 = 1;
        } else if (op == 6) {         /* current picture becomes long-term */
            for (int i = 0; i < H264_DPB_SIZE; i++) {
                struct H264DPBEntry *e = &dec->dpb[i];
                if (e->in_use && e->is_long_term &&
                    e->long_term_frame_idx == si->mmco[m].arg2)
                    e->in_use = 0;
            }
            *cur_is_long_term = 1;
            *cur_lt_idx = si->mmco[m].arg2;
        }
    }
}

static void h264_dpb_insert(LibVADecoder *dec, int surface_index, VASurfaceID surface,
                            int frame_num, int top_foc, int bottom_foc,
                            int is_long_term, int lt_idx) {
    int slot = -1;
    for (int i = 0; i < H264_DPB_SIZE; i++) {
        if (!dec->dpb[i].in_use) {
            slot = i;
            break;
        }
    }
    if (slot < 0)                     /* cannot happen after window/MMCO */
        slot = 0;
    struct H264DPBEntry *e = &dec->dpb[slot];
    e->surface = surface;
    e->surface_index = surface_index;
    e->frame_num = frame_num;
    e->top_foc = top_foc;
    e->bottom_foc = bottom_foc;
    e->is_long_term = is_long_term;
    e->long_term_frame_idx = lt_idx;
    e->in_use = 1;
}

static void h264_fill_va_picture(VAPictureH264 *p, const struct H264DPBEntry *e) {
    p->picture_id = e->surface;
    if (e->is_long_term) {
        p->frame_idx = (uint32_t)e->long_term_frame_idx;
        p->flags = VA_PICTURE_H264_LONG_TERM_REFERENCE;
    } else {
        p->frame_idx = (uint32_t)e->frame_num;
        p->flags = VA_PICTURE_H264_SHORT_TERM_REFERENCE;
    }
    p->TopFieldOrderCnt = e->top_foc;
    p->BottomFieldOrderCnt = e->bottom_foc;
}

/* RefPicList0 (spec 8.2.4.2.1 default order + 8.2.4.3 modification).
 * Note the VDPAU-bridge driver ignores this list entirely (VDPAU
 * re-derives it from the slice headers); it is filled correctly for
 * VA drivers that do consume it.  Simplification vs spec: a picture
 * appears at most once in the produced list. */
static int h264_build_ref_list_l0(LibVADecoder *dec, const struct H264Params *params,
                                  const struct H264SliceInfo *si,
                                  struct H264DPBEntry **list, int max_out) {
    int max_frame_num = 1 << (params->log2_max_frame_num_minus4 + 4);
    int cur = si->frame_num;
    int n = 0;
    /* short-term references by descending PicNum */
    for (int i = 0; i < H264_DPB_SIZE && n < max_out; i++) {
        struct H264DPBEntry *e = &dec->dpb[i];
        if (!e->in_use || e->is_long_term)
            continue;
        int pn = h264_pic_num(e, cur, max_frame_num);
        int j = n;
        while (j > 0 && h264_pic_num(list[j - 1], cur, max_frame_num) < pn) {
            list[j] = list[j - 1];
            j--;
        }
        list[j] = e;
        n++;
    }
    /* then long-term references by ascending LongTermFrameIdx */
    int st_count = n;
    for (int i = 0; i < H264_DPB_SIZE && n < max_out; i++) {
        struct H264DPBEntry *e = &dec->dpb[i];
        if (!e->in_use || !e->is_long_term)
            continue;
        int j = n;
        while (j > st_count && list[j - 1]->long_term_frame_idx > e->long_term_frame_idx) {
            list[j] = list[j - 1];
            j--;
        }
        list[j] = e;
        n++;
    }
    if (si->n_ref_mod_l0 && n > 1) {
        int pred = cur;               /* picNumL0Pred = CurrPicNum */
        int ref_idx = 0;
        for (int m = 0; m < si->n_ref_mod_l0 && ref_idx < n; m++) {
            struct H264DPBEntry *target = NULL;
            if (si->ref_mod_l0[m].idc <= 1) {
                int abs_diff = si->ref_mod_l0[m].val + 1;
                int nowrap;
                if (si->ref_mod_l0[m].idc == 0) {
                    nowrap = pred - abs_diff;
                    if (nowrap < 0)
                        nowrap += max_frame_num;
                } else {
                    nowrap = pred + abs_diff;
                    if (nowrap >= max_frame_num)
                        nowrap -= max_frame_num;
                }
                pred = nowrap;
                int picnum = nowrap > cur ? nowrap - max_frame_num : nowrap;
                for (int i = 0; i < n; i++) {
                    if (!list[i]->is_long_term &&
                        h264_pic_num(list[i], cur, max_frame_num) == picnum) {
                        target = list[i];
                        break;
                    }
                }
            } else {                  /* idc == 2: long-term */
                for (int i = 0; i < n; i++) {
                    if (list[i]->is_long_term &&
                        list[i]->long_term_frame_idx == si->ref_mod_l0[m].val) {
                        target = list[i];
                        break;
                    }
                }
            }
            if (!target)
                continue;             /* unresolvable op in a broken stream */
            int from = 0;
            while (from < n && list[from] != target)
                from++;
            if (from >= n)
                continue;
            for (int i = from; i > ref_idx; i--)
                list[i] = list[i - 1];
            list[ref_idx] = target;
            ref_idx++;
        }
    }
    return n;
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
    if (slice_type_mod == 1)
        return 0;                     /* B slices: single-direction DPB only */
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
            si->delta_poc_bottom = br_se(&br);
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
    if (!parse_h264_ref_pic_list_modification(&br, slice_type_mod, si))
        return 0;
    if ((params->weighted_pred_flag && (slice_type_mod == 0 || slice_type_mod == 3)) ||
        (params->weighted_bipred_idc == 1 && slice_type_mod == 1))
        parse_h264_pred_weight_table(&br, params, si);
    else
        init_h264_weight_defaults(si);
    if (!parse_h264_dec_ref_pic_marking(&br, nal_type, si))
        return 0;
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
    if (status != VA_STATUS_SUCCESS) {
        /* Fall back to vaCreateImage + vaGetImage for drivers without
         * DeriveImage support (e.g. the VDPAU-backed VA driver, whose
         * video surfaces have no linear CPU view) - the same pattern
         * ffmpeg's hwcontext_vaapi uses.  The image covers the full
         * (aligned) surface; the per-row copies below crop naturally. */
        VAImageFormat fmt;
        memset(&fmt, 0, sizeof(fmt));
        fmt.fourcc = dec->output_444 ? VA_FOURCC_XYUV : VA_FOURCC_NV12;
        fmt.byte_order = VA_LSB_FIRST;
        fmt.bits_per_pixel = dec->output_444 ? 32 : 12;
        status = vaCreateImage(dec->display, &fmt,
                               dec->surface_width, dec->surface_height, &image);
        if (status != VA_STATUS_SUCCESS)
            return set_error(dec, status, "vaDeriveImage/vaCreateImage");
        status = vaGetImage(dec->display, surface, 0, 0,
                            (unsigned int)dec->surface_width,
                            (unsigned int)dec->surface_height, image.image_id);
        if (status != VA_STATUS_SUCCESS) {
            vaDestroyImage(dec->display, image.image_id);
            return set_error(dec, status, "vaGetImage");
        }
    }
    status = vaMapBuffer(dec->display, image.buf, &data);
    t1 = usec_now();
    if (status != VA_STATUS_SUCCESS) {
        vaDestroyImage(dec->display, image.image_id);
        return set_error(dec, status, "vaMapBuffer(output)");
    }

    memset(frame, 0, sizeof(*frame));
    frame->full_range = dec->full_range;
    frame->width = w;
    frame->height = h;
    frame->depth = dec->output_444 ? 24 : 24;
    if (image.format.fourcc == VA_FOURCC_NV12) {
        /* NV12 chroma rows hold 2 bytes per 2-pixel pair, so an odd
         * display width needs w+1 bytes per chroma row; the source
         * surface is coded-size aligned so the bytes always exist.
         * (Odd display sizes are normal: h264 codes the padded even
         * size and crops via the SPS.) */
        int cw = (w + 1) & ~1;
        size_t ysize = (size_t)w * h;
        size_t uvsize = (size_t)cw * ((h + 1) / 2);
        if (!ensure_plane(dec, 0, ysize) || !ensure_plane(dec, 1, uvsize)) {
            vaUnmapBuffer(dec->display, image.buf);
            vaDestroyImage(dec->display, image.image_id);
            return LIBVA_DEC_ERROR;
        }
        for (int row = 0; row < h; row++)
            memcpy(dec->planes[0] + (size_t)row * w,
                   (uint8_t *)data + image.offsets[0] + (size_t)row * image.pitches[0], w);
        for (int row = 0; row < (h + 1) / 2; row++)
            memcpy(dec->planes[1] + (size_t)row * cw,
                   (uint8_t *)data + image.offsets[1] + (size_t)row * image.pitches[1], cw);
        frame->planes[0] = dec->planes[0];
        frame->planes[1] = dec->planes[1];
        frame->strides[0] = w;
        frame->strides[1] = cw;
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

static void init_vp8_state(struct VP8State *state) {
    static const uint8_t nk_y[4] = {112, 86, 140, 37};
    static const uint8_t nk_uv[3] = {162, 101, 204};
    memset(state, 0, sizeof(*state));
    memcpy(state->token_probs, vp8_default_token_probs, sizeof(state->token_probs));
    memcpy(state->mv_probs, vp8_default_mv_probs, sizeof(state->mv_probs));
    memcpy(state->y_mode_probs, nk_y, sizeof(state->y_mode_probs));
    memcpy(state->uv_mode_probs, nk_uv, sizeof(state->uv_mode_probs));
}

static void vp8_bool_fill(struct VP8BoolReader *br) {
    int shift = 16 - br->count;
    while (shift >= 0 && br->pos < br->size) {
        br->value |= (unsigned int)br->data[br->pos++] << shift;
        br->count += 8;
        shift -= 8;
    }
    if (shift >= 0)
        br->count += 0x40000000;
}

static void vp8_bool_init(struct VP8BoolReader *br, const uint8_t *data, int size) {
    memset(br, 0, sizeof(*br));
    br->data = data;
    br->size = size;
    br->range = 255;
    br->count = -8;
    vp8_bool_fill(br);
}

static int vp8_norm_shift(unsigned int range) {
    int shift = 0;
    while (range < 128) {
        range <<= 1;
        shift++;
    }
    return shift;
}

static int vp8_bool_read(struct VP8BoolReader *br, int probability) {
    unsigned int split = 1 + (((br->range - 1) * (unsigned int)probability) >> 8);
    unsigned int bigsplit = split << 24;
    int bit = 0;
    int shift;
    if (br->count < 0)
        vp8_bool_fill(br);
    if (br->value >= bigsplit) {
        br->range -= split;
        br->value -= bigsplit;
        bit = 1;
    } else {
        br->range = split;
    }
    shift = vp8_norm_shift(br->range);
    br->range <<= shift;
    br->value <<= shift;
    br->count -= shift;
    return bit;
}

static int vp8_bool_bits(struct VP8BoolReader *br, int bits) {
    int v = 0;
    for (int i = bits - 1; i >= 0; i--)
        v |= vp8_bool_read(br, 128) << i;
    return v;
}

static int vp8_bool_sint(struct VP8BoolReader *br, int bits) {
    int v = vp8_bool_bits(br, bits);
    return vp8_bool_read(br, 128) ? -v : v;
}

static int vp8_bool_pos(const struct VP8BoolReader *br) {
    return br->pos * 8 - (8 + br->count);
}

static void vp8_bool_state(struct VP8BoolReader *br, VABoolCoderContextVPX *ctx) {
    if (br->count < 0)
        vp8_bool_fill(br);
    ctx->range = (uint8_t)br->range;
    ctx->value = (uint8_t)(br->value >> 24);
    ctx->count = (uint8_t)((8 + br->count) & 7);
}

static void vp8_parse_segmentation(struct VP8BoolReader *br, struct VP8State *state) {
    state->update_mb_segmentation_map = 0;
    state->update_segment_feature_data = 0;
    if (!vp8_bool_read(br, 128)) {
        state->segmentation_enabled = 0;
        return;
    }
    state->segmentation_enabled = 1;
    state->update_mb_segmentation_map = vp8_bool_read(br, 128);
    state->update_segment_feature_data = vp8_bool_read(br, 128);
    if (state->update_segment_feature_data) {
        state->segment_feature_mode = vp8_bool_read(br, 128);
        for (int i = 0; i < 4; i++)
            state->quantizer_update_value[i] = vp8_bool_read(br, 128) ? vp8_bool_sint(br, 7) : 0;
        for (int i = 0; i < 4; i++)
            state->lf_update_value[i] = vp8_bool_read(br, 128) ? vp8_bool_sint(br, 6) : 0;
    }
    if (state->update_mb_segmentation_map) {
        for (int i = 0; i < 3; i++)
            state->segment_prob[i] = vp8_bool_read(br, 128) ? (uint8_t)vp8_bool_bits(br, 8) : 255;
    }
}

static void vp8_parse_lf_adjust(struct VP8BoolReader *br, struct VP8State *state) {
    state->mode_ref_lf_delta_update = 0;
    state->loop_filter_adj_enable = vp8_bool_read(br, 128);
    if (!state->loop_filter_adj_enable)
        return;
    state->mode_ref_lf_delta_update = vp8_bool_read(br, 128);
    if (!state->mode_ref_lf_delta_update)
        return;
    for (int i = 0; i < 4; i++)
        if (vp8_bool_read(br, 128))
            state->ref_frame_delta[i] = vp8_bool_sint(br, 6);
    for (int i = 0; i < 4; i++)
        if (vp8_bool_read(br, 128))
            state->mb_mode_delta[i] = vp8_bool_sint(br, 6);
}

static void vp8_parse_quant(struct VP8BoolReader *br, struct VP8FrameInfo *info) {
    info->y_ac_qi = vp8_bool_bits(br, 7);
    info->y_dc_delta = vp8_bool_read(br, 128) ? vp8_bool_sint(br, 4) : 0;
    info->y2_dc_delta = vp8_bool_read(br, 128) ? vp8_bool_sint(br, 4) : 0;
    info->y2_ac_delta = vp8_bool_read(br, 128) ? vp8_bool_sint(br, 4) : 0;
    info->uv_dc_delta = vp8_bool_read(br, 128) ? vp8_bool_sint(br, 4) : 0;
    info->uv_ac_delta = vp8_bool_read(br, 128) ? vp8_bool_sint(br, 4) : 0;
}

static int parse_vp8_frame(LibVADecoder *dec, const uint8_t *data, int size,
                           struct VP8FrameInfo *info) {
    static const uint8_t kf_y[4] = {145, 156, 163, 128};
    static const uint8_t kf_uv[3] = {142, 114, 183};
    uint32_t tag;
    const uint8_t *part0;
    int part0_size;
    struct VP8BoolReader br;
    if (size < 3)
        return 0;
    memset(info, 0, sizeof(*info));
    tag = (uint32_t)data[0] | ((uint32_t)data[1] << 8) | ((uint32_t)data[2] << 16);
    info->key_frame = !(tag & 1);
    info->version = (tag >> 1) & 7;
    info->show_frame = (tag >> 4) & 1;
    info->first_part_size = (tag >> 5) & 0x7ffff;
    info->data_chunk_size = info->key_frame ? 10 : 3;
    if (info->data_chunk_size >= size || info->first_part_size <= 0)
        return 0;
    if (info->key_frame) {
        if (size < 10 || data[3] != 0x9d || data[4] != 0x01 || data[5] != 0x2a)
            return 0;
        info->width = (int)(data[6] | (data[7] << 8)) & 0x3fff;
        info->height = (int)(data[8] | (data[9] << 8)) & 0x3fff;
        init_vp8_state(dec->vp8_state);
    }
    info->probs = *dec->vp8_state;
    part0 = data + info->data_chunk_size;
    part0_size = info->first_part_size;
    if (info->data_chunk_size + part0_size > size)
        return 0;
    vp8_bool_init(&br, part0, part0_size);
    if (info->key_frame) {
        vp8_bool_bits(&br, 1);         /* color_space */
        vp8_bool_bits(&br, 1);         /* clamping_type */
    }
    vp8_parse_segmentation(&br, &info->probs);
    info->filter_type = vp8_bool_bits(&br, 1);
    info->loop_filter_level = vp8_bool_bits(&br, 6);
    info->sharpness_level = vp8_bool_bits(&br, 3);
    vp8_parse_lf_adjust(&br, &info->probs);
    info->log2_partitions = vp8_bool_bits(&br, 2);
    vp8_parse_quant(&br, info);
    if (info->key_frame) {
        info->refresh_entropy_probs = vp8_bool_read(&br, 128);
        info->refresh_last = 1;
        info->refresh_golden_frame = 1;
        info->refresh_alternate_frame = 1;
        memcpy(info->probs.y_mode_probs, kf_y, sizeof(kf_y));
        memcpy(info->probs.uv_mode_probs, kf_uv, sizeof(kf_uv));
    } else {
        info->refresh_golden_frame = vp8_bool_read(&br, 128);
        info->refresh_alternate_frame = vp8_bool_read(&br, 128);
        if (!info->refresh_golden_frame)
            info->copy_buffer_to_golden = vp8_bool_bits(&br, 2);
        if (!info->refresh_alternate_frame)
            info->copy_buffer_to_alternate = vp8_bool_bits(&br, 2);
        info->sign_bias_golden = vp8_bool_bits(&br, 1);
        info->sign_bias_alternate = vp8_bool_bits(&br, 1);
        info->refresh_entropy_probs = vp8_bool_read(&br, 128);
        info->refresh_last = vp8_bool_read(&br, 128);
    }
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 8; j++)
            for (int k = 0; k < 3; k++)
                for (int l = 0; l < 11; l++)
                    if (vp8_bool_read(&br, vp8_token_update_probs[i][j][k][l]))
                        info->probs.token_probs[i][j][k][l] = (uint8_t)vp8_bool_bits(&br, 8);
    info->mb_no_coeff_skip = vp8_bool_read(&br, 128);
    if (info->mb_no_coeff_skip)
        info->prob_skip_false = vp8_bool_bits(&br, 8);
    if (!info->key_frame) {
        info->prob_intra = vp8_bool_bits(&br, 8);
        info->prob_last = vp8_bool_bits(&br, 8);
        info->prob_gf = vp8_bool_bits(&br, 8);
        if (vp8_bool_read(&br, 128))
            for (int i = 0; i < 4; i++)
                info->probs.y_mode_probs[i] = (uint8_t)vp8_bool_bits(&br, 8);
        if (vp8_bool_read(&br, 128))
            for (int i = 0; i < 3; i++)
                info->probs.uv_mode_probs[i] = (uint8_t)vp8_bool_bits(&br, 8);
        for (int i = 0; i < 2; i++)
            for (int j = 0; j < 19; j++)
                if (vp8_bool_read(&br, vp8_mv_update_probs[i][j])) {
                    int prob = vp8_bool_bits(&br, 7);
                    info->probs.mv_probs[i][j] = (uint8_t)(prob ? (prob << 1) : 1);
                }
    }
    info->header_bits = vp8_bool_pos(&br);
    info->bool_state = br;
    int n_parts = 1 << info->log2_partitions;
    int offset = info->data_chunk_size + info->first_part_size + 3 * (n_parts - 1);
    if (offset > size)
        return 0;
    for (int i = 0; i < n_parts - 1; i++) {
        const uint8_t *p = data + info->data_chunk_size + info->first_part_size + 3 * i;
        info->partition_size[i + 1] = (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16);
        offset += (int)info->partition_size[i + 1];
    }
    if (offset > size)
        return 0;
    info->partition_size[n_parts] = (uint32_t)(size - offset);
    if (info->refresh_entropy_probs)
        *dec->vp8_state = info->probs;
    return 1;
}

static VASurfaceID vpx_ref_surface(LibVADecoder *dec, int index) {
    return index >= 0 ? dec->surfaces[index & 3] : VA_INVALID_SURFACE;
}

static void fill_vp8_iq(const struct VP8FrameInfo *info, VAIQMatrixBufferVP8 *iq) {
    memset(iq, 0, sizeof(*iq));
    for (int i = 0; i < 4; i++) {
        int base = info->probs.segmentation_enabled ? info->probs.quantizer_update_value[i] : info->y_ac_qi;
        if (info->probs.segmentation_enabled && !info->probs.segment_feature_mode)
            base += info->y_ac_qi;
        iq->quantization_index[i][0] = (uint16_t)clamp_int(base, 0, 127);
        iq->quantization_index[i][1] = (uint16_t)clamp_int(base + info->y_dc_delta, 0, 127);
        iq->quantization_index[i][2] = (uint16_t)clamp_int(base + info->y2_dc_delta, 0, 127);
        iq->quantization_index[i][3] = (uint16_t)clamp_int(base + info->y2_ac_delta, 0, 127);
        iq->quantization_index[i][4] = (uint16_t)clamp_int(base + info->uv_dc_delta, 0, 127);
        iq->quantization_index[i][5] = (uint16_t)clamp_int(base + info->uv_ac_delta, 0, 127);
    }
}

static LibVADecodeStatus vp8_decoder_decode(LibVADecoder *dec,
                                            const uint8_t *data, int data_len,
                                            LibVADecodedFrame *frame) {
    VABufferID buffers[5];
    int nbuf = 0;
    struct VP8FrameInfo info;
    VAPictureParameterBufferVP8 pic;
    VAProbabilityDataBufferVP8 prob;
    VAIQMatrixBufferVP8 iq;
    VASliceParameterBufferVP8 slice;
    int surface_index;
    VASurfaceID surface;
    VAStatus status;
    LibVADecodeStatus dstatus;
    long long t0, t1, t2;

    if (!parse_vp8_frame(dec, data, data_len, &info))
        return set_message(dec, LIBVA_DEC_UNSUPPORTED, "unsupported VP8 frame header");
    for (int i = 0; i < (int)(sizeof(buffers) / sizeof(buffers[0])); i++)
        buffers[i] = VA_INVALID_ID;
    surface_index = dec->surface_index++ & 3;
    surface = dec->surfaces[surface_index];

    memset(&pic, 0, sizeof(pic));
    pic.frame_width = (uint32_t)dec->width;
    pic.frame_height = (uint32_t)dec->height;
    pic.last_ref_frame = vpx_ref_surface(dec, dec->vpx_last_surface);
    pic.golden_ref_frame = vpx_ref_surface(dec, dec->vpx_golden_surface);
    pic.alt_ref_frame = vpx_ref_surface(dec, dec->vpx_alt_surface);
    pic.out_of_loop_frame = VA_INVALID_SURFACE;
    pic.pic_fields.bits.key_frame = !info.key_frame;
    pic.pic_fields.bits.version = (uint32_t)info.version;
    pic.pic_fields.bits.segmentation_enabled = (uint32_t)info.probs.segmentation_enabled;
    pic.pic_fields.bits.update_mb_segmentation_map = (uint32_t)info.probs.update_mb_segmentation_map;
    pic.pic_fields.bits.update_segment_feature_data = (uint32_t)info.probs.update_segment_feature_data;
    pic.pic_fields.bits.filter_type = (uint32_t)info.filter_type;
    pic.pic_fields.bits.sharpness_level = (uint32_t)info.sharpness_level;
    pic.pic_fields.bits.loop_filter_adj_enable = (uint32_t)info.probs.loop_filter_adj_enable;
    pic.pic_fields.bits.mode_ref_lf_delta_update = (uint32_t)info.probs.mode_ref_lf_delta_update;
    pic.pic_fields.bits.sign_bias_golden = (uint32_t)info.sign_bias_golden;
    pic.pic_fields.bits.sign_bias_alternate = (uint32_t)info.sign_bias_alternate;
    pic.pic_fields.bits.mb_no_coeff_skip = (uint32_t)info.mb_no_coeff_skip;
    pic.pic_fields.bits.loop_filter_disable = (uint32_t)(info.loop_filter_level == 0);
    memcpy(pic.mb_segment_tree_probs, info.probs.segment_prob, sizeof(pic.mb_segment_tree_probs));
    for (int i = 0; i < 4; i++) {
        int level = info.probs.segmentation_enabled ? info.probs.lf_update_value[i] : info.loop_filter_level;
        if (info.probs.segmentation_enabled && !info.probs.segment_feature_mode)
            level += info.loop_filter_level;
        pic.loop_filter_level[i] = (uint8_t)clamp_int(level, 0, 63);
        pic.loop_filter_deltas_ref_frame[i] = (int8_t)info.probs.ref_frame_delta[i];
        pic.loop_filter_deltas_mode[i] = (int8_t)info.probs.mb_mode_delta[i];
    }
    pic.prob_skip_false = (uint8_t)info.prob_skip_false;
    pic.prob_intra = (uint8_t)info.prob_intra;
    pic.prob_last = (uint8_t)info.prob_last;
    pic.prob_gf = (uint8_t)info.prob_gf;
    memcpy(pic.y_mode_probs, info.probs.y_mode_probs, sizeof(pic.y_mode_probs));
    memcpy(pic.uv_mode_probs, info.probs.uv_mode_probs, sizeof(pic.uv_mode_probs));
    memcpy(pic.mv_probs, info.probs.mv_probs, sizeof(pic.mv_probs));
    vp8_bool_state(&info.bool_state, &pic.bool_coder_ctx);

    memset(&prob, 0, sizeof(prob));
    memcpy(prob.dct_coeff_probs, info.probs.token_probs, sizeof(prob.dct_coeff_probs));
    fill_vp8_iq(&info, &iq);
    memset(&slice, 0, sizeof(slice));
    slice.slice_data_size = (uint32_t)data_len;
    slice.slice_data_offset = (uint32_t)info.data_chunk_size;
    slice.slice_data_flag = VA_SLICE_DATA_FLAG_ALL;
    slice.macroblock_offset = (uint32_t)info.header_bits;
    slice.num_of_partitions = (uint8_t)((1 << info.log2_partitions) + 1);
    slice.partition_size[0] = (uint32_t)(info.first_part_size - ((info.header_bits + 7) >> 3));
    for (int i = 1; i < slice.num_of_partitions && i < 9; i++)
        slice.partition_size[i] = info.partition_size[i];

    status = vaCreateBuffer(dec->display, dec->context, VAPictureParameterBufferType,
                            sizeof(pic), 1, &pic, &buffers[nbuf++]);
    if (status == VA_STATUS_SUCCESS)
        status = vaCreateBuffer(dec->display, dec->context, VAProbabilityBufferType,
                                sizeof(prob), 1, &prob, &buffers[nbuf++]);
    if (status == VA_STATUS_SUCCESS)
        status = vaCreateBuffer(dec->display, dec->context, VAIQMatrixBufferType,
                                sizeof(iq), 1, &iq, &buffers[nbuf++]);
    if (status == VA_STATUS_SUCCESS)
        status = vaCreateBuffer(dec->display, dec->context, VASliceParameterBufferType,
                                sizeof(slice), 1, &slice, &buffers[nbuf++]);
    if (status == VA_STATUS_SUCCESS)
        status = vaCreateBuffer(dec->display, dec->context, VASliceDataBufferType,
                                (unsigned int)data_len, 1, (void *)data, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(dec, buffers, nbuf);
        return set_error(dec, status, "vaCreateBuffer(VP8)");
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
        return set_error(dec, status, "VA VP8 decode submit");
    status = vaSyncSurface(dec->display, surface);
    t2 = usec_now();
    if (status != VA_STATUS_SUCCESS)
        return set_error(dec, status, "vaSyncSurface");
    dstatus = map_output(dec, surface, frame);
    if (dstatus != LIBVA_DEC_OK)
        return dstatus;
    if (info.copy_buffer_to_golden == 1)
        dec->vpx_golden_surface = dec->vpx_last_surface;
    else if (info.copy_buffer_to_golden == 2)
        dec->vpx_golden_surface = dec->vpx_alt_surface;
    if (info.copy_buffer_to_alternate == 1)
        dec->vpx_alt_surface = dec->vpx_last_surface;
    else if (info.copy_buffer_to_alternate == 2)
        dec->vpx_alt_surface = dec->vpx_golden_surface;
    if (info.refresh_golden_frame)
        dec->vpx_golden_surface = surface_index;
    if (info.refresh_alternate_frame)
        dec->vpx_alt_surface = surface_index;
    if (info.refresh_last || info.key_frame)
        dec->vpx_last_surface = surface_index;
    frame->us_submit = (int)(t1 - t0);
    frame->us_sync = (int)(t2 - t1);
    dec->frames++;
    return LIBVA_DEC_OK;
}

static void vp9_br_init(struct VP9BitReader *br, const uint8_t *data, int size) {
    br->data = data;
    br->size = size;
    br->bit_pos = 0;
}

static int vp9_bit(struct VP9BitReader *br) {
    int pos = br->bit_pos++;
    if (pos >= br->size * 8)
        return 0;
    return (br->data[pos >> 3] >> (7 - (pos & 7))) & 1;
}

static int vp9_bits(struct VP9BitReader *br, int bits) {
    int v = 0;
    for (int i = 0; i < bits; i++)
        v = (v << 1) | vp9_bit(br);
    return v;
}

static int vp9_sbits(struct VP9BitReader *br, int bits) {
    int v = vp9_bits(br, bits);
    return vp9_bit(br) ? -v : v;
}

static int vp9_read_delta_q(struct VP9BitReader *br) {
    return vp9_bit(br) ? vp9_sbits(br, 4) : 0;
}

static int vp9_read_profile(struct VP9BitReader *br) {
    int profile = vp9_bit(br);
    profile |= vp9_bit(br) << 1;
    if (profile > 2)
        vp9_bit(br);
    return profile;
}

static int vp9_read_sync_code(struct VP9BitReader *br) {
    return vp9_bits(br, 8) == 0x49 && vp9_bits(br, 8) == 0x83 && vp9_bits(br, 8) == 0x42;
}

static void vp9_read_frame_size(struct VP9BitReader *br, int *w, int *h) {
    *w = vp9_bits(br, 16) + 1;
    *h = vp9_bits(br, 16) + 1;
}

static void vp9_read_render_size(struct VP9BitReader *br, struct VP9FrameInfo *info) {
    if (vp9_bit(br))
        vp9_read_frame_size(br, &info->render_width, &info->render_height);
    else {
        info->render_width = info->frame_width;
        info->render_height = info->frame_height;
    }
}

static int vp9_read_color_config(struct VP9BitReader *br, struct VP9FrameInfo *info) {
    int color_space;
    info->bit_depth = 8;
    info->subsampling_x = 1;
    info->subsampling_y = 1;
    if (info->profile >= 2)
        info->bit_depth = vp9_bit(br) ? 12 : 10;
    color_space = vp9_bits(br, 3);
    if (color_space != 7) {
        info->color_range = vp9_bit(br);   /* 0=studio, 1=full */
        if (info->profile == 1 || info->profile == 3) {
            info->subsampling_x = vp9_bit(br);
            info->subsampling_y = vp9_bit(br);
            vp9_bit(br);              /* reserved */
        }
    } else if (info->profile == 1 || info->profile == 3) {
        info->color_range = 1;             /* CS_RGB (sRGB) is always full range */
        info->subsampling_x = 0;
        info->subsampling_y = 0;
        vp9_bit(br);                  /* reserved */
    } else {
        return 0;
    }
    return 1;
}

static void vp9_init_lf_deltas(struct VP9FrameInfo *info) {
    info->loop_filter_ref_deltas[0] = 1;
    info->loop_filter_ref_deltas[1] = 0;
    info->loop_filter_ref_deltas[2] = -1;
    info->loop_filter_ref_deltas[3] = -1;
    info->loop_filter_mode_deltas[0] = 0;
    info->loop_filter_mode_deltas[1] = 0;
}

static void init_vp9_state(LibVADecoder *dec) {
    dec->vp9_bit_depth = 8;
    dec->vp9_subsampling_x = 1;
    dec->vp9_subsampling_y = 1;
    dec->vp9_loop_filter_ref_deltas[0] = 1;
    dec->vp9_loop_filter_ref_deltas[1] = 0;
    dec->vp9_loop_filter_ref_deltas[2] = -1;
    dec->vp9_loop_filter_ref_deltas[3] = -1;
    dec->vp9_loop_filter_mode_deltas[0] = 0;
    dec->vp9_loop_filter_mode_deltas[1] = 0;
    dec->vp9_segmentation_abs_or_delta_update = 0;
    memset(dec->vp9_feature_enabled, 0, sizeof(dec->vp9_feature_enabled));
    memset(dec->vp9_feature_data, 0, sizeof(dec->vp9_feature_data));
}

static void load_vp9_state(LibVADecoder *dec, struct VP9FrameInfo *info) {
    /* color_config (bit depth / chroma subsampling) is only signalled in key and
     * intra-only frames; inter frames inherit it from the previous decoded frame. */
    info->bit_depth = dec->vp9_bit_depth;
    info->color_range = dec->vp9_color_range;
    info->subsampling_x = dec->vp9_subsampling_x;
    info->subsampling_y = dec->vp9_subsampling_y;
    memcpy(info->loop_filter_ref_deltas, dec->vp9_loop_filter_ref_deltas,
           sizeof(info->loop_filter_ref_deltas));
    memcpy(info->loop_filter_mode_deltas, dec->vp9_loop_filter_mode_deltas,
           sizeof(info->loop_filter_mode_deltas));
    info->segmentation_abs_or_delta_update = dec->vp9_segmentation_abs_or_delta_update;
    memcpy(info->feature_enabled, dec->vp9_feature_enabled, sizeof(info->feature_enabled));
    memcpy(info->feature_data, dec->vp9_feature_data, sizeof(info->feature_data));
}

static void save_vp9_state(LibVADecoder *dec, const struct VP9FrameInfo *info) {
    dec->vp9_bit_depth = info->bit_depth;
    dec->vp9_color_range = info->color_range;
    dec->full_range = info->color_range;
    dec->vp9_subsampling_x = info->subsampling_x;
    dec->vp9_subsampling_y = info->subsampling_y;
    memcpy(dec->vp9_loop_filter_ref_deltas, info->loop_filter_ref_deltas,
           sizeof(dec->vp9_loop_filter_ref_deltas));
    memcpy(dec->vp9_loop_filter_mode_deltas, info->loop_filter_mode_deltas,
           sizeof(dec->vp9_loop_filter_mode_deltas));
    if (info->segmentation_enabled) {
        dec->vp9_segmentation_abs_or_delta_update = info->segmentation_abs_or_delta_update;
        memcpy(dec->vp9_feature_enabled, info->feature_enabled, sizeof(dec->vp9_feature_enabled));
        memcpy(dec->vp9_feature_data, info->feature_data, sizeof(dec->vp9_feature_data));
    }
}

static void vp9_read_loop_filter(struct VP9BitReader *br, struct VP9FrameInfo *info) {
    info->loop_filter_level = vp9_bits(br, 6);
    info->loop_filter_sharpness = vp9_bits(br, 3);
    info->loop_filter_delta_enabled = vp9_bit(br);
    if (info->loop_filter_delta_enabled && vp9_bit(br)) {
        for (int i = 0; i < 4; i++)
            if (vp9_bit(br))
                info->loop_filter_ref_deltas[i] = vp9_sbits(br, 6);
        for (int i = 0; i < 2; i++)
            if (vp9_bit(br))
                info->loop_filter_mode_deltas[i] = vp9_sbits(br, 6);
    }
}

static void vp9_read_quant(struct VP9BitReader *br, struct VP9FrameInfo *info) {
    info->base_q_idx = vp9_bits(br, 8);
    info->delta_q_y_dc = vp9_read_delta_q(br);
    info->delta_q_uv_dc = vp9_read_delta_q(br);
    info->delta_q_uv_ac = vp9_read_delta_q(br);
    info->lossless = info->base_q_idx == 0 && info->delta_q_y_dc == 0 &&
                     info->delta_q_uv_dc == 0 && info->delta_q_uv_ac == 0;
}

static int vp9_seg_signed(int feature) {
    return feature == 0 || feature == 1;
}

static int vp9_seg_bits(int feature) {
    static const int bits[4] = {8, 6, 2, 0};
    return bits[feature];
}

static void vp9_read_segmentation(struct VP9BitReader *br, struct VP9FrameInfo *info) {
    info->segmentation_enabled = vp9_bit(br);
    if (!info->segmentation_enabled)
        return;
    info->segmentation_update_map = vp9_bit(br);
    if (info->segmentation_update_map) {
        for (int i = 0; i < 7; i++)
            info->segmentation_tree_probs[i] = vp9_bit(br) ? (uint8_t)vp9_bits(br, 8) : 255;
        info->segmentation_temporal_update = vp9_bit(br);
        if (info->segmentation_temporal_update) {
            for (int i = 0; i < 3; i++)
                info->segmentation_pred_probs[i] = vp9_bit(br) ? (uint8_t)vp9_bits(br, 8) : 255;
        } else {
            memset(info->segmentation_pred_probs, 255, sizeof(info->segmentation_pred_probs));
        }
    }
    if (vp9_bit(br)) {
        info->segmentation_abs_or_delta_update = vp9_bit(br);
        for (int i = 0; i < 8; i++) {
            for (int j = 0; j < 4; j++) {
                info->feature_enabled[i][j] = vp9_bit(br);
                if (info->feature_enabled[i][j]) {
                    info->feature_data[i][j] = vp9_bits(br, vp9_seg_bits(j));
                    if (vp9_seg_signed(j) && vp9_bit(br))
                        info->feature_data[i][j] = -info->feature_data[i][j];
                }
            }
        }
    }
}

static void vp9_read_tiles(struct VP9BitReader *br, struct VP9FrameInfo *info) {
    int sb64_cols = (info->frame_width + 63) / 64;
    int min_log2 = 0, max_log2 = 0;
    while ((64 << min_log2) < sb64_cols)
        min_log2++;
    while ((sb64_cols >> max_log2) >= 4)
        max_log2++;
    info->tile_cols_log2 = min_log2;
    while (info->tile_cols_log2 < max_log2 && vp9_bit(br))
        info->tile_cols_log2++;
    info->tile_rows_log2 = vp9_bit(br);
    if (info->tile_rows_log2)
        info->tile_rows_log2 += vp9_bit(br);
}

static int parse_vp9_frame(LibVADecoder *dec, const uint8_t *data, int size,
                           struct VP9FrameInfo *info) {
    struct VP9BitReader br;
    int marker;
    memset(info, 0, sizeof(*info));
    load_vp9_state(dec, info);
    vp9_br_init(&br, data, size);
    marker = vp9_bits(&br, 2);
    if (marker != 2)
        return 0;
    info->profile = vp9_read_profile(&br);
    if (info->profile > 1 && !dec->output_444)
        return 0;
    if (vp9_bit(&br)) {               /* show_existing_frame */
        int ref = vp9_bits(&br, 3);
        (void)ref;
        return 0;
    }
    info->frame_type = vp9_bit(&br);
    info->show_frame = vp9_bit(&br);
    info->error_resilient_mode = vp9_bit(&br);
    if (info->frame_type == 0) {
        if (!vp9_read_sync_code(&br) || !vp9_read_color_config(&br, info))
            return 0;
        vp9_read_frame_size(&br, &info->frame_width, &info->frame_height);
        vp9_read_render_size(&br, info);
        info->refresh_frame_flags = 0xff;
    } else {
        if (!info->show_frame)
            info->intra_only = vp9_bit(&br);
        if (!info->error_resilient_mode)
            info->reset_frame_context = vp9_bits(&br, 2);
        if (info->intra_only) {
            if (!vp9_read_sync_code(&br))
                return 0;
            if (info->profile > 0) {
                if (!vp9_read_color_config(&br, info))
                    return 0;
            } else {
                info->bit_depth = 8;
                info->subsampling_x = 1;
                info->subsampling_y = 1;
            }
            info->refresh_frame_flags = vp9_bits(&br, 8);
            vp9_read_frame_size(&br, &info->frame_width, &info->frame_height);
            vp9_read_render_size(&br, info);
        } else {
            info->refresh_frame_flags = vp9_bits(&br, 8);
            for (int i = 0; i < 3; i++) {
                info->ref_frame_idx[i] = vp9_bits(&br, 3);
                info->ref_frame_sign_bias[i + 1] = vp9_bit(&br);
            }
            for (int i = 0; i < 3; i++) {
                if (vp9_bit(&br)) {
                    info->frame_width = dec->width;
                    info->frame_height = dec->height;
                    break;
                }
            }
            if (!info->frame_width)
                vp9_read_frame_size(&br, &info->frame_width, &info->frame_height);
            vp9_read_render_size(&br, info);
            info->allow_high_precision_mv = vp9_bit(&br);
            info->interpolation_filter = vp9_bit(&br) ? 4 : vp9_bits(&br, 2);
        }
    }
    if (info->frame_type == 0 || info->intra_only || info->error_resilient_mode) {
        vp9_init_lf_deltas(info);
        info->segmentation_abs_or_delta_update = 0;
        memset(info->feature_enabled, 0, sizeof(info->feature_enabled));
        memset(info->feature_data, 0, sizeof(info->feature_data));
    }
    if (!info->error_resilient_mode) {
        info->refresh_frame_context = vp9_bit(&br);
        info->frame_parallel_decoding_mode = vp9_bit(&br);
    } else {
        info->refresh_frame_context = 0;
        info->frame_parallel_decoding_mode = 1;
    }
    info->frame_context_idx = vp9_bits(&br, 2);
    vp9_read_loop_filter(&br, info);
    vp9_read_quant(&br, info);
    vp9_read_segmentation(&br, info);
    vp9_read_tiles(&br, info);
    info->first_partition_size = vp9_bits(&br, 16);
    info->uncompressed_header_bytes = (br.bit_pos + 7) / 8;
    if (info->frame_width <= 0)
        info->frame_width = dec->width;
    if (info->frame_height <= 0)
        info->frame_height = dec->height;
    return info->uncompressed_header_bytes <= size;
}

static int vp9_dc_quant(int q, int delta) {
    return vp9_dc_qlookup[clamp_int(q + delta, 0, 255)];
}

static int vp9_ac_quant(int q, int delta) {
    return vp9_ac_qlookup[clamp_int(q + delta, 0, 255)];
}

static int vp9_seg_qindex(const struct VP9FrameInfo *info, int segment) {
    int q = info->base_q_idx;
    if (info->segmentation_enabled && info->feature_enabled[segment][0]) {
        if (info->segmentation_abs_or_delta_update)
            q = info->feature_data[segment][0];
        else
            q += info->feature_data[segment][0];
    }
    return clamp_int(q, 0, 255);
}

static void fill_vp9_segment(const struct VP9FrameInfo *info, int segment,
                             VASegmentParameterVP9 *seg) {
    int q = vp9_seg_qindex(info, segment);
    int lvl = info->loop_filter_level;
    int scale = 1 << (lvl >> 5);
    memset(seg, 0, sizeof(*seg));
    seg->segment_flags.fields.segment_reference_enabled =
        (uint16_t)info->feature_enabled[segment][2];
    seg->segment_flags.fields.segment_reference =
        (uint16_t)info->feature_data[segment][2];
    seg->segment_flags.fields.segment_reference_skipped =
        (uint16_t)info->feature_enabled[segment][3];
    seg->luma_dc_quant_scale = (int16_t)vp9_dc_quant(q, info->delta_q_y_dc);
    seg->luma_ac_quant_scale = (int16_t)vp9_ac_quant(q, 0);
    seg->chroma_dc_quant_scale = (int16_t)vp9_dc_quant(q, info->delta_q_uv_dc);
    seg->chroma_ac_quant_scale = (int16_t)vp9_ac_quant(q, info->delta_q_uv_ac);
    if (info->segmentation_enabled && info->feature_enabled[segment][1]) {
        lvl = info->segmentation_abs_or_delta_update ?
              info->feature_data[segment][1] : lvl + info->feature_data[segment][1];
    }
    lvl = clamp_int(lvl, 0, 63);
    for (int ref = 0; ref < 4; ref++) {
        for (int mode = 0; mode < 2; mode++) {
            int fl = lvl;
            if (info->loop_filter_delta_enabled)
                fl += (info->loop_filter_ref_deltas[ref] + info->loop_filter_mode_deltas[mode]) * scale;
            seg->filter_level[ref][mode] = (uint8_t)clamp_int(fl, 0, 63);
        }
    }
}

static LibVADecodeStatus vp9_decoder_decode(LibVADecoder *dec,
                                            const uint8_t *data, int data_len,
                                            LibVADecodedFrame *frame) {
    VABufferID buffers[3];
    int nbuf = 0;
    struct VP9FrameInfo info;
    VADecPictureParameterBufferVP9 pic;
    VASliceParameterBufferVP9 slice;
    int surface_index;
    VASurfaceID surface;
    VAStatus status;
    LibVADecodeStatus dstatus;
    long long t0, t1, t2;

    if (!parse_vp9_frame(dec, data, data_len, &info))
        return set_message(dec, LIBVA_DEC_UNSUPPORTED, "unsupported VP9 frame header");
    for (int i = 0; i < (int)(sizeof(buffers) / sizeof(buffers[0])); i++)
        buffers[i] = VA_INVALID_ID;
    surface_index = dec->surface_index++ & 3;
    surface = dec->surfaces[surface_index];

    memset(&pic, 0, sizeof(pic));
    pic.frame_width = (uint16_t)info.frame_width;
    pic.frame_height = (uint16_t)info.frame_height;
    for (int i = 0; i < 8; i++)
        pic.reference_frames[i] = dec->vp9_refs[i];
    pic.pic_fields.bits.subsampling_x = (uint32_t)info.subsampling_x;
    pic.pic_fields.bits.subsampling_y = (uint32_t)info.subsampling_y;
    pic.pic_fields.bits.frame_type = (uint32_t)info.frame_type;
    pic.pic_fields.bits.show_frame = (uint32_t)info.show_frame;
    pic.pic_fields.bits.error_resilient_mode = (uint32_t)info.error_resilient_mode;
    pic.pic_fields.bits.intra_only = (uint32_t)info.intra_only;
    pic.pic_fields.bits.allow_high_precision_mv = (uint32_t)info.allow_high_precision_mv;
    pic.pic_fields.bits.mcomp_filter_type = (uint32_t)info.interpolation_filter;
    pic.pic_fields.bits.frame_parallel_decoding_mode = (uint32_t)info.frame_parallel_decoding_mode;
    pic.pic_fields.bits.reset_frame_context = (uint32_t)info.reset_frame_context;
    pic.pic_fields.bits.refresh_frame_context = (uint32_t)info.refresh_frame_context;
    pic.pic_fields.bits.frame_context_idx = (uint32_t)info.frame_context_idx;
    pic.pic_fields.bits.segmentation_enabled = (uint32_t)info.segmentation_enabled;
    pic.pic_fields.bits.segmentation_temporal_update = (uint32_t)info.segmentation_temporal_update;
    pic.pic_fields.bits.segmentation_update_map = (uint32_t)info.segmentation_update_map;
    pic.pic_fields.bits.last_ref_frame = (uint32_t)info.ref_frame_idx[0];
    pic.pic_fields.bits.last_ref_frame_sign_bias = (uint32_t)info.ref_frame_sign_bias[1];
    pic.pic_fields.bits.golden_ref_frame = (uint32_t)info.ref_frame_idx[1];
    pic.pic_fields.bits.golden_ref_frame_sign_bias = (uint32_t)info.ref_frame_sign_bias[2];
    pic.pic_fields.bits.alt_ref_frame = (uint32_t)info.ref_frame_idx[2];
    pic.pic_fields.bits.alt_ref_frame_sign_bias = (uint32_t)info.ref_frame_sign_bias[3];
    pic.pic_fields.bits.lossless_flag = (uint32_t)info.lossless;
    pic.filter_level = (uint8_t)info.loop_filter_level;
    pic.sharpness_level = (uint8_t)info.loop_filter_sharpness;
    pic.log2_tile_rows = (uint8_t)info.tile_rows_log2;
    pic.log2_tile_columns = (uint8_t)info.tile_cols_log2;
    pic.frame_header_length_in_bytes = (uint8_t)info.uncompressed_header_bytes;
    pic.first_partition_size = (uint16_t)info.first_partition_size;
    memcpy(pic.mb_segment_tree_probs, info.segmentation_tree_probs, sizeof(pic.mb_segment_tree_probs));
    if (info.segmentation_temporal_update)
        memcpy(pic.segment_pred_probs, info.segmentation_pred_probs, sizeof(pic.segment_pred_probs));
    else
        memset(pic.segment_pred_probs, 255, sizeof(pic.segment_pred_probs));
    pic.profile = (uint8_t)info.profile;
    pic.bit_depth = (uint8_t)info.bit_depth;

    memset(&slice, 0, sizeof(slice));
    slice.slice_data_size = (uint32_t)data_len;
    slice.slice_data_offset = 0;
    slice.slice_data_flag = VA_SLICE_DATA_FLAG_ALL;
    for (int i = 0; i < 8; i++)
        fill_vp9_segment(&info, i, &slice.seg_param[i]);

    status = vaCreateBuffer(dec->display, dec->context, VAPictureParameterBufferType,
                            sizeof(pic), 1, &pic, &buffers[nbuf++]);
    if (status == VA_STATUS_SUCCESS)
        status = vaCreateBuffer(dec->display, dec->context, VASliceParameterBufferType,
                                sizeof(slice), 1, &slice, &buffers[nbuf++]);
    if (status == VA_STATUS_SUCCESS)
        status = vaCreateBuffer(dec->display, dec->context, VASliceDataBufferType,
                                (unsigned int)data_len, 1, (void *)data, &buffers[nbuf++]);
    if (status != VA_STATUS_SUCCESS) {
        destroy_buffers(dec, buffers, nbuf);
        return set_error(dec, status, "vaCreateBuffer(VP9)");
    }
    libva_log("VP9 dbg: STORED bitdepth=%d ss=%d,%d", dec->vp9_bit_depth, dec->vp9_subsampling_x, dec->vp9_subsampling_y);
    libva_log("VP9 dbg: profile=%d type=%d show=%d errres=%d intra_only=%d bitdepth=%d ss=%d,%d "
              "size=%dx%d refidx=%d,%d,%d refresh=0x%02x reffrm=%u,%u,%u,%u,%u,%u,%u,%u "
              "lf_level=%d lf_sharp=%d base_q=%d lossless=%d seg_en=%d tile=%d,%d fhlen=%d fps=%d datalen=%d",
              info.profile, info.frame_type, info.show_frame, info.error_resilient_mode, info.intra_only,
              info.bit_depth, info.subsampling_x, info.subsampling_y,
              info.frame_width, info.frame_height,
              info.ref_frame_idx[0], info.ref_frame_idx[1], info.ref_frame_idx[2],
              info.refresh_frame_flags,
              (unsigned)dec->vp9_refs[0], (unsigned)dec->vp9_refs[1], (unsigned)dec->vp9_refs[2],
              (unsigned)dec->vp9_refs[3], (unsigned)dec->vp9_refs[4], (unsigned)dec->vp9_refs[5],
              (unsigned)dec->vp9_refs[6], (unsigned)dec->vp9_refs[7],
              info.loop_filter_level, info.loop_filter_sharpness, info.base_q_idx, info.lossless,
              info.segmentation_enabled, info.tile_cols_log2, info.tile_rows_log2,
              info.uncompressed_header_bytes, info.first_partition_size, data_len);
    t0 = usec_now();
    status = vaBeginPicture(dec->display, dec->context, surface);
    if (status == VA_STATUS_SUCCESS)
        status = vaRenderPicture(dec->display, dec->context, buffers, nbuf);
    if (status == VA_STATUS_SUCCESS)
        status = vaEndPicture(dec->display, dec->context);
    t1 = usec_now();
    destroy_buffers(dec, buffers, nbuf);
    if (status != VA_STATUS_SUCCESS)
        return set_error(dec, status, "VA VP9 decode submit");
    status = vaSyncSurface(dec->display, surface);
    t2 = usec_now();
    if (status != VA_STATUS_SUCCESS)
        return set_error(dec, status, "vaSyncSurface");
    /* update the decoder state (incl. the colour range) before mapping the output,
     * so that map_output reports this frame's range and not the previous one's: */
    save_vp9_state(dec, &info);
    dstatus = map_output(dec, surface, frame);
    if (dstatus != LIBVA_DEC_OK)
        return dstatus;
    for (int i = 0; i < 8; i++) {
        if (info.refresh_frame_flags & (1 << i))
            dec->vp9_refs[i] = surface;
    }
    frame->us_submit = (int)(t1 - t0);
    frame->us_sync = (int)(t2 - t1);
    dec->frames++;
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
    dec->full_range = params.video_full_range_flag;
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
    if (params.pic_order_cnt_type == 1)
        return set_message(dec, LIBVA_DEC_UNSUPPORTED,
                           "H.264 pic_order_cnt_type 1 is not supported");
    if (is_idr) {
        /* spec 8.2.5.1: IDR unmarks all reference pictures */
        h264_dpb_flush(dec);
        dec->poc_prev_lsb = 0;
        dec->poc_prev_msb = 0;
        dec->poc_prev_frame_num = 0;
        dec->poc_prev_frame_num_offset = 0;
    }
    int top_foc = 0, bottom_foc = 0;
    if (h264_compute_poc(dec, &params, first, is_idr, &top_foc, &bottom_foc) != 0)
        return set_message(dec, LIBVA_DEC_UNSUPPORTED,
                           "H.264 pic_order_cnt_type 1 is not supported");
    surface_index = h264_pick_surface(dec);
    if (surface_index < 0)
        return set_message(dec, LIBVA_DEC_ERROR, "no free H.264 surface");
    surface = dec->surfaces[surface_index];

    memset(&pic, 0, sizeof(pic));
    pic.CurrPic.picture_id = surface;
    pic.CurrPic.frame_idx = (uint32_t)first->frame_num;
    pic.CurrPic.flags = first->nal_ref_idc ? VA_PICTURE_H264_SHORT_TERM_REFERENCE : 0;
    pic.CurrPic.TopFieldOrderCnt = top_foc;
    pic.CurrPic.BottomFieldOrderCnt = bottom_foc;
    for (int i = 0; i < 16; i++)
        fill_invalid_picture(&pic.ReferenceFrames[i]);
    {
        int n = 0;
        for (int i = 0; i < H264_DPB_SIZE && n < 16; i++) {
            if (dec->dpb[i].in_use)
                h264_fill_va_picture(&pic.ReferenceFrames[n++], &dec->dpb[i]);
        }
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
    pic.pic_fields.bits.reference_pic_flag = (uint32_t)(first->nal_ref_idc != 0);
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
        if ((si->slice_type % 5) == 0 || (si->slice_type % 5) == 3) {
            struct H264DPBEntry *l0[32];
            int nl0 = h264_build_ref_list_l0(dec, &params, si, l0, 32);
            for (int i = 0; i < nl0; i++)
                h264_fill_va_picture(&slice.RefPicList0[i], l0[i]);
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
    if (first->nal_ref_idc) {
        int cur_is_lt = 0, cur_lt_idx = 0, had_mmco5 = 0;
        int ins_frame_num = first->frame_num;
        if (is_idr) {
            /* DPB already flushed before decode */
            cur_is_lt = first->idr_long_term_reference_flag;
        } else if (first->adaptive_ref_pic_marking) {
            h264_dpb_apply_mmco(dec, &params, first, first->frame_num,
                                &cur_is_lt, &cur_lt_idx, &had_mmco5);
        } else {
            h264_dpb_sliding_window(dec, &params, first->frame_num);
        }
        if (had_mmco5) {
            /* spec 8.2.1: after MMCO5 the current picture counts as
             * frame_num 0 with its POC rebased to zero */
            int temp = top_foc < bottom_foc ? top_foc : bottom_foc;
            top_foc -= temp;
            bottom_foc -= temp;
            ins_frame_num = 0;
            dec->poc_prev_lsb = top_foc;
            dec->poc_prev_msb = 0;
            dec->poc_prev_frame_num = 0;
            dec->poc_prev_frame_num_offset = 0;
        }
        h264_dpb_insert(dec, surface_index, surface, ins_frame_num,
                        top_foc, bottom_foc, cur_is_lt, cur_lt_idx);
    }
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
    if (dec->codec == LIBVA_CODEC_VP8)
        return vp8_decoder_decode(dec, data, data_len, frame);
    if (dec->codec == LIBVA_CODEC_VP9)
        return vp9_decoder_decode(dec, data, data_len, frame);
    return set_message(dec, LIBVA_DEC_UNSUPPORTED, "unknown VA decode codec");
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
