# This file is part of Xpra.
# Copyright (C) 2017-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False
from time import monotonic

from xpra.log import Logger
log = Logger("decoder", "jpeg")

from xpra.util import envbool, reverse_dict
from xpra.codecs.image_wrapper import ImageWrapper
from libc.stdint cimport uintptr_t
from xpra.buffers.membuf cimport getbuf, MemBuf #pylint: disable=syntax-error
from libc.string cimport memset #pylint: disable=syntax-error

from libc.stdint cimport uint8_t

LOG_PERF = envbool("XPRA_JPEG_LOG_PERF", False)

ctypedef int TJSAMP
ctypedef int TJPF
ctypedef int TJCS

cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS

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

    int tjPlaneWidth(int componentID, int width, int subsamp)
    unsigned long tjBufSizeYUV2(int width, int pad, int height, int subsamp)
    unsigned long tjPlaneSizeYUV(int componentID, int width, int stride, int height, int subsamp)
    int tjPlaneWidth(int componentID, int width, int subsamp)
    int tjPlaneHeight(int componentID, int height, int subsamp)


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

TJPF_STR = {
    TJPF_RGB    : "RGB",
    TJPF_BGR    : "BGR",
    TJPF_RGBX   : "RGBX",
    TJPF_BGRX   : "BGRX",
    TJPF_XBGR   : "XBGR",
    TJPF_XRGB   : "XRGB",
    TJPF_GRAY   : "GRAY",
    TJPF_RGBA   : "RGBA",
    TJPF_BGRA   : "BGRA",
    TJPF_ABGR   : "ABGR",
    TJPF_ARGB   : "ARGB",
    TJPF_CMYK   : "CMYK",
    }
TJPF_VAL = reverse_dict(TJPF_STR)


def get_version():
    return (1, 0)

def get_encodings():
    return ("jpeg", "jpega")


cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)


def get_error_str():
    cdef char *err = tjGetErrorStr()
    return str(err)

