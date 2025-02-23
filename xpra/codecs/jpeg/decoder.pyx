# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False
from time import monotonic
from typing import Tuple, NoReturn

from xpra.log import Logger
log = Logger("decoder", "jpeg")

from xpra.util.env import envbool
from xpra.util.objects import reverse_dict, typedict
from xpra.codecs.image import ImageWrapper
from xpra.buffers.membuf cimport getbuf, MemBuf  # pylint: disable=syntax-error
from libc.stdint cimport uintptr_t, uint8_t
from libc.string cimport memset  # pylint: disable=syntax-error

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


def get_version() -> Tuple[int, int]:
    return (1, 0)


def get_encodings() -> Sequence[str]:
    return ("jpeg", "jpega")


cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)

DEF ALIGN = 4


def get_error_str() -> str:
    cdef char *err = tjGetErrorStr()
    return str(err)


cdef inline void close_handle(tjhandle handle):
    r = tjDestroy(handle)
    if r:
        log.error(f"Error: failed to destroy the JPEG decompressor, code {r}:")
        log.error(" %s", get_error_str())


def tj_err(int r, msg: str) -> NoReturn:
    err = get_error_str()
    raise RuntimeError(f"{msg}: {err!r}")


def decompress_to_yuv(data: bytes, options: typedict) -> ImageWrapper:
    cdef tjhandle decompressor = tjInitDecompress()
    if decompressor==NULL:
        raise RuntimeError("failed to instantiate a JPEG decompressor")

    cdef Py_buffer py_buf
    if PyObject_GetBuffer(data, &py_buf, PyBUF_ANY_CONTIGUOUS):
        tjDestroy(decompressor)
        raise RuntimeError(f"failed to read compressed data from {type(data)}")

    cdef int r

    def close_decompressor() -> None:
        close_handle(decompressor)

    def release() -> None:
        PyBuffer_Release(&py_buf)

    def close() -> None:
        release()
        close_decompressor()

    def tj_check(int r, msg: str):
        if r:
            close()
            tj_err(r, msg)

    # set the buffer size and pointer to `jpeg` portion:
    cdef unsigned int alpha_offset = options.intget("alpha-offset", 0)
    cdef unsigned char nplanes = 3
    cdef unsigned int buf_len = py_buf.len
    cdef void* buf = <void*> py_buf.buf
    if alpha_offset:
        if alpha_offset >= buf_len:
            raise ValueError(f"jpeg data buffer is too small, expected at least {alpha_offset} but got {buf_len}")
        buf_len = alpha_offset
        nplanes = 4

    # parse header:
    cdef int w, h, subsamp, cs
    r = tjDecompressHeader3(decompressor,
                            <const unsigned char *> buf, buf_len,
                            &w, &h, &subsamp, &cs)
    tj_check(r, "failed to decompress JPEG main header")

    subsamp_str = TJSAMP_STR.get(subsamp, subsamp)
    assert subsamp in (TJSAMP_444, TJSAMP_422, TJSAMP_420, TJSAMP_GRAY), "unsupported JPEG colour subsampling: %s" % subsamp_str
    log("jpeg.decompress_to_yuv %i planes, size: %4ix%-4i, subsampling=%-4s, colorspace=%s",
        nplanes, w, h, subsamp_str, TJCS_STR.get(cs, cs))
    if nplanes==3:
        pixel_format = "YUV%sP" % subsamp_str
    elif nplanes == 4:
        pixel_format = "YUVA%sP" % subsamp_str
    elif nplanes==1:
        pixel_format = "YUV400P"
    else:
        close()
        raise ValueError("invalid number of planes: %i" % nplanes)
    #allocate YUV buffers:
    cdef unsigned long plane_size
    cdef unsigned char *planes[4]
    cdef int strides[4]
    cdef int i, stride
    cdef MemBuf membuf
    cdef MemBuf empty
    cdef int flags = 0
    pystrides = []
    pyplanes = []
    cdef unsigned long total_size = 0
    cdef double start, elapsed
    for i in range(4):
        strides[i] = 0
        planes[i] = NULL

    for i in range(nplanes):
        if i == 3:
            subsamp = TJSAMP_GRAY
        stride = tjPlaneWidth(i % 3, w, subsamp)
        if stride <= 0:
            if subsamp != TJSAMP_GRAY or (i % 3) == 0:
                raise ValueError("cannot get size for plane %r for mode %r" % ("YUVA"[i], subsamp_str))
            stride = roundup(w//2, ALIGN)
            plane_size = stride * roundup(h, 2)//2
            if i==1:
                #allocate empty U and V planes:
                empty = getbuf(plane_size, 0)
                memset(<void *> empty.get_mem(), 128, plane_size)
                pixel_format = "YUV420P"
            membuf = empty
        else:
            stride = roundup(stride, ALIGN)
            strides[i] = stride
            plane_size = tjPlaneSizeYUV(i % 3, w, stride, h, subsamp)
            membuf = getbuf(plane_size, 0)     #add padding?
            planes[i] = <unsigned char*> membuf.get_mem()
        total_size += plane_size
        #python objects for each plane:
        pystrides.append(stride)
        pyplanes.append(memoryview(membuf))
    # log("jpeg strides: %s, plane sizes=%s", pystrides, [int(plane_sizes[i]) for i in range(4)])
    start = monotonic()
    with nogil:
        r = tjDecompressToYUVPlanes(decompressor,
                                    <const unsigned char*> buf, buf_len,
                                    planes, w, strides, h, flags)
    tj_check(r, "failed to decompress {subsamp_str!r} JPEG data to YUV")

    cdef int aw, ah
    if alpha_offset:
        # now decompress the alpha channel:
        buf = <void*> (<uintptr_t> py_buf.buf + alpha_offset)
        buf_len = py_buf.len - alpha_offset

        r = tjDecompressHeader3(decompressor,
                                <const unsigned char *> buf, buf_len,
                                &aw, &ah, &subsamp, &cs)
        tj_check(r, "failed to decompress JPEG alpha header")

        if subsamp != TJSAMP_GRAY:
            subsamp_str = TJSAMP_STR.get(subsamp, subsamp)
            raise ValueError("unsupported JPEG colour subsampling for alpha channel: %s" % subsamp_str)

        if aw != w or ah != h:
            raise ValueError(f"alpha channel dimensions {aw}x{ah} does not match main image {w}x{h}")

        with nogil:
            r = tjDecompressToYUVPlanes(decompressor,
                                        <const unsigned char*> buf, buf_len,
                                        &planes[3], aw, &strides[3], ah, flags)
        tj_check(r, "failed to decompress JPEG alpha channel data")

    close_decompressor()
    release()

    if LOG_PERF:
        elapsed = monotonic()-start
        log("decompress jpeg to %s: %4i MB/s (%9i bytes in %2.1fms)",
            pixel_format, total_size/elapsed//1024//1024, total_size, 1000*elapsed)
    return ImageWrapper(0, 0, w, h, pyplanes, pixel_format, nplanes*8, pystrides, planes=nplanes)


def decompress_to_rgb(data: bytes, options: typedict) -> ImageWrapper:
    cdef unsigned int alpha_offset = options.intget("alpha-offset", 0)
    rgb_format = "BGRA" if alpha_offset else "BGRX"
    rgb_format = options.strget("rgb_format", rgb_format)
    assert rgb_format in TJPF_VAL
    cdef TJPF pixel_format = TJPF_VAL[rgb_format]

    cdef tjhandle decompressor = tjInitDecompress()
    if decompressor==NULL:
        raise RuntimeError("failed to instantiate a JPEG decompressor")

    cdef Py_buffer py_buf
    if PyObject_GetBuffer(data, &py_buf, PyBUF_ANY_CONTIGUOUS):
        tjDestroy(decompressor)
        raise ValueError(f"failed to read compressed data from {type(data)}")

    cdef int r

    def close_decompressor() -> None:
        close_handle(decompressor)

    def release() -> None:
        PyBuffer_Release(&py_buf)

    def close() -> None:
        release()
        close_decompressor()

    def tj_check(int r, msg: str):
        if r:
            close()
            tj_err(r, msg)

    cdef int w, h, subsamp, cs
    cdef uintptr_t buf = <uintptr_t> py_buf.buf
    cdef unsigned long buf_size = py_buf.len
    if alpha_offset>0:
        buf_size = alpha_offset
    log("decompressing buffer at %#x of size %i", buf, buf_size)
    r = tjDecompressHeader3(decompressor,
                            <const unsigned char *> buf, buf_size,
                            &w, &h, &subsamp, &cs)
    tj_check(r, "failed to decompress JPEG header")
    subsamp_str = TJSAMP_STR.get(subsamp, subsamp)
    log("jpeg.decompress_to_rgb: size=%4ix%-4i, subsampling=%3s, colorspace=%s",
        w, h, subsamp_str, TJCS_STR.get(cs, cs))
    cdef int flags = 0      #TJFLAG_BOTTOMUP
    cdef double elapsed
    cdef double start = monotonic()
    cdef int stride = w*4
    cdef unsigned long size = stride*h
    cdef MemBuf membuf = getbuf(size, 0)
    cdef unsigned char *dst_buf = <unsigned char*> membuf.get_mem()
    with nogil:
        r = tjDecompress2(decompressor,
                          <const unsigned char *> buf, buf_size, dst_buf,
                          w, stride, h, pixel_format, flags)
    tj_check(r, "failed to decompress {subsamp_str!r} JPEG data to {rgb_format!r")
    # deal with alpha channel if there is one:
    cdef int aw, ah
    cdef unsigned char *planes[3]
    cdef int strides[3]
    cdef MemBuf alpha
    cdef unsigned long alpha_size
    cdef int x, y, alpha_stride
    cdef unsigned char* alpha_plane
    cdef char alpha_index
    bpp = 24
    if alpha_offset:
        bpp = 32
        alpha_index = rgb_format.find("A")
        assert alpha_index>=0, "no 'A' in %s" % rgb_format
        assert len(rgb_format)==4, "unsupported rgb format for alpha: %s" % rgb_format
        assert <unsigned long> py_buf.len>alpha_offset, "alpha offset is beyond the end of the compressed buffer"
        buf = (<uintptr_t> py_buf.buf) + alpha_offset
        buf_len = py_buf.len - alpha_offset
        r = tjDecompressHeader3(decompressor,
                                <const unsigned char *> buf, buf_len,
                                &aw, &ah, &subsamp, &cs)
        tj_check(r, "failed to decompress alpha channel")
        assert aw==w and ah==h, "alpha plane dimensions %ix%i don't match main image %ix%i" % (aw, ah, w, h)
        subsamp_str = TJSAMP_STR.get(subsamp, subsamp)
        log("found alpha plane %r at %#x size %i", subsamp_str, buf, buf_len)
        assert subsamp==TJSAMP_GRAY, "unsupported JPEG alpha subsampling: %s" % subsamp_str
        for i in range(3):
            strides[i] = 0
            planes[i] = NULL
        alpha_stride = tjPlaneWidth(0, w, subsamp)
        strides[0] = alpha_stride
        alpha_size = tjPlaneSizeYUV(0, w, alpha_stride, h, subsamp)
        alpha = getbuf(alpha_size, 0)
        alpha_plane = <unsigned char*> alpha.get_mem()
        planes[0] = alpha_plane
        with nogil:
            r = tjDecompressToYUVPlanes(decompressor,
                                        <const unsigned char*> buf, buf_len,
                                        planes, w, strides, h, flags)
        tj_check(r, f"failed to decompress {subsamp_str!r} JPEG alpha data")
        #merge alpha into rgb buffer:
        for y in range(h):
            for x in range(w):
                dst_buf[y*stride+x*4+alpha_index] = alpha_plane[y*alpha_stride+x]

    close()
    if LOG_PERF:
        elapsed = monotonic()-start
        log("decompress jpeg to %s: %4i MB/s (%9i bytes in %2.1fms)",
            rgb_format, size/elapsed//1024//1024, size, 1000*elapsed)
    return ImageWrapper(0, 0, w, h, memoryview(membuf), rgb_format, bpp, stride, planes=ImageWrapper.PACKED)


def selftest(full=False) -> None:
    log("jpeg selftest")

    def test_rgbx(bdata, options):
        return decompress_to_rgb(bdata, typedict(options))

    def test_yuv(bdata, options):
        return decompress_to_yuv(bdata, typedict(options))

    from xpra.codecs.checks import TEST_PICTURES
    for encoding in ("jpeg", "jpega"):
        for size, samples in TEST_PICTURES[encoding].items():
            w, h = size
            for data, options in samples:
                for fn in (test_yuv, test_rgbx):
                    img = fn(data, options)
                    log("%s(%i bytes, %s)=%s", fn, len(data), options, img)
                    if full:
                        try:
                            v = fn(data[:len(data)//2])
                            assert v is not None
                        except:
                            pass
                        else:
                            raise RuntimeError("should not be able to decompress incomplete data, but got %s" % v)
