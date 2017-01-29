# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("decoder", "jpeg")

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.buffers.membuf cimport getbuf, MemBuf

from libc.stdint cimport uint8_t, uint32_t, uintptr_t


ctypedef int boolean
ctypedef unsigned int JDIMENSION


cdef extern from "stdlib.h":
    void free(void *ptr)
    void* malloc(size_t size)

ctypedef int TJSAMP
ctypedef int TJPF
ctypedef int TJCS

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

    TJCS    TJCS_RGB
    TJCS    TJCS_YCbCr
    TJCS    TJCS_GRAY
    TJCS    TJCS_CMYK
    TJCS    TJCS_YCCK

    int TJFLAG_BOTTOMUP
    int TJFLAG_FASTUPSAMPLE
    int TJFLAG_FASTUPSAMPLE
    int TJFLAG_FASTDCT
    int TJFLAG_ACCURATEDCT

    ctypedef void* tjhandle
    tjhandle tjInitDecompress()
    int tjDecompressHeader3(tjhandle handle,
                            const unsigned char *jpegBuf, unsigned long jpegSize, int *width,
                            int *height, int *jpegSubsamp, int *jpegColorspace)
    int tjDecompress2(tjhandle handle,
                      const unsigned char *jpegBuf, unsigned long jpegSize, unsigned char *dstBuf,
                      int width, int pitch, int height, int pixelFormat, int flags) nogil
    int tjDecompressToYUVPlanes(tjhandle handle,
                                const unsigned char *jpegBuf, unsigned long jpegSize,
                                unsigned char **dstPlanes, int width, int *strides, int height, int flags) nogil
    int tjDestroy(tjhandle handle)
    char* tjGetErrorStr()

    unsigned long tjBufSizeYUV2(int width, int pad, int height, int subsamp)
    unsigned long tjPlaneSizeYUV(int componentID, int width, int stride, int height, int subsamp)
    int tjPlaneWidth(int componentID, int width, int subsamp)
    int tjPlaneHeight(int componentID, int height, int subsamp)


cdef extern from "../../buffers/buffers.h":
    int object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)


TJSAMP_STR = {
    TJSAMP_444  : "444",
    TJSAMP_422  : "422",
    TJSAMP_420  : "420",
    TJSAMP_GRAY : "GRAY",
    TJSAMP_440  : "440",
    TJSAMP_411  : "411",
    }

TJCS_STR = {
    TJCS_RGB    : "RGB",
    TJCS_YCbCr  : "YCbCr",
    TJCS_GRAY   : "GRAY",
    TJCS_CMYK   : "CMYK",
    TJCS_YCCK   : "YCCK",
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

def decompress(data, int width, int height, options={}):
    cdef const uint8_t *buf
    cdef Py_ssize_t buf_len
    assert object_as_buffer(data, <const void**> &buf, &buf_len)==0, "unable to convert %s to a buffer" % type(data)

    cdef tjhandle decompressor = tjInitDecompress()
    if decompressor==NULL:
        log.error("Error: failed to instantiate a JPEG decompressor")
        return None

    cdef int r, w, h, subsamp, cs
    r = tjDecompressHeader3(decompressor,
                            <const unsigned char *> buf, buf_len,
                            &w, &h, &subsamp, &cs)
    if r:
        log.error("Error: failed to decompress JPEG header")
        log.error(" %s", get_error_str())
        return None
    assert w==width and h==height, "invalid picture dimensions: %ix%i, expected %ix%i" % (w, h, width, height)
    subsamp_str = "YUV%sP" % TJSAMP_STR.get(subsamp, subsamp)
    assert subsamp in (TJSAMP_444, TJSAMP_422, TJSAMP_420), "unsupported JPEG colour subsampling: %s" % subsamp_str
    log("decompress: size=%ix%i, subsampling=%s, colorspace=%s", w, h, subsamp_str, TJCS_STR.get(cs, cs))
    #allocate YUV buffers:
    cdef unsigned long plane_sizes[3]
    cdef unsigned char *planes[3]
    cdef int strides[3]
    cdef int i, stride
    cdef MemBuf membuf
    pystrides = []
    pyplanes = []
    for i in range(3):
        strides[i] = roundup(w, 4)
        plane_sizes[i] = tjPlaneSizeYUV(i, w, strides[i], h, subsamp)
        membuf = getbuf(plane_sizes[i])     #add padding?
        planes[i] = <unsigned char*> membuf.get_mem()
        #python objects for each plane:
        pystrides.append(strides[i])
        pyplanes.append(memoryview(membuf))
    log("jpeg strides: %s, plane sizes=%s", pystrides, [int(plane_sizes[i]) for i in range(3)])
    cdef int flags = 0      #TJFLAG_BOTTOMUP
    r = tjDecompressToYUVPlanes(decompressor,
                                buf, buf_len, 
                                planes, width, strides, height, flags)
    if r:
        log.error("Error: failed to decompress JPEG data")
        log.error(" %s", get_error_str())
        return None
    return ImageWrapper(0, 0, w, h, pyplanes, subsamp_str, 24, pystrides, ImageWrapper._3_PLANES)

def selftest(full=False):
    try:
        log("jpeg selftest")
        import binascii
        data = binascii.unhexlify("ffd8ffe000104a46494600010101004800480000fffe00134372656174656420776974682047494d50ffdb0043000302020302020303030304030304050805050404050a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141514ffdb00430103040405040509050509140d0b0d1414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414ffc20011080010001003011100021101031101ffc4001500010100000000000000000000000000000008ffc40014010100000000000000000000000000000000ffda000c03010002100310000001aa4007ffc40014100100000000000000000000000000000020ffda00080101000105021fffc40014110100000000000000000000000000000020ffda0008010301013f011fffc40014110100000000000000000000000000000020ffda0008010201013f011fffc40014100100000000000000000000000000000020ffda0008010100063f021fffc40014100100000000000000000000000000000020ffda0008010100013f211fffda000c03010002000300000010924fffc40014110100000000000000000000000000000020ffda0008010301013f101fffc40014110100000000000000000000000000000020ffda0008010201013f101fffc40014100100000000000000000000000000000020ffda0008010100013f101fffd9")
        img = decompress(data, 16, 16)
        log("decompress(%i bytes)=%s", len(data), img)
        if full:
            try:
                v = decompress(data[:len(data)//2], 16, 16)
                assert v is not None
            except:
                pass
            else:
                raise Exception("should not be able to decompress incomplete data, but got %s" % v)
    finally:
        pass
