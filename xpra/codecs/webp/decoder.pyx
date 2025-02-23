# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict, Tuple
from collections.abc import Sequence

from xpra.log import Logger
log = Logger("encoder", "webp")

from xpra.util.env import envbool
from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.codecs.debug import may_save_image
from xpra.buffers.membuf cimport memalign, buffer_context

from xpra.codecs.argb.argb cimport show_plane_range
from libc.stdint cimport uint8_t, uint32_t, uintptr_t
from libc.stdlib cimport free

DEF ALIGN = 4

cdef uint8_t SHOW_PLANE_RANGES = envbool("XPRA_SHOW_PLANE_RANGES", False)


cdef extern from *:
    ctypedef unsigned long size_t

cdef extern from "Python.h":
    object PyMemoryView_FromMemory(char *mem, Py_ssize_t size, int flags)
    int PyBUF_WRITE

cdef extern from "webp/decode.h":

    int WebPGetDecoderVersion()

    ctypedef int VP8StatusCode
    VP8StatusCode VP8_STATUS_OK
    VP8StatusCode VP8_STATUS_OUT_OF_MEMORY
    VP8StatusCode VP8_STATUS_INVALID_PARAM
    VP8StatusCode VP8_STATUS_BITSTREAM_ERROR
    VP8StatusCode VP8_STATUS_UNSUPPORTED_FEATURE
    VP8StatusCode VP8_STATUS_SUSPENDED
    VP8StatusCode VP8_STATUS_USER_ABORT
    VP8StatusCode VP8_STATUS_NOT_ENOUGH_DATA

    ctypedef int WEBP_CSP_MODE
    WEBP_CSP_MODE MODE_RGB
    WEBP_CSP_MODE MODE_RGBA
    WEBP_CSP_MODE MODE_BGR
    WEBP_CSP_MODE MODE_BGRA
    WEBP_CSP_MODE MODE_ARGB
    WEBP_CSP_MODE MODE_RGBA_4444
    WEBP_CSP_MODE MODE_RGB_565
    #RGB-premultiplied transparent modes (alpha value is preserved)
    WEBP_CSP_MODE MODE_rgbA
    WEBP_CSP_MODE MODE_bgrA
    WEBP_CSP_MODE MODE_Argb
    WEBP_CSP_MODE MODE_rgbA_4444
    #YUV modes must come after RGB ones.
    WEBP_CSP_MODE MODE_YUV
    WEBP_CSP_MODE MODE_YUVA                       #yuv 4:2:0


    ctypedef struct WebPDecoderOptions:
        int bypass_filtering            #if true, skip the in-loop filtering
        int no_fancy_upsampling         #if true, use faster pointwise upsampler
        int use_cropping                #if true, cropping is applied _first_
        int crop_left
        int crop_top                    #top-left position for cropping.
                                        #Will be snapped to even values.
        int crop_width
        int crop_height                 #dimension of the cropping area
        int use_scaling                 #if true, scaling is applied _afterward_
        int scaled_width, scaled_height #final resolution
        int use_threads                 #if true, use multi-threaded decoding

        int force_rotation              #forced rotation (to be applied _last_)
        int no_enhancement              #if true, discard enhancement layer
        uint32_t pad[6]                 #padding for later use

    ctypedef struct WebPBitstreamFeatures:
        int width                       #Width in pixels, as read from the bitstream.
        int height                      #Height in pixels, as read from the bitstream.
        int has_alpha                   #True if the bitstream contains an alpha channel.
        int has_animation               #True if the bitstream is an animation.
        #Unused for now:
        int format
        uint32_t pad[5]                 #padding for later use

    ctypedef struct WebPRGBABuffer:     #view as RGBA
        uint8_t* rgba                   #pointer to RGBA samples
        int stride                      #stride in bytes from one scanline to the next.
        size_t size                     #total size of the *rgba buffer.

    ctypedef struct WebPYUVABuffer:     #view as YUVA
        uint8_t* y                      #pointer to luma
        uint8_t* u                      #pointer to chroma U
        uint8_t* v                      #pointer to chroma V
        uint8_t* a                      #pointer to alpha samples
        int y_stride                    #luma stride
        int u_stride, v_stride          #chroma strides
        int a_stride                    #alpha stride
        size_t y_size                   #luma plane size
        size_t u_size, v_size           #chroma planes size
        size_t a_size                   #alpha-plane size

    ctypedef struct u:
        WebPRGBABuffer RGBA
        WebPYUVABuffer YUVA

    ctypedef struct WebPDecBuffer:
        WEBP_CSP_MODE colorspace        #Colorspace.
        int width, height               #Dimensions.
        int is_external_memory          #If true, 'internal_memory' pointer is not used.
        u u
        uint32_t       pad[4]           #padding for later use
        uint8_t* private_memory         #Internally allocated memory (only when
                                        #is_external_memory is false). Should not be used
                                        #externally, but accessed via the buffer union.

    ctypedef struct WebPDecoderConfig:
        WebPBitstreamFeatures input     #Immutable bitstream features (optional)
        WebPDecBuffer output            #Output buffer (can point to external mem)
        WebPDecoderOptions options      #Decoding options


    VP8StatusCode WebPGetFeatures(const uint8_t* data, size_t data_size,
                                  WebPBitstreamFeatures* features)

    int WebPInitDecoderConfig(WebPDecoderConfig* config)
    VP8StatusCode WebPDecode(const uint8_t* data, size_t data_size,
                                      WebPDecoderConfig* config) nogil
    void WebPFreeDecBuffer(WebPDecBuffer* buffer)


