# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import errno
from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec
from xpra.util.env import envbool
from xpra.util.str_fn import hexstr
from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper, PlanarFormat
from xpra.log import Logger

log = Logger("decoder", "aom")

from libcpp cimport bool as bool_t
from libc.string cimport memset, memcpy
from libc.stdint cimport uint8_t, uint16_t, uint32_t, int64_t, uintptr_t
from xpra.buffers.membuf cimport padbuf, MemBuf, buffer_context  # pylint: disable=syntax-error
from xpra.codecs.argb.argb cimport show_plane_range


cdef unsigned char debug_enabled = log.is_debug_enabled()
cdef unsigned char SHOW_PLANE_RANGES = envbool("XPRA_SHOW_PLANE_RANGES", False)


cdef inline unsigned int roundup(unsigned int n, unsigned int m) noexcept nogil:
    return (n + m - 1) & ~(m - 1)


cdef unsigned int ENOMEM = errno.ENOMEM


cdef extern from "stdarg.h":
    ctypedef struct va_list:
        pass


cdef extern from "string.h":
    int vsnprintf(char * s, size_t n, const char *fmt, va_list arg) nogil


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
        AOM_IMG_FMT_NV12
        AOM_IMG_FMT_I42016
        AOM_IMG_FMT_YV1216
        AOM_IMG_FMT_I42216
        AOM_IMG_FMT_I44416

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


FORMAT_STRS: Dict[aom_img_fmt_t, str] = {
    AOM_IMG_FMT_NONE: "None",
    AOM_IMG_FMT_I420: "YUV420P",
    AOM_IMG_FMT_I422: "YUV422P",
    AOM_IMG_FMT_I444: "YUV444P",
    AOM_IMG_FMT_YV12: "YV12",
    AOM_IMG_FMT_NV12: "NV12",
    AOM_IMG_FMT_AOMYV12: "AOMYV12",
    AOM_IMG_FMT_AOMI420: "AOMI420",
    AOM_IMG_FMT_I42016: "YUV420P16",
    AOM_IMG_FMT_YV1216: "YV12P16",
    AOM_IMG_FMT_I42216: "YUV422P16",
    AOM_IMG_FMT_I44416: "YUV444P16",
}


cdef extern from "aom/aomdx.h":
    aom_codec_iface_t *aom_codec_av1_dx() nogil


def get_version() -> Tuple[int, int, int]:
    cdef int version = aom_codec_version()
    return (version >> 16, (version >> 8) & 0xFF, version & 0xFF)


def get_type() -> str:
    return "aom"


def get_info() -> Dict[str, Any]:
    return {
        "version": get_version(),
        "abi": AOM_DECODER_ABI_VERSION,
    }


def get_encodings() -> Sequence[str]:
    return ("av1", )


def get_min_size(encoding) -> Tuple[int, int]:
    return 32, 32


MAX_WIDTH, MAX_HEIGHT = (8192, 4096)

COLORSPACES = ("YUV420P", "YUV422P", "YUV444P", "YUV420P16", "YUV422P16", "YUV444P16", "NV12")


def get_specs() -> Sequence[VideoSpec]:
    specs = []
    for cs in COLORSPACES:
        specs.append(
            VideoSpec(
                encoding="av1", input_colorspace=cs, output_colorspaces=(cs, ),
                has_lossless_mode=False,
                codec_class=Decoder, codec_type=get_type(),
                quality=40, speed=20,
                size_efficiency=40,
                setup_cost=0, width_mask=0xFFFE, height_mask=0xFFFE,
                max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
            )
        )
    return specs


def check(r: aom_codec_err_t) -> None:
    if r == AOM_CODEC_OK:
        return
    elif r == AOM_CODEC_MEM_ERROR:
        raise MemoryError("AOM codec memory error")
    elif r == AOM_CODEC_ABI_MISMATCH:
        raise RuntimeError("AOM codec ABI mismatch")
    elif r == AOM_CODEC_INCAPABLE:
        raise RuntimeError("AOM codec incapable")
    elif r == AOM_CODEC_UNSUP_BITSTREAM:
        raise RuntimeError("AOM codec unsupported bitstream")
    elif r == AOM_CODEC_UNSUP_FEATURE:
        raise RuntimeError("AOM codec unsupported feature")
    elif r == AOM_CODEC_CORRUPT_FRAME:
        raise RuntimeError("AOM codec corrupt frame")
    elif r == AOM_CODEC_INVALID_PARAM:
        raise ValueError("AOM codec invalid parameter")
    else:
        raise RuntimeError(f"AOM codec error: {aom_codec_err_to_string(r).decode('utf-8')}")


