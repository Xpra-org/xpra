# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import os
from time import monotonic
from typing import Any, Tuple, List, Dict
from collections.abc import Sequence

from xpra.log import Logger
log = Logger("decoder", "vpx")

from xpra.codecs.constants import VideoSpec, get_subsampling_divs, check_image_size, MAX_IMAGE_DIMENSION
from xpra.codecs.image import ImageWrapper
from xpra.common import SizedBuffer
from xpra.util.objects import typedict
from xpra.util.env import envint

from libc.stdint cimport uintptr_t, uint8_t
from libc.string cimport memset, memcpy
from libc.stdlib cimport malloc
from xpra.codecs.vpx.vpx cimport (
    vpx_img_fmt_t, vpx_codec_iface_t,
    vpx_codec_iter_t, vpx_codec_flags_t, vpx_codec_err_t,
    vpx_codec_ctx_t,
    vpx_codec_error, vpx_codec_destroy,
    vpx_codec_version_str, vpx_codec_build_config,
    VPX_IMG_FMT_I420, VPX_IMG_FMT_I422, VPX_IMG_FMT_I444, VPX_IMG_FMT_I42016,
    VPX_CS_UNKNOWN, VPX_CS_BT_601, VPX_CS_BT_709,
    VPX_CS_SMPTE_170, VPX_CS_SMPTE_240, VPX_CS_BT_2020,
    VPX_CS_RESERVED, VPX_CS_SRGB,
    vpx_image_t,
    VPX_CR_STUDIO_RANGE, VPX_CR_FULL_RANGE,
)
from xpra.buffers.membuf cimport padbuf, MemBuf, buffer_context  # pylint: disable=syntax-error


from xpra.codecs.debug import get_save_to_file
SAVE_TO_FILE = get_save_to_file()

VPX_COLOR_SPACES : Dict[int,str] = {
    VPX_CS_UNKNOWN  : "unknown",
    VPX_CS_BT_601   : "BT601",
    VPX_CS_BT_709   : "BT709",
    VPX_CS_SMPTE_170    : "SMPTE170",
    VPX_CS_SMPTE_240    : "SMPTE240",
    VPX_CS_BT_2020  : "BT2020",
    VPX_CS_RESERVED : "reserved",
    VPX_CS_SRGB     : "SRGB",
}

VPX_COLOR_RANGES : Dict[int,str] = {
    VPX_CR_STUDIO_RANGE : "studio",
    VPX_CR_FULL_RANGE   : " full",
}


cdef unsigned int cpus = os.cpu_count()
cdef int VPX_THREADS = envint("XPRA_VPX_THREADS", max(1, cpus-1))


cdef inline int roundup(int n, int m) noexcept nogil:
    return (n + m - 1) & ~(m - 1)


cdef extern from "vpx/vp8dx.h":
    const vpx_codec_iface_t *vpx_codec_vp8_dx()
    const vpx_codec_iface_t *vpx_codec_vp9_dx()

cdef extern from "vpx/vpx_decoder.h":
    ctypedef struct vpx_codec_enc_cfg_t:
        unsigned int rc_target_bitrate
        unsigned int g_lag_in_frames
        unsigned int rc_dropframe_thresh
        unsigned int rc_resize_allowed
        unsigned int g_w
        unsigned int g_h
        unsigned int g_error_resilient
    ctypedef struct vpx_codec_dec_cfg_t:
        unsigned int threads
        unsigned int w
        unsigned int h
    cdef int VPX_CODEC_OK
    cdef int VPX_DECODER_ABI_VERSION

    vpx_codec_err_t vpx_codec_dec_init_ver(vpx_codec_ctx_t *ctx, vpx_codec_iface_t *iface,
                                            vpx_codec_dec_cfg_t *cfg, vpx_codec_flags_t flags, int ver)

    vpx_codec_err_t vpx_codec_decode(vpx_codec_ctx_t *ctx, const uint8_t *data,
                                     unsigned int data_sz, void *user_priv, long deadline) nogil

    vpx_image_t *vpx_codec_get_frame(vpx_codec_ctx_t *ctx, vpx_codec_iter_t *citer) nogil


#https://groups.google.com/a/webmproject.org/forum/?fromgroups#!msg/webm-discuss/f5Rmi-Cu63k/IXIzwVoXt_wJ
#"RGB is not supported.  You need to convert your source to YUV, and then compress that."
COLORSPACES : Dict[str, Sequence[str]] = {
    "vp8"   : ("YUV420P", ),
    "vp9"   : ("YUV420P", "YUV422P", "YUV444P", "YUV420P10"),
}
CODECS = tuple(COLORSPACES.keys())


def get_abi_version() -> int:
    return VPX_DECODER_ABI_VERSION


def get_version() -> Sequence[int]:
    b = vpx_codec_version_str()
    vstr = b.decode("latin1").lstrip("v")
    log("vpx_codec_version_str()=%s", vstr)
    vparts : List[int] = []
    try:
        for x in vstr.split("."):
            vparts.append(int(x))
    except Exception:
        pass
    return tuple(vparts)


