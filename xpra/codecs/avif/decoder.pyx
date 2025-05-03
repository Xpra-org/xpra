# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Tuple, Dict
from collections.abc import Sequence

from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper
from xpra.codecs.constants import get_subsampling_divs
from xpra.codecs.debug import may_save_image

from libc.string cimport memset  # pylint: disable=syntax-error
from xpra.buffers.membuf cimport getbuf, MemBuf  # pylint: disable=syntax-error
from xpra.codecs.avif.avif cimport (
    avifDecoder, avifResult, avifRGBImage, avifImage,
    avifResultToString,
    avifDecoderCreate, avifDecoderSetIOMemory,
    avifDecoderParse, avifDecoderNextImage, avifDecoderDestroy,
    avifDecoderNextImage, avifRGBImageSetDefaults, avifImageYUVToRGB,
    AVIF_RESULT, AVIF_RESULT_OK, AVIF_RGB_FORMAT_BGRA,
    AVIF_PIXEL_FORMAT_NONE, AVIF_PIXEL_FORMAT_YUV444, AVIF_PIXEL_FORMAT_YUV422,
    AVIF_PIXEL_FORMAT_YUV420, AVIF_PIXEL_FORMAT_YUV400,
    AVIF_RANGE_LIMITED, AVIF_RANGE_FULL,
    AVIF_VERSION_MAJOR, AVIF_VERSION_MINOR, AVIF_VERSION_PATCH,
    #AVIF_STRICT_ENABLED,
)
from xpra.buffers.membuf cimport memalign, buffer_context

from xpra.log import Logger
log = Logger("encoder", "avif")

from libc.stdint cimport uint8_t, uint32_t, uintptr_t
from libc.stdlib cimport free

cdef extern from *:
    ctypedef unsigned long size_t


AVIF_PIXEL_FORMAT: Dict[int, str] = {
    AVIF_PIXEL_FORMAT_NONE      : "NONE",
    AVIF_PIXEL_FORMAT_YUV444    : "YUV444",
    AVIF_PIXEL_FORMAT_YUV422    : "YUV422",
    AVIF_PIXEL_FORMAT_YUV420    : "YUV420",
    AVIF_PIXEL_FORMAT_YUV400    : "YUV400",
}

AVIF_RANGE: Dict[int, str] = {
    AVIF_RANGE_LIMITED  : "LIMITED",
    AVIF_RANGE_FULL     : "FULL",
}


def get_version() -> Tuple[int, int, int]:
    return (AVIF_VERSION_MAJOR, AVIF_VERSION_MINOR, AVIF_VERSION_PATCH)


def get_info() -> Dict:
    return {
        "version"      : get_version(),
        "encodings"    : get_encodings(),
    }


def get_encodings() -> Sequence[str]:
    return ("avif", )


cdef inline void check(avifResult r, message: str):
    if r != AVIF_RESULT_OK:
        err = avifResultToString(r).decode("latin1") or AVIF_RESULT.get(r, r)
        raise RuntimeError("%s : %s" % (message, err))


def decompress_to_yuv(data: bytes, options: typedict) -> ImageWrapper:
    return decompress(data, options, True)


