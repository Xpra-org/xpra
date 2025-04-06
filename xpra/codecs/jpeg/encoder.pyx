# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from typing import Any, Dict, Tuple
from collections.abc import Sequence
from time import monotonic

from libc.stdint cimport uintptr_t
from xpra.codecs.image import ImageWrapper
from xpra.buffers.membuf cimport makebuf, MemBuf, buffer_context     # pylint: disable=syntax-error
from xpra.codecs.constants import get_subsampling_divs
from xpra.codecs.constants import VideoSpec
from xpra.codecs.debug import may_save_image
from xpra.net.compression import Compressed
from xpra.util.env import envbool
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.log import Logger
log = Logger("encoder", "jpeg")

cdef int YUV = envbool("XPRA_TURBOJPEG_YUV", True)


ctypedef int TJSAMP
ctypedef int TJPF

cdef extern from "math.h":
    double sqrt(double arg) nogil
    double round(double arg) nogil

cdef extern from "turbojpeg.h":
    TJSAMP  TJSAMP_444
    TJSAMP  TJSAMP_422
    TJSAMP  TJSAMP_420
    TJSAMP  TJSAMP_GRAY
    TJSAMP  TJSAMP_440
    TJSAMP  TJSAMP_411

    TJPF    TJPF_RGB
    TJPF    TJPF_BGR
    TJPF    TJPF_RGBX
    TJPF    TJPF_BGRX
    TJPF    TJPF_XBGR
    TJPF    TJPF_XRGB
    TJPF    TJPF_GRAY
    TJPF    TJPF_RGBA
    TJPF    TJPF_BGRA
    TJPF    TJPF_ABGR
    TJPF    TJPF_ARGB
    TJPF    TJPF_CMYK

    int TJFLAG_BOTTOMUP
    int TJFLAG_FASTUPSAMPLE
    int TJFLAG_FASTDCT
    int TJFLAG_ACCURATEDCT

    ctypedef void* tjhandle
    tjhandle tjInitCompress()
    int tjDestroy(tjhandle handle)
    char* tjGetErrorStr()
    #unsigned long tjBufSize(int width, int height, int jpegSubsamp)
    int tjCompress2(tjhandle handle, const unsigned char *srcBuf,
                    int width, int pitch, int height, int pixelFormat, unsigned char **jpegBuf,
                    unsigned long *jpegSize, int jpegSubsamp, int jpegQual, int flags) nogil

    int tjCompressFromYUVPlanes(tjhandle handle,
                    const unsigned char **srcPlanes,
                    int width, const int *strides,
                    int height, int subsamp,
                    unsigned char **jpegBuf,
                    unsigned long *jpegSize, int jpegQual,
                    int flags) nogil

TJPF_VAL: Dict[str, int] = {
    "RGB"   : TJPF_RGB,
    "BGR"   : TJPF_BGR,
    "RGBX"  : TJPF_RGBX,
    "BGRX"  : TJPF_BGRX,
    "XBGR"  : TJPF_XBGR,
    "XRGB"  : TJPF_XRGB,
    "GRAY"  : TJPF_GRAY,
    "RGBA"  : TJPF_RGBA,
    "BGRA"  : TJPF_BGRA,
    "ABGR"  : TJPF_ABGR,
    "ARGB"  : TJPF_ARGB,
    "CMYK"  : TJPF_CMYK,
}
TJSAMP_STR: Dict[int, str] = {
    TJSAMP_444  : "444",
    TJSAMP_422  : "422",
    TJSAMP_420  : "420",
    TJSAMP_GRAY : "GRAY",
    TJSAMP_440  : "440",
    TJSAMP_411  : "411",
}


def get_version() -> Tuple[int, int]:
    return (2, 0)


def get_type() -> str:
    return "jpeg"


def get_info() -> Dict[str, Any]:
    return {"version"   : get_version()}


def get_encodings() -> Sequence[str]:
    return ("jpeg", "jpega")


if YUV:
    JPEG_INPUT_COLORSPACES = ("BGRX", "RGBX", "XBGR", "XRGB", "RGB", "BGR", "YUV420P", "YUV422P", "YUV444P")
else:
    JPEG_INPUT_COLORSPACES = ("BGRX", "RGBX", "XBGR", "XRGB", "RGB", "BGR")
JPEGA_INPUT_COLORSPACES = ("BGRA", "RGBA", )


