# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False, wraparound=False, cdivision=True

from xpra.log import Logger
log = Logger("encoder", "jpeg")

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.buffers.membuf cimport makebuf, object_as_buffer
from xpra.net.compression import Compressed

from libc.stdint cimport uint8_t, uint32_t, uintptr_t


ctypedef int boolean
ctypedef unsigned int JDIMENSION
ctypedef int TJSAMP
ctypedef int TJPF
ctypedef int TJCS
ctypedef int TJXOP

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


TJPF_VAL = {
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
TJSAMP_STR = {
    TJSAMP_444  : "444",
    TJSAMP_422  : "422",
    TJSAMP_420  : "420",
    TJSAMP_GRAY : "GRAY",
    TJSAMP_440  : "440",
    TJSAMP_411  : "411",
    }


def get_version():
    return 1

def get_encodings():
    return ["jpeg"]


cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)


def get_error_str():
    cdef char *err = tjGetErrorStr()
    return str(err)

def encode(image, int quality=50, int speed=50, options={}):
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    cdef int stride = image.get_rowstride()
    cdef const unsigned char* buf
    cdef Py_ssize_t buf_len
    pixels = image.get_pixels()
    pfstr = image.get_pixel_format()
    assert object_as_buffer(pixels, <const void**> &buf, &buf_len)==0, "unable to convert %s to a buffer" % type(pixels)
    assert buf_len>=stride*height, "%s buffer is too small: %i bytes, %ix%i=%i bytes required" % (pfstr, buf_len, stride, height, stride*height)
    pf = TJPF_VAL.get(pfstr)
    if pf is None:
        raise Exception("invalid pixel format %s" % pfstr)
    cdef TJPF tjpf = pf
    cdef tjhandle compressor = tjInitCompress()
    if compressor==NULL:
        log.error("Error: failed to instantiate a JPEG compressor")
        return None
    cdef TJSAMP subsamp = TJSAMP_444
    if quality<80:
        if quality<50:
            subsamp = TJSAMP_420
        else:
            subsamp = TJSAMP_422
    cdef int flags = 0
    cdef unsigned char *out = NULL
    cdef unsigned long out_size = 0
    cdef int r
    log("jpeg: encode with subsampling=%s for pixel format=%s with quality=%s", TJSAMP_STR.get(subsamp, subsamp), pfstr, quality)
    try:
        with nogil:
            r = tjCompress2(compressor, buf,
                            width, stride, height, tjpf, &out,
                            &out_size, subsamp, quality, flags)
        if r!=0:
            log.error("Error: failed to compress jpeg image, code %i:", r)
            log.error(" %s", get_error_str())
            log.error(" width=%i, stride=%i, height=%i", width, stride, height)
            log.error(" pixel format=%s, quality=%i", pfstr, quality)
            return None
        assert out_size>0 and out!=NULL, "jpeg compression produced no data"
    finally:
        r = tjDestroy(compressor)
        if r:
            log.error("Error: failed to destroy the JPEG compressor, code %i:", r)
            log.error(" %s", get_error_str())
    cdata = makebuf(out, out_size)
    client_options = {}
    return "jpeg", Compressed("jpeg", memoryview(cdata), False), client_options, width, height, 0, 24


def selftest(full=False):
    log("jpeg selftest")
    from xpra.codecs.codec_checks import make_test_image
    img = make_test_image("BGRA", 32, 32)
    for q in (0, 50, 100):
        v = encode(img, q, 100)
        assert v, "encode output was empty!"