def get_type() -> str:
    return "vpx"


def get_encodings() -> Sequence[str]:
    return CODECS


def get_min_size(encoding:str) -> Tuple[int, int]:
    return 16, 16


def get_specs() -> Sequence[VideoSpec]:
    specs: Sequence[VideoSpec] = []
    for encoding, in_css in COLORSPACES.items():
        for colorspace in in_css:
            specs.append(VideoSpec(
                    encoding=encoding, input_colorspace=colorspace, output_colorspaces=(colorspace, ),
                    has_lossless_mode=encoding == "vp9" and colorspace == "YUV444P",
                    codec_class=Decoder, codec_type=get_type(),
                    quality=50, speed=50,
                    size_efficiency=60,
                    setup_cost=20,
                    max_w=8192,
                    max_h=4096,
                )
            )
    return specs


def get_info() -> Dict[str, Any]:
    global CODECS
    info = {
        "version"       : get_version(),
        "encodings"     : CODECS,
        "abi_version"   : get_abi_version(),
        "build_config"  : vpx_codec_build_config(),
    }
    for k,v in COLORSPACES.items():
        info["%s.colorspaces" % k] = v
    return info


cdef inline const vpx_codec_iface_t  *make_codec_dx(encoding):
    if encoding=="vp8":
        return vpx_codec_vp8_dx()
    if encoding=="vp9":
        return vpx_codec_vp9_dx()
    raise ValueError(f"unsupported encoding: {encoding!r}")


cdef inline vpx_img_fmt_t get_vpx_colorspace(colorspace) noexcept:
    if colorspace == "YUV422P":
        return VPX_IMG_FMT_I422
    if colorspace == "YUV444P":
        return VPX_IMG_FMT_I444
    if colorspace == "YUV420P10":
        return VPX_IMG_FMT_I42016
    return VPX_IMG_FMT_I420