def get_specs() -> Sequence[VideoSpec]:
    specs: Sequence[VideoSpec] = []
    for encoding in ("jpeg", "jpega"):
        in_css = JPEG_INPUT_COLORSPACES if encoding == "jpeg" else JPEGA_INPUT_COLORSPACES

        for in_cs in in_css:
            width_mask=0xFFFF
            height_mask=0xFFFF
            if in_cs in ("YUV420P", "YUV422P"):
                width_mask=0xFFFE
            if in_cs in ("YUV420P", ):
                height_mask=0xFFFE

            specs.append(VideoSpec(
                    encoding=encoding, input_colorspace=in_cs, output_colorspaces=(in_cs, ),
                    has_lossless_mode=False,
                    codec_class=Encoder, codec_type="jpeg",
                    setup_cost=0, cpu_cost=100, gpu_cost=0,
                    min_w=16, min_h=16, max_w=16*1024, max_h=16*1024,
                    can_scale=False,
                    score_boost=-50,
                    width_mask=width_mask, height_mask=height_mask,
                )
            )
    return specs


cdef inline int norm_quality(int quality) nogil:
    if quality<=0:
        return 0
    if quality>=100:
        return 100
    return <int> round(sqrt(<double> quality)*10)


cdef class Encoder:
    cdef tjhandle compressor
    cdef int width
    cdef int height
    cdef object encoding
    cdef object src_format
    cdef int quality
    cdef int grayscale
    cdef long frames
    cdef object __weakref__

    def __init__(self):
        self.width = self.height = self.quality = self.frames = 0
        self.compressor = tjInitCompress()
        if self.compressor == NULL:
            raise RuntimeError("Error: failed to instantiate a JPEG compressor")

    def init_context(self, encoding: str, width : int, height : int, src_format: str, options: typedict) -> None:
        assert encoding in ("jpeg", "jpega"), "invalid encoding: %s" % encoding
        if encoding == "jpeg":
            assert src_format in JPEG_INPUT_COLORSPACES
        elif encoding == "jpega":
            assert src_format in JPEGA_INPUT_COLORSPACES
        else:
            raise ValueError(f"invalid encoding {encoding!r}")
        scaled_width = options.intget("scaled-width", width)
        scaled_height = options.intget("scaled-height", height)
        assert scaled_width == width and scaled_height == height, "jpeg encoder does not handle scaling"
        self.encoding = encoding
        self.width = width
        self.height = height
        self.src_format = src_format
        self.grayscale = options.boolget("grayscale")
        self.quality = options.intget("quality", 50)

    def is_ready(self) -> bool:
        return self.compressor!=NULL

    def is_closed(self) -> bool:
        return self.compressor == NULL

    def clean(self) -> None:
        self.width = self.height = self.quality = 0
        if self.compressor:
            r = tjDestroy(self.compressor)
            self.compressor = NULL
            if r:
                log.error("Error: failed to destroy the JPEG compressor, code %i:", r)
                log.error(" %s", get_error_str())

    def get_encoding(self) -> str:
        return self.encoding

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "jpeg"

    def get_src_format(self) -> str:
        return self.src_format

    def get_info(self) -> Dict[str,Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "encoding"      : self.encoding,
            "width"         : self.width,
            "height"        : self.height,
            "quality"       : self.quality,
            "grayscale"     : bool(self.grayscale),
        }
        return info

    def compress_image(self, image: ImageWrapper, options: typedict) -> Tuple:
        quality = options.get("quality", -1)
        if quality>0:
            self.quality = quality
        else:
            quality = self.quality
        pfstr = image.get_pixel_format()
        if pfstr in ("YUV420P", "YUV422P", "YUV444P"):
            cdata = encode_yuv(self.compressor, image, quality, self.grayscale)
        else:
            cdata = encode_rgb(self.compressor, image, quality, self.grayscale)
        if not cdata:
            return None
        now = monotonic()
        may_save_image("jpeg", cdata, now)
        client_options = {
            "full-range": image.get_full_range(),
        }
        if self.encoding == "jpega":
            from xpra.codecs.argb.argb import alpha
            a = alpha(image)
            planes = (a, )
            rowstrides = (image.get_rowstride()//4, )
            adata = do_encode_yuv(self.compressor, "YUV400P", planes,
                                  self.width, self.height, rowstrides,
                                  quality, TJSAMP_GRAY)
            client_options["alpha-offset"] = len(cdata)
            may_save_image("jpeg", adata, now)
            cdata = memoryview(cdata).tobytes()+memoryview(adata).tobytes()
        self.frames += 1
        return memoryview(cdata), client_options


def get_error_str() -> str:
    err = tjGetErrorStr()
    try:
        return err.decode("latin1")
    except:
        return str(err)


JPEG_INPUT_FORMATS = ("RGB", "RGBX", "BGRX", "XBGR", "XRGB", )
JPEGA_INPUT_FORMATS = ("RGBA", "BGRA", "ABGR", "ARGB")


def encode(coding, image: ImageWrapper, options: typedict) -> Tuple:
    assert coding in ("jpeg", "jpega")
    rgb_format = image.get_pixel_format()
    if coding == "jpega" and rgb_format.find("A")<0:
        #why did we select 'jpega' then!?
        coding = "jpeg"
    cdef int quality = options.intget("quality", 50)
    cdef int grayscale = options.boolget("grayscale", False)
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    cdef int scaled_width = options.intget("scaled-width", width)
    cdef int scaled_height = options.intget("scaled-height", height)
    cdef char resize = scaled_width!=width or scaled_height!=height
    log("encode%s", (coding, image, options))
    input_formats = JPEG_INPUT_FORMATS if coding == "jpeg" else JPEGA_INPUT_FORMATS
    if rgb_format not in input_formats or resize and len(rgb_format)!=4:
        from xpra.codecs.argb.argb import argb_swap
        if not argb_swap(image, input_formats):
            log("jpeg: argb_swap failed to convert %s to a suitable format: %s" % (
                rgb_format, input_formats))
        log("jpeg converted %s to %s", rgb_format, image)

    if resize:
        from xpra.codecs.argb.scale import scale_image
        image = scale_image(image, scaled_width, scaled_height)
        log("jpeg scaled image: %s", image)

    client_options = {
        "quality"   : quality
    }
    cdef tjhandle compressor = tjInitCompress()
    if compressor == NULL:
        log.error("Error: failed to instantiate a JPEG compressor")
        return ()
    cdef int r
    try:
        cdata = encode_rgb(compressor, image, quality, grayscale)
        if not cdata:
            return None
        now = monotonic()
        may_save_image("jpeg", cdata, now)
        bpp = 24
        if coding == "jpega":
            from xpra.codecs.argb.argb import alpha
            a = alpha(image)
            planes = (a, )
            rowstrides = (image.get_rowstride()//4, )
            adata = do_encode_yuv(compressor, "YUV400P", planes,
                                  width, height, rowstrides,
                                  quality, TJSAMP_GRAY)
            may_save_image("jpeg", adata, now)
            client_options["alpha-offset"] = len(cdata)
            cdata = memoryview(cdata).tobytes()+memoryview(adata).tobytes()
            bpp = 32
        return coding, Compressed(coding, memoryview(cdata), False), client_options, width, height, 0, bpp
    finally:
        r = tjDestroy(compressor)
        if r:
            log.error("Error: failed to destroy the JPEG compressor, code %i:", r)
            log.error(" %s", get_error_str())


cdef inline TJSAMP get_subsamp(int quality):
    if quality<60:
        return TJSAMP_420
    elif quality<80:
        return TJSAMP_422
    return TJSAMP_444


cdef object encode_rgb(tjhandle compressor, image, int quality, int grayscale=0):
    pfstr = image.get_pixel_format()
    pf = TJPF_VAL.get(pfstr)
    if pf is None:
        raise ValueError(f"invalid pixel format {pfstr!r}")
    cdef TJPF tjpf = pf
    cdef TJSAMP subsamp
    if grayscale:
        subsamp = TJSAMP_GRAY
    else:
        subsamp = get_subsamp(quality)
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    cdef int stride = image.get_rowstride()
    pixels = image.get_pixels()
    return do_encode_rgb(compressor, pfstr, pixels,
                         width, height, stride,
                         quality, tjpf, subsamp)


cdef object do_encode_rgb(tjhandle compressor, pfstr, pixels,
                   int width, int height, int stride,
                   int quality, TJPF tjpf, TJSAMP subsamp):
    cdef int flags = 0
    cdef unsigned char *out = NULL
    cdef unsigned long out_size = 0
    cdef int r = -1
    cdef const unsigned char *src
    log("jpeg.encode_rgb with subsampling=%s for pixel format=%s with quality=%s",
        TJSAMP_STR.get(subsamp, subsamp), pfstr, quality)
    with buffer_context(pixels) as bc:
        assert len(bc)>=stride*height, "%s buffer is too small: %i bytes, %ix%i=%i bytes required" % (
            pfstr, len(bc), stride, height, stride*height)
        src = <const unsigned char *> (<uintptr_t> int(bc))
        if src == NULL:
            raise ValueError("missing pixel buffer address from context %s" % bc)
        with nogil:
            r = tjCompress2(compressor, src,
                            width, stride, height, tjpf,
                            &out, &out_size, subsamp, norm_quality(quality), flags)
    if r!=0:
        log.error("Error: failed to compress jpeg image, code %i:", r)
        log.error(" %s", get_error_str())
        log.error(" width=%i, stride=%i, height=%i", width, stride, height)
        log.error(" quality=%i (from %i), flags=%x", norm_quality(quality), quality, flags)
        log.error(" pixel format=%s", pfstr)
        return None
    assert out_size>0 and out!=NULL, "jpeg compression produced no data"
    log("output is %s bytes", out_size)
    return makebuf(out, out_size, 0)


cdef object encode_yuv(tjhandle compressor, image, int quality, int grayscale=0):
    pfstr = image.get_pixel_format()
    assert pfstr in ("YUV420P", "YUV422P"), "invalid yuv pixel format %s" % pfstr
    cdef TJSAMP subsamp
    if grayscale:
        subsamp = TJSAMP_GRAY
    elif pfstr == "YUV420P":
        subsamp = TJSAMP_420
    elif pfstr == "YUV422P":
        subsamp = TJSAMP_422
    elif pfstr == "YUV444P":
        subsamp = TJSAMP_444
    else:
        raise ValueError("invalid yuv pixel format %s" % pfstr)
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    rowstrides = image.get_rowstride()
    planes = image.get_pixels()
    return do_encode_yuv(compressor, pfstr, planes,
                         width, height, rowstrides,
                         quality, subsamp)


cdef object do_encode_yuv(tjhandle compressor, pfstr, planes,
                   int width, int height, rowstrides,
                   int quality, TJSAMP subsamp):
    cdef int flags = 0
    cdef unsigned char *out = NULL
    cdef unsigned long out_size = 0
    cdef int r = -1
    cdef int strides[3]
    cdef const unsigned char *src[3]
    divs = get_subsampling_divs(pfstr)
    for i in range(3):
        src[i] = NULL
        strides[i] = 0
    for i, (xdiv, ydiv) in enumerate(divs):
        assert rowstrides[i]>=width//xdiv, "stride %i is too small for width %i of plane %s from %s" % (
            rowstrides[i], width//xdiv, "YUV"[i], pfstr)
        strides[i] = rowstrides[i]
    contexts = []
    try:
        for i, (xdiv, ydiv) in enumerate(divs):
            bc = buffer_context(planes[i])
            bc.__enter__()
            contexts.append(bc)
            if len(bc)<strides[i]*height//ydiv:
                raise ValueError("plane %r is only %i bytes, %ix%i=%i bytes required" % (
                "YUV"[i], len(bc), strides[i], height, strides[i]*height//ydiv))
            src[i] = <const unsigned char *> (<uintptr_t> int(bc))
            if src[i] == NULL:
                raise ValueError("missing plane %s from context %s" % ("YUV"[i], bc))
        log("jpeg.encode_yuv with subsampling=%s for pixel format=%s with quality=%s",
            TJSAMP_STR.get(subsamp, subsamp), pfstr, quality)
        with nogil:
            r = tjCompressFromYUVPlanes(compressor,
                                        src,
                                        width, <const int*> strides,
                                        height, subsamp,
                                        &out, &out_size, norm_quality(quality), flags)
        if r!=0:
            log.error("Error: failed to compress jpeg image, code %i:", r)
            log.error(" %s", get_error_str())
            log.error(" width=%i, strides=%s, height=%i", width, rowstrides, height)
            log.error(" quality=%i (from %i), flags=%x", norm_quality(quality), quality, flags)
            log.error(" pixel format=%s, subsampling=%s", pfstr, TJSAMP_STR.get(subsamp, subsamp))
            log.error(" planes: %s", csv(<uintptr_t> src[i] for i in range(3)))
            return None
    finally:
        for bc in contexts:
            bc.__exit__()
    assert out_size>0 and out!=NULL, "jpeg compression produced no data"
    return makebuf(out, out_size, 0)


def selftest(full=False) -> None:
    log("jpeg selftest")
    from xpra.codecs.checks import make_test_image
    for q in (0, 50, 100):
        for encoding in ("jpeg", "jpega"):
            img = make_test_image("BGRA", 32, 32)
            v = encode(encoding, img, typedict({"quality" : q}))
            assert v, "encode output was empty!"
            from xpra.util.str_fn import hexstr
