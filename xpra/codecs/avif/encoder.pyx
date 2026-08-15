# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Tuple, Dict, Any, Set
from collections.abc import Sequence

from libc.stdint cimport uint8_t, uintptr_t    # pylint: disable=syntax-error
from libc.string cimport memset  # pylint: disable=syntax-error
from xpra.buffers.membuf cimport buffer_context
from xpra.codecs.avif.avif cimport (
    AVIF_RESULT_OK, AVIF_RESULT,
    AVIF_VERSION_MAJOR, AVIF_VERSION_MINOR, AVIF_VERSION_PATCH,
    AVIF_QUANTIZER_LOSSLESS, AVIF_QUANTIZER_BEST_QUALITY, AVIF_QUANTIZER_WORST_QUALITY,
    AVIF_RANGE_LIMITED, AVIF_RANGE_FULL,
    AVIF_MATRIX_COEFFICIENTS_IDENTITY,
    avifResult,
    avifRWData,
    AVIF_PIXEL_FORMAT_NONE, AVIF_PIXEL_FORMAT_YUV400,
    AVIF_PIXEL_FORMAT_YUV444, AVIF_PIXEL_FORMAT_YUV422, AVIF_PIXEL_FORMAT_YUV420,
    avifImage, avifRGBImage, avifImageCreate, avifImageDestroy,
    AVIF_RGB_FORMAT_BGRA, AVIF_RGB_FORMAT_BGR,
    AVIF_RGB_FORMAT_RGBA, AVIF_RGB_FORMAT_RGB,
    AVIF_RGB_FORMAT_ARGB, AVIF_RGB_FORMAT_ABGR,
    AVIF_CHROMA_UPSAMPLING_FASTEST,
    AVIF_ADD_IMAGE_FLAG_SINGLE,
    AVIF_CODEC_CHOICE_AUTO, AVIF_CODEC_FLAG_CAN_ENCODE,
    avifEncoder, avifEncoderCreate, avifEncoderAddImage, avifEncoderFinish, avifEncoderDestroy,
    avifEncoderSetCodecSpecificOption,
    avifCodecName,
    avifRWDataFree,
    avifImageRGBToYUV,
    avifRGBImageSetDefaults,
    avifResultToString,
)

from xpra.codecs.constants import is_screen_content
from xpra.util.env import envint
from xpra.util.objects import typedict
from xpra.net.compression import Compressed
from xpra.codecs.image import ImageWrapper
from xpra.codecs.debug import may_save_image
from xpra.log import Logger
log = Logger("encoder", "avif")