def decompress_to_yuv(data, unsigned char nplanes=3):
    cdef tjhandle decompressor = tjInitDecompress()
    if decompressor==NULL:
        raise Exception("failed to instantiate a JPEG decompressor")

    cdef Py_buffer py_buf
    if PyObject_GetBuffer(data, &py_buf, PyBUF_ANY_CONTIGUOUS):
        tjDestroy(decompressor)
        raise Exception("failed to read compressed data from %s" % type(data))

    cdef int r
    def close():
        PyBuffer_Release(&py_buf)
        r = tjDestroy(decompressor)
        if r:
            log.error("Error: failed to destroy the JPEG decompressor, code %i:", r)
            log.error(" %s", get_error_str())

    cdef int w, h, subsamp, cs
    r = tjDecompressHeader3(decompressor,
                            <const unsigned char *> py_buf.buf, py_buf.len,
                            &w, &h, &subsamp, &cs)
    if r:
        err = get_error_str()
        close()
        raise Exception("failed to decompress JPEG header: %s" % err)

    subsamp_str = TJSAMP_STR.get(subsamp, subsamp)
    assert subsamp in (TJSAMP_444, TJSAMP_422, TJSAMP_420, TJSAMP_GRAY), "unsupported JPEG colour subsampling: %s" % subsamp_str
    log("jpeg.decompress_to_yuv size: %4ix%-4i, subsampling=%-4s, colorspace=%s",
        w, h, subsamp_str, TJCS_STR.get(cs, cs))
    if nplanes==3:
        pixel_format = "YUV%sP" % subsamp_str
    elif nplanes==1:
        pixel_format = "YUV400P"
    else:
        close()
        raise ValueError("invalid number of planes: %i" % nplanes)
    #allocate YUV buffers:
    cdef unsigned long plane_size
    cdef unsigned char *planes[3]
    cdef int strides[3]
    cdef int i, stride
    cdef MemBuf membuf
    cdef MemBuf empty
    cdef int flags = 0
    pystrides = []
    pyplanes = []
    cdef unsigned long total_size = 0
    cdef double start, elapsed
    for i in range(3):
        strides[i] = 0
        planes[i] = NULL
    try:
        for i in range(nplanes):
            stride = tjPlaneWidth(i, w, subsamp)
            if stride<=0:
                if subsamp!=TJSAMP_GRAY or i==0:
                    raise ValueError("cannot get size for plane %r for mode %r" % ("YUV"[i], subsamp_str))
                stride = roundup(w//2, 4)
                plane_size = stride * roundup(h, 2)//2
                if i==1:
                    #allocate empty U and V planes:
                    empty = getbuf(plane_size)
                    memset(<void *> empty.get_mem(), 128, plane_size)
                    pixel_format = "YUV420P"
                membuf = empty
            else:
                stride = roundup(stride, 4)
                strides[i] = stride
                plane_size = tjPlaneSizeYUV(i, w, stride, h, subsamp)
                membuf = getbuf(plane_size)     #add padding?
                planes[i] = <unsigned char*> membuf.get_mem()
            total_size += plane_size
            #python objects for each plane:
            pystrides.append(stride)
            pyplanes.append(memoryview(membuf))
        #log("jpeg strides: %s, plane sizes=%s", pystrides, [int(plane_sizes[i]) for i in range(3)])
        start = monotonic()
        with nogil:
            r = tjDecompressToYUVPlanes(decompressor,
                                        <const unsigned char*> py_buf.buf, py_buf.len,
                                        planes, w, strides, h, flags)
        if r:
            raise Exception("failed to decompress %s JPEG data to YUV: %s" % (subsamp_str, get_error_str()))
    finally:
        close()
    if LOG_PERF:
        elapsed = monotonic()-start
        log("decompress jpeg to %s: %4i MB/s (%9i bytes in %2.1fms)",
            pixel_format, total_size/elapsed//1024//1024, total_size, 1000*elapsed)
    return ImageWrapper(0, 0, w, h, pyplanes, pixel_format, 24, pystrides, ImageWrapper.PLANAR_3)


def decompress_to_rgb(rgb_format, data, unsigned long alpha_offset=0):
    assert rgb_format in TJPF_VAL
    cdef TJPF pixel_format = TJPF_VAL[rgb_format]

    cdef tjhandle decompressor = tjInitDecompress()
    if decompressor==NULL:
        raise Exception("failed to instantiate a JPEG decompressor")

    cdef Py_buffer py_buf
    if PyObject_GetBuffer(data, &py_buf, PyBUF_ANY_CONTIGUOUS):
        tjDestroy(decompressor)
        raise Exception("failed to read compressed data from %s" % type(data))

    cdef int r
    def close():
        PyBuffer_Release(&py_buf)
        r = tjDestroy(decompressor)
        if r:
            log.error("Error: failed to destroy the JPEG decompressor, code %i:", r)
            log.error(" %s", get_error_str())

    cdef int w, h, subsamp, cs
    cdef uintptr_t buf = <uintptr_t> py_buf.buf
    cdef unsigned long buf_size = py_buf.len
    if alpha_offset>0:
        buf_size = alpha_offset
    log("decompressing buffer at %#x of size %i", buf, buf_size)
    r = tjDecompressHeader3(decompressor,
                            <const unsigned char *> buf, buf_size,
                            &w, &h, &subsamp, &cs)
    if r:
        err = get_error_str()
        close()
        raise Exception("failed to decompress JPEG header: %s" % err)
    subsamp_str = TJSAMP_STR.get(subsamp, subsamp)
    log("jpeg.decompress_to_rgb: size=%4ix%-4i, subsampling=%3s, colorspace=%s",
        w, h, subsamp_str, TJCS_STR.get(cs, cs))
    cdef int flags = 0      #TJFLAG_BOTTOMUP
    cdef double elapsed
    #TODO: add padding and rounding?
    cdef double start = monotonic()
    cdef int stride = w*4
    cdef unsigned long size = stride*h
    cdef MemBuf membuf = getbuf(size)
    cdef unsigned char *dst_buf = <unsigned char*> membuf.get_mem()
    with nogil:
        r = tjDecompress2(decompressor,
                          <const unsigned char *> buf, buf_size, dst_buf,
                          w, stride, h, pixel_format, flags)
    if r:
        close()
        raise Exception("failed to decompress %s JPEG data to %s: %s" % (subsamp_str, rgb_format, get_error_str()))
    #deal with alpha channel if there is one:
    cdef int aw, ah
    cdef unsigned char *planes[3]
    cdef int strides[3]
    cdef MemBuf alpha
    cdef unsigned long alpha_size
    cdef int x, y, alpha_stride
    cdef unsigned char* alpha_plane
    cdef char alpha_index
    if alpha_offset:
        alpha_index = rgb_format.find("A")
        assert alpha_index>=0, "no 'A' in %s" % rgb_format
        assert len(rgb_format)==4, "unsupported rgb format for alpha: %s" % rgb_format
        assert <unsigned long> py_buf.len>alpha_offset, "alpha offset is beyond the end of the compressed buffer"
        buf = (<uintptr_t> py_buf.buf) + alpha_offset
        buf_len = py_buf.len - alpha_offset
        r = tjDecompressHeader3(decompressor,
                                <const unsigned char *> buf, buf_len,
                                &aw, &ah, &subsamp, &cs)
        assert aw==w and ah==h, "alpha plane dimensions %ix%i don't match main image %ix%i" % (
            aw, ah, w, h)
        subsamp_str = TJSAMP_STR.get(subsamp, subsamp)
        log("found alpha plane %r at %#x size %i", subsamp_str, buf, buf_len)
        assert subsamp==TJSAMP_GRAY, "unsupported JPEG alpha subsampling: %s" % subsamp_str
        for i in range(3):
            strides[i] = 0
            planes[i] = NULL
        alpha_stride = tjPlaneWidth(0, w, subsamp)
        strides[0] = alpha_stride
        alpha_size = tjPlaneSizeYUV(0, w, alpha_stride, h, subsamp)
        alpha = getbuf(alpha_size)
        alpha_plane = <unsigned char*> alpha.get_mem()
        planes[0] = alpha_plane
        with nogil:
            r = tjDecompressToYUVPlanes(decompressor,
                                        <const unsigned char*> buf, buf_len,
                                        planes, w, strides, h, flags)
        if r:
            close()
            raise Exception("failed to decompress %s JPEG alpha data: %s" % (subsamp_str, get_error_str()))
        #merge alpha into rgb buffer:
        for y in range(h):
            for x in range(w):
                dst_buf[y*stride+x*4+alpha_index] = alpha_plane[y*alpha_stride+x]
    close()
    if LOG_PERF:
        elapsed = monotonic()-start
        log("decompress jpeg to %s: %4i MB/s (%9i bytes in %2.1fms)",
            rgb_format, size/elapsed//1024//1024, size, 1000*elapsed)
    return ImageWrapper(0, 0, w, h, memoryview(membuf), rgb_format, 24, stride, ImageWrapper.PACKED)


def selftest(full=False):
    try:
        log("jpeg selftest")
        import binascii
        data = binascii.unhexlify("ffd8ffe000104a46494600010101004800480000fffe00134372656174656420776974682047494d50ffdb0043000302020302020303030304030304050805050404050a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141514ffdb00430103040405040509050509140d0b0d1414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414ffc20011080010001003011100021101031101ffc4001500010100000000000000000000000000000008ffc40014010100000000000000000000000000000000ffda000c03010002100310000001aa4007ffc40014100100000000000000000000000000000020ffda00080101000105021fffc40014110100000000000000000000000000000020ffda0008010301013f011fffc40014110100000000000000000000000000000020ffda0008010201013f011fffc40014100100000000000000000000000000000020ffda0008010100063f021fffc40014100100000000000000000000000000000020ffda0008010100013f211fffda000c03010002000300000010924fffc40014110100000000000000000000000000000020ffda0008010301013f101fffc40014110100000000000000000000000000000020ffda0008010201013f101fffc40014100100000000000000000000000000000020ffda0008010100013f101fffd9")
        def test_rgbx(*args):
            return decompress_to_rgb("RGBX", *args)
        for fn in (decompress_to_yuv, test_rgbx):
            img = fn(data)
            log("%s(%i bytes)=%s", fn, len(data), img)
            if full:
                try:
                    v = decompress_to_yuv(data[:len(data)//2])
                    assert v is not None
                except:
                    pass
                else:
                    raise Exception("should not be able to decompress incomplete data, but got %s" % v)
    finally:
        pass