cdef class Decoder:
    cdef unsigned long frames
    cdef unsigned int width
    cdef unsigned int height
    cdef object colorspace
    cdef aom_codec_iface_t *codec
    cdef aom_codec_ctx_t context

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("aom.init_context%s", (encoding, width, height, colorspace))
        assert encoding == "av1", f"invalid encoding: {encoding}"
        if colorspace not in COLORSPACES:
            raise ValueError(f"invalid colorspace: {colorspace!r}, expected one of {COLORSPACES}")
        self.width = width
        self.height = height
        self.colorspace = colorspace
        self.frames = 0
        self.codec = <aom_codec_iface_t*> aom_codec_av1_dx()
        name = aom_codec_iface_name(self.codec)
        log("codec: %s", name.decode("utf-8"))
        cdef aom_codec_dec_cfg_t config
        memset(&config, 0, sizeof(aom_codec_dec_cfg_t))
        config.threads = options.intget("threads", 0)  # 0 means use the default number of threads
        config.w = width
        config.h = height
        config.allow_lowbitdepth = 1
        cdef aom_codec_err_t err = aom_codec_dec_init_ver(&self.context, self.codec, &config,
                                                          0, AOM_DECODER_ABI_VERSION)
        check(err)

    def get_encoding(self) -> str:
        return "av1"

    def get_colorspace(self) -> str:
        return self.colorspace

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return bool(self.codec != NULL)

    def get_type(self) -> str:
        return "aom"

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        self.frames = 0
        self.width = 0
        self.height = 0
        self.colorspace = ""
        cdef aom_codec_err_t r
        if self.codec != NULL:
            r = aom_codec_destroy(&self.context)
            if r:
                log.error("Error destroying codec: %i", r)
            self.codec = NULL

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "colorspace"    : self.colorspace,
        }
        return info

    def decompress_image(self, data: bytes, options: typedict) -> ImageWrapper:
        log("decompress_image(%i bytes, %s)", len(data), options)
        cdef aom_codec_err_t r

        cdef size_t data_len
        cdef const uint8_t* data_buf
        with buffer_context(data) as bc:
            data_len = len(bc)
            data_buf = <const uint8_t*> (<uintptr_t> int(bc))
            with nogil:
                r = aom_codec_decode(&self.context, data_buf, data_len, NULL)
        log("aom_codec_decode(..)=%s", r)
        check(r)

        cdef aom_codec_iter_t iter = NULL
        cdef aom_image_t *image = NULL
        with nogil:
            image = aom_codec_get_frame(&self.context, &iter)
        if image == NULL:
            err = aom_codec_error_detail(&self.context).decode("utf-8")
            log.error("Error retrieving frame: %s", err)
            raise RuntimeError(err)

        pixel_format = FORMAT_STRS.get(image.fmt, "unknown: %i" % image.fmt)
        log("got aom image at %#x, pixel format %s", <uintptr_t> image, pixel_format)
        if pixel_format not in COLORSPACES:
            raise RuntimeError(f"Unsupported image format %r" % FORMAT_STRS.get(image.fmt, "unknown"))
        Bpp = 6 if pixel_format.endswith("P16") else 3
        if image.bit_depth != AOM_BITS_8:
            raise RuntimeError("image bit depth %i is not supported yet" % image.bit_depth)
        depth = Bpp * image.bit_depth

        # expose these eventually:
        # aom_color_primaries color_primaries
        # aom_transfer_characteristics transfer_characteristics
        # aom_matrix_coefficients matrix_coefficients
        if image.monochrome:
            log("monochrome image")
        # aom_chroma_sample_position chroma_sample_position
        full_range = image.range == AOM_CR_FULL_RANGE
        if image.w < self.width or image.h < self.height:
            log.error("Error: image size %ix%i does not match expected size %ix%i",
                      image.w, image.h, self.width, self.height)
            return None

        # we have to copy the image data to a new buffer,
        # until we can implement the aom_codec_set_frame_buffer_functions callbacks
        pyplanes = []
        pystrides = []
        cdef MemBuf plane_buf
        cdef int plane_width
        cdef int plane_height
        cdef int stride
        for i in range(3):
            assert image.planes[i] != NULL
            plane_width = aom_img_plane_width(image, i)
            plane_height = aom_img_plane_height(image, i)
            stride = image.stride[i]
            log("plane %s: %ix%i, stride=%i", "YUV"[i], plane_width, plane_height, stride)
            # copy:
            plane_buf = padbuf(plane_height * stride, stride)
            memcpy(<void *> plane_buf.get_mem(), <const void *> image.planes[i], plane_height * stride)
            pyplanes.append(memoryview(plane_buf))
            pystrides.append(stride)

        if SHOW_PLANE_RANGES:
            show_plane_range("Y", pyplanes[0], self.width, pystrides[0], self.height)
            log.info("Y[0]=%s", hexstr(pyplanes[0][:64]))
            show_plane_range("U", pyplanes[1], self.width, pystrides[1], self.height//2)
            log.info("U[0]=%s", hexstr(pyplanes[1][:64]))
            show_plane_range("V", pyplanes[2], self.width, pystrides[2], self.height//2)
            log.info("V[0]=%s", hexstr(pyplanes[2][:64]))

        self.frames += 1
        return ImageWrapper(0, 0, self.width, self.height, pyplanes, pixel_format, depth,
                            pystrides, planes=PlanarFormat.PLANAR_3, bytesperpixel=Bpp, full_range=full_range)


def selftest(full=False) -> None:
    log("aom selftest: %s", get_info())
    if log.is_debug_enabled():
        global debug_enabled
        debug_enabled = True
    from xpra.codecs.checks import testdecoder
    from xpra.codecs.aom import decoder
    testdecoder(decoder, full)