cdef class Decoder:

    cdef vpx_codec_ctx_t *context
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned int max_threads
    cdef unsigned long frames
    cdef vpx_img_fmt_t pixfmt
    cdef object dst_format
    cdef object encoding
    cdef int full_range
    cdef object file

    cdef object __weakref__

    def init_context(self, encoding: str, width: int, height: int, colorspace: str, options: typedict) -> None:
        log("vpx decoder init_context%s", (encoding, width, height, colorspace))
        assert encoding in CODECS, f"invalid encoding {encoding!r}"
        assert colorspace in COLORSPACES[encoding], f"invalid colorspace {colorspace!r} for encoding {encoding!r}"
        check_image_size(width, height, f"{encoding} decoder")
        cdef int flags = 0
        cdef const vpx_codec_iface_t *codec_iface = make_codec_dx(encoding)
        self.encoding = encoding
        self.dst_format = colorspace
        self.pixfmt = get_vpx_colorspace(self.dst_format)
        # modern mode omits steady-state full-range=True, so missing metadata defaults to
        # full-range until the bitstream or an explicit option says otherwise.
        self.full_range = True
        self.width = width
        self.height = height
        try:
            #no point having too many threads if the height is small, also avoids a warning:
            self.max_threads = max(0, min(int(VPX_THREADS), roundup(height, 32)//32*2))
        except:
            self.max_threads = 1
        self.context = <vpx_codec_ctx_t *> malloc(sizeof(vpx_codec_ctx_t))
        assert self.context!=NULL
        memset(self.context, 0, sizeof(vpx_codec_ctx_t))
        cdef vpx_codec_dec_cfg_t dec_cfg
        dec_cfg.w = width
        dec_cfg.h = height
        dec_cfg.threads = self.max_threads
        if vpx_codec_dec_init_ver(self.context, codec_iface, &dec_cfg,
                              flags, VPX_DECODER_ABI_VERSION)!=VPX_CODEC_OK:
            raise RuntimeError("failed to instantiate %s decoder with ABI version %s: %s" % (encoding, VPX_DECODER_ABI_VERSION, self.codec_error_str()))
        if SAVE_TO_FILE:
            filename = f"./{SAVE_TO_FILE}-{monotonic()}.{self.encoding}"
            self.file = open(filename, "wb")
            log.info("saving %s stream to %s", self.encoding, filename)
        log("vpx_codec_dec_init_ver for %s succeeded with ABI version %s", encoding, VPX_DECODER_ABI_VERSION)

    def __repr__(self):
        return "vpx.Decoder(%s)" % self.encoding

    def get_info(self) -> Dict[str, Any]:
        return {
            "type"      : self.get_type(),
            "width"     : self.get_width(),
            "height"    : self.get_height(),
            "encoding"  : self.encoding,
            "frames"    : int(self.frames),
            "colorspace": self.get_colorspace(),
            "max_threads" : self.max_threads,
        }

    def get_colorspace(self) -> str:
        return self.dst_format

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return self.context==NULL

    def get_encoding(self) -> str:
        return self.encoding

    def get_type(self) -> str:
        return "vpx"

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        if self.context!=NULL:
            vpx_codec_destroy(self.context)
            self.context = NULL
        self.width = 0
        self.height = 0
        self.max_threads = 0
        self.pixfmt = 0
        self.dst_format = ""
        self.encoding = ""
        f = self.file
        if f:
            self.file = None
            f.close()

    def decompress_image(self, data: SizedBuffer, options: typedict) -> ImageWrapper:
        cdef vpx_codec_iter_t citer = NULL
        cdef MemBuf output_buf
        cdef void *output
        cdef Py_ssize_t plane_len
        cdef uint8_t dy
        cdef unsigned int height
        cdef int stride
        assert self.context!=NULL

        cdef double start = monotonic()
        cdef vpx_codec_err_t ret = -1
        cdef uint8_t* src
        cdef Py_ssize_t src_len
        with buffer_context(data) as bc:
            src = <uint8_t*> (<uintptr_t> int(bc))
            src_len = len(bc)
            with nogil:
                ret = vpx_codec_decode(self.context, src, src_len, NULL, 0)
        if ret!=VPX_CODEC_OK:
            log.error("Error: vpx_codec_decode: %s", self.codec_error_str())
            return None
        cdef vpx_image_t *img
        with nogil:
            img = vpx_codec_get_frame(self.context, &citer)
        if img==NULL:
            log.error("Error: vpx_codec_get_frame: %s", self.codec_error_str())
            return None
        # the planes are allocated by libvpx for the dimensions found in the bitstream,
        # but we copy `self.height` lines out of them below - so a stream declaring
        # a smaller frame than we were initialized with would make us read out of bounds:
        if img.d_w < self.width or img.d_h < self.height:
            log.error("Error: %s image is too small: %ix%i, expected at least %ix%i",
                      self.encoding, img.d_w, img.d_h, self.width, self.height)
            return None
        if img.fmt != self.pixfmt:
            expected = self.dst_format
            if img.fmt == VPX_IMG_FMT_I444:
                self.dst_format = "YUV444P"
            elif img.fmt == VPX_IMG_FMT_I422:
                self.dst_format = "YUV422P"
            elif img.fmt == VPX_IMG_FMT_I420:
                self.dst_format = "YUV420P"
            elif img.fmt == VPX_IMG_FMT_I42016:
                self.dst_format = "YUV420P10"
            else:
                raise RuntimeError("unexpected image pixel format %s" % img.fmt)
            log.warn(f"Warning: expected {expected} but got {self.dst_format}")
        strides = []
        pixels = []
        divs = get_subsampling_divs(self.get_colorspace())
        cdef int i
        for i in range(3):
            _, dy = divs[i]
            if dy==1:
                height = self.height
            elif dy==2:
                height = (self.height+1)>>1
            else:
                raise ValueError(f"invalid height divisor {dy} for {self.get_colorspace()}")
            stride = img.stride[i]
            if stride <= 0 or stride > MAX_IMAGE_DIMENSION * 4:
                raise ValueError(f"invalid stride {stride} for plane {i}")
            strides.append(stride)

            plane_len = <Py_ssize_t> height * stride
            #add one extra line of padding:
            output_buf = padbuf(plane_len, stride, 0)
            output = <void *>output_buf.get_mem()
            memcpy(output, <void *>img.planes[i], plane_len)
            memset(<void *>((<char *>output)+plane_len), 0, stride)

            pixels.append(memoryview(output_buf))
        cdef double elapsed = 1000*(monotonic()-start)
        self.frames += 1
        log("%s frame %4i decoded in %3ims, colorspace=%s, format=%s",
            self.encoding, self.frames, elapsed, VPX_COLOR_SPACES.get(img.cs, img.cs), self.dst_format)
        # vp9 signals the colour range in the bitstream (color_config), but vp8 has no
        # range syntax - so for vp8 we reuse the range from an earlier frame's options;
        # the client option always takes precedence when present:
        if "full-range" in options:
            self.full_range = options.boolget("full-range")
        elif self.encoding == "vp9":
            self.full_range = bool(img.range == VPX_CR_FULL_RANGE)
        # 10-bit samples are stored in 16-bit containers (2 bytes per sample):
        cdef int bytesperpixel = 2 if self.dst_format.endswith("P10") else 1
        cdef int depth = 30 if bytesperpixel == 2 else 24
        return ImageWrapper(0, 0, self.width, self.height, pixels, self.get_colorspace(), depth, strides, bytesperpixel, ImageWrapper.PLANAR_3,
                            full_range=bool(self.full_range))

    def codec_error_str(self) -> str:
        return vpx_codec_error(self.context).decode("latin1")


def selftest(full=False) -> None:
    global CODECS
    from xpra.codecs.checks import testdecoder
    from xpra.codecs.vpx import decoder
    CODECS = testdecoder(decoder, full)