ERROR_TO_NAME: Dict[int, str] = {
#VP8_STATUS_OK
    VP8_STATUS_OUT_OF_MEMORY        : "out of memory",
    VP8_STATUS_INVALID_PARAM        : "invalid parameter",
    VP8_STATUS_BITSTREAM_ERROR      : "bitstream error",
    VP8_STATUS_UNSUPPORTED_FEATURE  : "unsupported feature",
    VP8_STATUS_SUSPENDED            : "suspended",
    VP8_STATUS_USER_ABORT           : "user abort",
    VP8_STATUS_NOT_ENOUGH_DATA      : "not enough data",
}


def get_version() -> Tuple[int, int, int]:
    cdef int version = WebPGetDecoderVersion()
    log("WebPGetDecoderVersion()=%#x", version)
    return (version >> 16) & 0xff, (version >> 8) & 0xff, version & 0xff


def get_info() -> Dict[str, Any]:
    return  {
        "version"      : get_version(),
        "encodings"    : get_encodings(),
    }


cdef inline void webp_check(int ret):
    if ret==0:
        return
    err = ERROR_TO_NAME.get(ret, ret)
    raise RuntimeError("error: %s" % err)


def get_encodings() -> Sequence[str]:
    return ("webp", )


cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)


def decompress_to_rgb(data: bytes, options: typedict) -> ImageWrapper:
    cdef int has_alpha = options.boolget("has_alpha", False)
    rgb_format = options.strget("rgb_format", "BGRA" if has_alpha else "BGRX")
    if rgb_format not in ("RGBX", "RGBA", "BGRA", "BGRX", "RGB", "BGR"):
        raise ValueError(f"unsupported rgb format {rgb_format!r}")
    cdef WebPDecoderConfig config
    config.options.use_threads = 1
    WebPInitDecoderConfig(&config)
    webp_check(WebPGetFeatures(data, len(data), &config.input))
    log("webp decompress_to_rgb found features: width=%4i, height=%4i, has_alpha=%-5s, input rgb_format=%s",
        config.input.width, config.input.height, bool(config.input.has_alpha), rgb_format)

    config.output.colorspace = MODE_BGRA
    cdef int stride = 4 * config.input.width
    cdef size_t size = stride * config.input.height
    #allocate the buffer:
    cdef uint8_t *buf = <uint8_t*> memalign(size + stride)      #add one line of padding
    config.output.u.RGBA.rgba   = buf
    config.output.u.RGBA.stride = stride
    config.output.u.RGBA.size   = size
    config.output.is_external_memory = 1

    cdef VP8StatusCode ret = 0
    cdef size_t data_len
    cdef const uint8_t* data_buf
    with buffer_context(data) as bc:
        data_len = len(bc)
        data_buf = <const uint8_t*> (<uintptr_t> int(bc))
        with nogil:
            ret = WebPDecode(data_buf, data_len, &config)
    webp_check(ret)
    #we use external memory, so this is not needed:
    #WebPFreeDecBuffer(&config.output)
    may_save_image("webp", data)
    out_format = rgb_format
    if len(rgb_format) == 3:    # ie: "RGB", "BGR"
        out_format = out_format + "X"
    assert len(out_format) == 4
    if not has_alpha or not config.input.has_alpha:
        out_format = out_format.replace("A", "X")
    pixels = PyMemoryView_FromMemory(<char *> buf, size, PyBUF_WRITE)
    img = WebpImageWrapper(
        0, 0, config.input.width, config.input.height, pixels, out_format,
        len(out_format) * 8, stride,
    )
    img.cython_buffer = <uintptr_t> buf
    return img


class WebpImageWrapper(ImageWrapper):

    def _cn(self):
        return "WebpImageWrapper"

    def free(self) -> None:
        cdef uintptr_t buf = self.cython_buffer
        self.cython_buffer = 0
        log("WebpImageWrapper.free() cython_buffer=%#x", buf)
        super().free()
        if buf!=0:
            free(<void *> buf)


