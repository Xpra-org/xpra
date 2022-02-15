# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.codecs.codec_debug import may_save_image

from libc.string cimport memset #pylint: disable=syntax-error
from xpra.buffers.membuf cimport getbuf, MemBuf #pylint: disable=syntax-error
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

cdef extern from "Python.h":
    object PyMemoryView_FromMemory(char *mem, Py_ssize_t size, int flags)


AVIF_PIXEL_FORMAT = {
    AVIF_PIXEL_FORMAT_NONE      : "NONE",
    AVIF_PIXEL_FORMAT_YUV444    : "YUV444",
    AVIF_PIXEL_FORMAT_YUV422    : "YUV422",
    AVIF_PIXEL_FORMAT_YUV420    : "YUV420",
    AVIF_PIXEL_FORMAT_YUV400    : "YUV400",
    }

AVIF_RANGE = {
    AVIF_RANGE_LIMITED  : "LIMITED",
    AVIF_RANGE_FULL     : "FULL",
    }


def get_version():
    return (AVIF_VERSION_MAJOR, AVIF_VERSION_MINOR, AVIF_VERSION_PATCH)

def get_info():
    return  {
        "version"      : get_version(),
        "encodings"    : get_encodings(),
        }

def get_encodings():
    return ("avif", )


cdef check(avifResult r, message):
    if r != AVIF_RESULT_OK:
        err = avifResultToString(r).decode("latin1") or AVIF_RESULT.get(r, r)
        raise Exception("%s : %s" % (message, err))

def decompress(data, options=None, yuv=False):
    cdef avifRGBImage rgb
    memset(&rgb, 0, sizeof(avifRGBImage))
    cdef avifDecoder * decoder = avifDecoderCreate()
    if decoder==NULL:
        raise Exception("failed to create avif decoder")
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
                return ImageWrapper(0, 0, width, height, planes, yuv_format, 24, strides, ImageWrapper.PLANAR_3)

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
            pixels = getbuf(width*4*height)
            rgb.pixels = <uint8_t *> pixels.get_mem()
            rgb.rowBytes = stride
            if AVIF_VERSION_MAJOR>0 or AVIF_VERSION_MINOR>8:
                rgb.alphaPremultiplied = 1
            r = avifImageYUVToRGB(image, &rgb)
            check(r, "Conversion from YUV failed")
            if rgb.depth>8:
                raise Exception("cannot handle depth %s" % rgb.depth)
            may_save_image("avif", data)
            if decoder.imageCount>1:
                log.warn("Warning: more than one image in avif data")
            return ImageWrapper(0, 0, width, height, memoryview(pixels), rgb_format, bpp, stride, ImageWrapper.PACKED)
    finally:
        avifDecoderDestroy(decoder)



def selftest(full=False):
    w, h = 24, 16       #hard coded size of test data
    for has_alpha, hexdata in ((True, "00000020667479706176696600000000617669666d6966316d6961664d413141000001a16d657461000000000000002868646c720000000000000000706963740000000000000000000000006c696261766966000000000e7069746d0000000000010000002c696c6f630000000044000002000100000001000001de00000018000200000001000001c9000000150000004269696e660000000000020000001a696e6665020000000001000061763031436f6c6f72000000001a696e6665020000000002000061763031416c706861000000001a69726566000000000000000e6175786c000200010001000000d769707270000000b16970636f0000001469737065000000000000001800000010000000107069786900000000030808080000000c617631438120000000000013636f6c726e636c780002000200028000000014697370650000000000000018000000100000000e706978690000000001080000000c6176314381001c0000000038617578430000000075726e3a6d7065673a6d706567423a636963703a73797374656d733a617578696c696172793a616c706861000000001e69706d6100000000000000020001040102830400020405068708000000356d64617412000a051810efed2a320a1000c5c0e0651476f01c12000a053810efed12320d100000c79949a86935c2b90c40"),
                             (False, "00000020667479706176696600000000617669666d6966316d6961664d413141000000f26d657461000000000000002868646c720000000000000000706963740000000000000000000000006c696261766966000000000e7069746d0000000000010000001e696c6f6300000000440000010001000000010000011a000000180000002869696e660000000000010000001a696e6665020000000001000061763031436f6c6f72000000006a697072700000004b6970636f0000001469737065000000000000001800000010000000107069786900000000030808080000000c617631438120000000000013636f6c726e636c78000200020002800000001769706d61000000000000000100010401028304000000206d64617412000a053810efed12320d100000c5c030e847ff81dca0c0")):
        import binascii
        bdata = binascii.unhexlify(hexdata)
        img = decompress(bdata, {"alpha" : has_alpha})
        assert img.get_width()==w and img.get_height()==h
        assert len(img.get_pixels())>0
        #print("compressed data(%s)=%s" % (has_alpha, binascii.hexlify(r)))