def decompress(data: bytes, options: typedict, yuv=False) -> ImageWrapper:
    cdef avifRGBImage rgb
    memset(&rgb, 0, sizeof(avifRGBImage))
    cdef avifDecoder * decoder = avifDecoderCreate()
    if decoder==NULL:
        raise RuntimeError("failed to create avif decoder")
    decoder.ignoreExif = 1
    decoder.ignoreXMP = 1
    #decoder.imageSizeLimit = 4096*4096
    #decoder.imageCountLimit = 1
    #decoder.strictFlags = AVIF_STRICT_ENABLED
    cdef avifResult r
    cdef size_t data_len
    cdef const uint8_t* data_buf
    cdef uint32_t width, height, stride, ydiv, size
    cdef uint8_t bpp = 32
    cdef MemBuf pixels
    cdef avifImage *image = NULL
    try:
        with buffer_context(data) as bc:
            data_len = len(bc)
            data_buf = <const uint8_t*> (<uintptr_t> int(bc))
            r = avifDecoderSetIOMemory(decoder, data_buf, data_len)
            check(r, "Cannot set IO on avifDecoder")

            r = avifDecoderParse(decoder)
            check(r, "Failed to decode image")

            image = decoder.image
            # Now available:
            # * All decoder->image information other than pixel data:
            # * width, height, depth
            # * transformations (pasp, clap, irot, imir)
            # * color profile (icc, CICP)
            # * metadata (Exif, XMP)
            # * decoder->alphaPresent
            # * number of total images in the AVIF (decoder->imageCount)
            # * overall image sequence timing (including per-frame timing with avifDecoderNthImageTiming())
            width = image.width
            height = image.height
            r = avifDecoderNextImage(decoder)
            check(r, "failed to get next image")
            # Now available (for this frame):
            # * All decoder->image YUV pixel data (yuvFormat, yuvPlanes, yuvRange, yuvChromaSamplePosition, yuvRowBytes)
            log("avif parsed: %ux%u (%ubpc) yuvFormat=%s, yuvRange=%s",
                width, height, image.depth, AVIF_PIXEL_FORMAT.get(image.yuvFormat), AVIF_RANGE.get(image.yuvRange))
            if yuv:
                #do we still need to copy if image.imageOwnsYUVPlanes?
                #could we keep the decoder context alive until the image is freed instead?
                yuv_format = "%sP" % AVIF_PIXEL_FORMAT.get(image.yuvFormat) #ie: YUV420P
                divs = get_subsampling_divs(yuv_format)
                planes = []
                strides = []
                for i in range(3):
                    ydiv = divs[i][1]
                    size = image.yuvRowBytes[i]*height//ydiv
                    planes.append(image.yuvPlanes[i][:size])
                    strides.append(image.yuvRowBytes[i])
                return ImageWrapper(0, 0, width, height, planes, yuv_format, 24, strides, planes=ImageWrapper.PLANAR_3)

            # * decoder->image alpha data (alphaRange, alphaPlane, alphaRowBytes)
            # * this frame's sequence timing
            avifRGBImageSetDefaults(&rgb, image)
            # Override YUV(A)->RGB(A) defaults here: depth, format, chromaUpsampling, ignoreAlpha, alphaPremultiplied, libYUVUsage, etc
            rgb_format = "BGRA"
            if not decoder.alphaPresent:
                rgb.ignoreAlpha = 1
                rgb_format = "BGRX"
                bpp = 24
            rgb.format = AVIF_RGB_FORMAT_BGRA
            stride = width*4
            pixels = getbuf(width*4*height, 0)
            rgb.pixels = <uint8_t *> pixels.get_mem()
            rgb.rowBytes = stride
            rgb.alphaPremultiplied = 1
            r = avifImageYUVToRGB(image, &rgb)
            check(r, "Conversion from YUV failed")
            if rgb.depth>8:
                raise ValueError("cannot handle depth %s" % rgb.depth)
            may_save_image("avif", data)
            if decoder.imageCount>1:
                log.warn("Warning: more than one image in avif data")
            img = ImageWrapper(0, 0, width, height, memoryview(pixels), rgb_format, bpp, stride, planes=ImageWrapper.PACKED)
            img.set_full_range(image.yuvRange == AVIF_RANGE_FULL and options.boolget("full-range", True))
            return img
    finally:
        avifDecoderDestroy(decoder)


def selftest(full=False) -> None:
    from xpra.codecs.checks import TEST_PICTURES
    for size, samples in TEST_PICTURES["avif"].items():
        w, h = size
        for bdata, options in samples:
            img = decompress(bdata, typedict(options))
            assert img.get_width()==w and img.get_height()==h
            assert len(img.get_pixels())>0
            #print("compressed data(%s)=%s" % (has_alpha, binascii.hexlify(r)))