THREADS = envint("XPRA_AVIF_THREADS", min(4, max(1, os.cpu_count()//2)))
DEF AVIF_PLANE_COUNT_YUV = 3

# libavif can be built against more than one AV1 encoder (aom, rav1e, svt..)
# and the codec specific options we use below are spelled the `libaom` way:
cdef const char *encoder_name = avifCodecName(AVIF_CODEC_CHOICE_AUTO, AVIF_CODEC_FLAG_CAN_ENCODE)
AV1_ENCODER: str = encoder_name.decode("latin1") if encoder_name!=NULL else ""


def get_type() -> str:
    return "avif"


def get_encodings() -> Sequence[str]:
    return ("avif", )


def get_version() -> Tuple[int, int, int]:
    return AVIF_VERSION_MAJOR, AVIF_VERSION_MINOR, AVIF_VERSION_PATCH


def get_info() -> Dict[str, Any]:
    return {
        "version"       : get_version(),
        "encodings"     : get_encodings(),
        "av1-encoder"   : AV1_ENCODER,
    }


AVIF_PIXEL_FORMAT: Dict[int, str] = {
    AVIF_PIXEL_FORMAT_NONE      : "NONE",
    AVIF_PIXEL_FORMAT_YUV444    : "YUV444",
    AVIF_PIXEL_FORMAT_YUV422    : "YUV422",
    AVIF_PIXEL_FORMAT_YUV420    : "YUV420",
    AVIF_PIXEL_FORMAT_YUV400    : "YUV400",
}

INPUT_PIXEL_FORMATS: Dict[str, int] = {
    "RGBX"  : AVIF_RGB_FORMAT_RGBA,
    "RGBA"  : AVIF_RGB_FORMAT_RGBA,
    "BGRX"  : AVIF_RGB_FORMAT_BGRA,
    "BGRA"  : AVIF_RGB_FORMAT_BGRA,
    "RGB"   : AVIF_RGB_FORMAT_RGB,
    "BGR"   : AVIF_RGB_FORMAT_BGR,
    "ARGB"  : AVIF_RGB_FORMAT_ARGB,
    "ABGR"  : AVIF_RGB_FORMAT_ABGR,
}


cdef inline void check(avifResult r, message: str):
    if r != AVIF_RESULT_OK:
        err = avifResultToString(r).decode("latin1") or AVIF_RESULT.get(r, r)
        raise RuntimeError("%s : %s" % (message, err))


REFUSED: Set[str] = set()


cdef void set_option(avifEncoder *encoder, key: str, value: str):
    #these are advisory: an encoder that does not know the option must not cost us the image
    cdef avifResult r = avifEncoderSetCodecSpecificOption(encoder, key.encode("latin1"), value.encode("latin1"))
    log("avifEncoderSetCodecSpecificOption(%s, %s)=%i", key, value, r)
    if r != AVIF_RESULT_OK and key not in REFUSED:
        #once is enough: this is a property of the encoder we are linked against
        REFUSED.add(key)
        log.warn("Warning: %r encoder refused %r=%r", AV1_ENCODER, key, value)


cdef void configure_content(avifEncoder *encoder, content_types: Sequence[str]):
    if not is_screen_content(content_types) or AV1_ENCODER != "aom":
        return
    #`tune-content=screen` is what enables the screen content tools in the sequence header,
    #and without it `enable-palette` does nothing at all.
    #Palette mode is worth 29% (syntax highlighted code), 29% (a terminal), 23% (a desktop)
    #and 33% (a browser window) at equal quality, and 4 to 8% on the lossless path,
    #but it costs 5% on a photograph - so this is strictly a screen content setting:
    set_option(encoder, "tune-content", "screen")
    #the same switch also turns on intra block copy, which we do not want:
    #it did not win a single block on any of the test images (the byte counts are identical
    #with and without it) and it doubles the time spent searching:
    set_option(encoder, "enable-intrabc", "0")


def encode(coding: str, image: ImageWrapper, options=None) -> Tuple:
    assert coding == "avif"
    options = typedict(options or {})
    pixel_format = image.get_pixel_format()
    if pixel_format not in INPUT_PIXEL_FORMATS:
        raise ValueError("invalid input format: %s" % pixel_format)
    pixels = image.get_pixels()
    cdef uint8_t grayscale = options.boolget("grayscale", False)
    cdef uint8_t alpha = pixel_format.find("A")>=0
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    cdef avifImage *avif_image = avifImageCreate(width, height, 8, AVIF_PIXEL_FORMAT_YUV444)
    if avif_image==NULL:
        raise RuntimeError("failed to allocate avif image")
    cdef avifRGBImage rgb
    memset(&rgb, 0, sizeof(avifRGBImage))

    avifRGBImageSetDefaults(&rgb, avif_image)
    rgb.format = INPUT_PIXEL_FORMATS.get(pixel_format)
    rgb.chromaUpsampling = AVIF_CHROMA_UPSAMPLING_FASTEST
    rgb.ignoreAlpha = not alpha
    rgb.alphaPremultiplied = alpha
    rgb.rowBytes = image.get_rowstride()

    cdef avifResult r
    cdef avifEncoder * encoder = NULL
    cdef avifRWData avifOutput
    memset(&avifOutput, 0, sizeof(avifRWData))

    cdef int speed = options.intget("speed", 50)
    cdef int quality = options.intget("quality", 50)
    cdef uint8_t lossless = quality >= 100
    content_types = options.strtupleget("content-types", ())
    cdef uint8_t screen_content = is_screen_content(content_types)
    qrange = 20
    # map quality (0..100) to a base quantizer (0=best .. 63=worst), then allow the
    # rate controller a band of `qrange` worse to save bits on easy frames:
    cdef int minq = max(AVIF_QUANTIZER_BEST_QUALITY, AVIF_QUANTIZER_WORST_QUALITY * (100 - quality) // 100)
    cdef int maxq = min(AVIF_QUANTIZER_WORST_QUALITY, minq + qrange)
    client_options = {"quality" : quality}

    with buffer_context(pixels) as bc:
        # libavif reads `rowBytes * height` bytes from the buffer, so check it is
        # that big rather than trusting the image metadata to describe it:
        if len(bc) < <Py_ssize_t> rgb.rowBytes * height:
            avifImageDestroy(avif_image)
            raise ValueError("pixel buffer is too small: %i bytes, %i needed for %ix%i at rowstride %i" % (
                len(bc), rgb.rowBytes * height, width, height, rgb.rowBytes))
        rgb.pixels = <uint8_t*> (<uintptr_t> int(bc))
        log("avif.encode(%s, %s, %s) pixels=%#x", coding, image, options, int(bc))
        try:
            if lossless:
                # bit-exact round-trip: full range and lossless quantizer, no subsampling:
                avif_image.yuvRange = AVIF_RANGE_FULL
                minq = maxq = AVIF_QUANTIZER_LOSSLESS
                if grayscale:
                    avif_image.yuvFormat = AVIF_PIXEL_FORMAT_YUV400
                    client_options["subsampling"] = "YUV400"
                else:
                    # identity matrix encodes the R/G/B channels directly with no YCbCr
                    # transform - this requires 4:4:4:
                    avif_image.matrixCoefficients = AVIF_MATRIX_COEFFICIENTS_IDENTITY
                    avif_image.yuvFormat = AVIF_PIXEL_FORMAT_YUV444
                    client_options["subsampling"] = "YUV444"
            else:
                if image.get_full_range():
                    avif_image.yuvRange = AVIF_RANGE_FULL
                else:
                    avif_image.yuvRange = AVIF_RANGE_LIMITED
                if grayscale:
                    avif_image.yuvFormat = AVIF_PIXEL_FORMAT_YUV400
                    client_options["subsampling"] = "YUV400"
                elif screen_content or quality>80:
                    #chroma subsampling is a bad deal for screen content (as with jpeg):
                    #measured on the sharp edges of the source, `444` is worth 13 to 18%
                    #at equal quality, and spending those bits on `quality` instead
                    #buys back much less - coloured text is what suffers most
                    avif_image.yuvFormat = AVIF_PIXEL_FORMAT_YUV444
                    client_options["subsampling"] = "YUV444"
                elif quality>50:
                    avif_image.yuvFormat = AVIF_PIXEL_FORMAT_YUV422
                    client_options["subsampling"] = "YUV422"
                else:
                    avif_image.yuvFormat = AVIF_PIXEL_FORMAT_YUV420
                    client_options["subsampling"] = "YUV420"
            r = avifImageRGBToYUV(avif_image, &rgb)
            log("avifImageRGBToYUV()=%i for %s", r, AVIF_PIXEL_FORMAT.get(avif_image.yuvFormat))
            check(r, "Failed to convert to YUV(A)")

            encoder = avifEncoderCreate()
            log("avifEncoderCreate()=%#x", <uintptr_t> encoder)
            if encoder==NULL:
                raise RuntimeError("failed to create avif encoder")
            # Configure your encoder here (see avif/avif.h):
            encoder.speed = 9+int(speed>=50)
            encoder.maxThreads = THREADS
            encoder.minQuantizer = minq
            encoder.maxQuantizer = maxq
            configure_content(encoder, content_types)
            if alpha>0:
                #we need this client side to know if we can use planar gl paint:
                client_options["alpha"] = alpha
                encoder.minQuantizerAlpha = minq
                encoder.maxQuantizerAlpha = maxq
            # * tileRowsLog2
            # * tileColsLog2
            # * keyframeInterval
            # * timescale
            r = avifEncoderAddImage(encoder, avif_image, 1, AVIF_ADD_IMAGE_FLAG_SINGLE)
            log("avifEncoderAddImage()=%i", r)
            check(r, "Failed to add image to encoder")

            r = avifEncoderFinish(encoder, &avifOutput)
            log("avifEncoderFinish()=%i", r)
            check(r, "Failed to finish encode")

            cdata = avifOutput.data[:avifOutput.size]
            log("avif: got %i bytes", avifOutput.size)
            may_save_image("avif", cdata)
            return "avif", Compressed("avif", cdata), client_options, width, height, 0, len(pixel_format.replace("A", ""))*8
        finally:
            avifImageDestroy(avif_image)
            if encoder:
                avifEncoderDestroy(encoder)
            avifRWDataFree(&avifOutput)


def selftest(full=False) -> None:
    #fake empty buffer:
    from xpra.util.str_fn import hexstr
    from xpra.codecs.checks import make_test_image
    w, h = (32, 32)
    for has_alpha in (True, False):
        rgb_format = "BGR%s" % ["X", "A"][has_alpha]
        img = make_test_image(rgb_format, w, h)
        for grayscale in (False, True):
            # quality=100 exercises the lossless path (YUV444 identity, or YUV400 when grayscale):
            for q in (10, 50, 90, 100):
                r = encode("avif", img, {"quality" : q, "speed" : 50, "alpha" : has_alpha, "grayscale" : grayscale})
                assert len(r)>0
                log(f"avif {rgb_format} grayscale={grayscale} @ {q}%%: " + hexstr(r[1].data))