def decompress_to_yuv(data: bytes, options: typedict) -> WebpImageWrapper:
    """
        This returns a WebpBufferWrapper, you MUST call free() on it
        once the pixel buffer can be freed.
    """
    cdef WebPDecoderConfig config
    config.options.use_threads = 1
    WebPInitDecoderConfig(&config)
    webp_check(WebPGetFeatures(data, len(data), &config.input))
    log("webp decompress_to_yuv found features: width=%4i, height=%4i, has_alpha=%-5s", config.input.width, config.input.height, bool(config.input.has_alpha))

    config.output.colorspace = MODE_YUV
    cdef int has_alpha = options.boolget("has_alpha", False)
    cdef int alpha = has_alpha and config.input.has_alpha
    if alpha:
        log.warn("Warning: webp YUVA colorspace not supported yet")
        alpha = 0
        #config.output.colorspace = MODE_YUVA

    cdef int w = config.input.width
    cdef int h = config.input.height
    cdef WebPYUVABuffer *YUVA = &config.output.u.YUVA
    YUVA.y_stride = roundup(w, ALIGN)
    YUVA.u_stride = roundup((w+1)//2, ALIGN)
    YUVA.v_stride = roundup((w+1)//2, ALIGN)
    if alpha:
        YUVA.a_stride = w
    else:
        YUVA.a_stride = 0
    cdef size_t y_size = YUVA.y_stride * h
    cdef size_t u_size = YUVA.u_stride * ((h+1)//2)
    cdef size_t v_size = YUVA.v_stride * ((h+1)//2)
    cdef size_t a_size = YUVA.a_stride * h
    YUVA.y_size = y_size
    YUVA.u_size = u_size
    YUVA.v_size = v_size
    YUVA.a_size = a_size
    #allocate a buffer big enough for all planes with 1 stride of padding after each:
    cdef uint8_t *buf = <uint8_t*> memalign(y_size + u_size + v_size + a_size + YUVA.y_stride + YUVA.u_stride + YUVA.v_stride + YUVA.a_stride)
    YUVA.y = buf
    YUVA.u = <uint8_t*> (<uintptr_t> buf + y_size + YUVA.y_stride)
    YUVA.v = <uint8_t*> (<uintptr_t> buf + y_size + YUVA.y_stride + u_size + YUVA.u_stride)
    if alpha:
        YUVA.a = <uint8_t*> (<uintptr_t> buf + y_size + YUVA.y_stride + u_size + YUVA.u_stride + v_size + YUVA.v_stride)
        strides = (YUVA.y_stride, YUVA.u_stride, YUVA.v_stride, YUVA.a_stride)
    else:
        YUVA.a = NULL
        strides = (YUVA.y_stride, YUVA.u_stride, YUVA.v_stride)
    config.output.is_external_memory = 1
    log("WebPDecode: image size %ix%i : buffer=%#x, strides=%s",
        w, h, <uintptr_t> buf, strides)
    cdef VP8StatusCode ret = 0
    cdef size_t data_len
    cdef const uint8_t* data_buf
    with buffer_context(data) as bc:
        data_len = len(bc)
        data_buf = <const uint8_t*> (<uintptr_t> int(bc))
        with nogil:
            ret = WebPDecode(data_buf, data_len, &config)
    webp_check(ret)
    if alpha:
        planes = (
            PyMemoryView_FromMemory(<char *> YUVA.y, y_size, PyBUF_WRITE),
            PyMemoryView_FromMemory(<char *> YUVA.u, u_size, PyBUF_WRITE),
            PyMemoryView_FromMemory(<char *> YUVA.v, v_size, PyBUF_WRITE),
            PyMemoryView_FromMemory(<char *> YUVA.a, a_size, PyBUF_WRITE),
        )
    else:
        planes = (
            PyMemoryView_FromMemory(<char *> YUVA.y, y_size, PyBUF_WRITE),
            PyMemoryView_FromMemory(<char *> YUVA.u, u_size, PyBUF_WRITE),
            PyMemoryView_FromMemory(<char *> YUVA.v, v_size, PyBUF_WRITE),
        )
    if SHOW_PLANE_RANGES:
        for i in range(3):
            # YUV420P
            ydiv = xdiv = 2 if i > 1 else 1
            show_plane_range("YUV"[i], planes[i], w // xdiv, strides[i], h // ydiv)

    img = WebpImageWrapper(0, 0, w, h, planes, "YUV420P", (3+alpha)*8, strides, 3+alpha, ImageWrapper.PLANAR_3+alpha)
    img.set_full_range(False)
    img.cython_buffer = <uintptr_t> buf
    return img


def selftest(full=False) -> None:
    from xpra.codecs.checks import TEST_PICTURES   # pylint: disable=import-outside-toplevel
    for size, samples in TEST_PICTURES["webp"].items():
        w, h = size
        for bdata, options in samples:
            alpha = typedict(options).boolget("has_alpha")
            img = decompress_to_rgb(bdata, typedict(options))
            iw = img.get_width()
            ih = img.get_height()
            pf = img.get_pixel_format()
            got_alpha = pf.find("A") >= 0
            assert iw==w and ih==h, f"expected {w}x{h} but got {iw}x{ih}"
            if not alpha:
                assert not got_alpha, f"expected {alpha=}, got {pf}"
            assert len(img.get_pixels())>0
            img.free()

            img = decompress_to_yuv(bdata, typedict())
            assert img.get_width()==w and img.get_height()==h and (img.get_pixel_format() == "YUV420P")
            assert len(img.get_pixels())>0
            img.free()
            #print("compressed data(%s)=%s" % (has_alpha, binascii.hexlify(r)))
