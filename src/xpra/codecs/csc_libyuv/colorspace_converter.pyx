# This file is part of Xpra.
# Copyright (C) 2013 Arthur Huillet
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from xpra.log import Logger
from xpra.codecs.codec_checks import do_testcsc
from xpra.codecs.codec_constants import get_subsampling_divs
log = Logger("csc", "libyuv")

from xpra.os_util import is_Ubuntu
from xpra.codecs.codec_constants import csc_spec
from xpra.codecs.image_wrapper import ImageWrapper


cdef extern from "stdlib.h":
    int posix_memalign(void **memptr, size_t alignment, size_t size)
    void free(void *ptr)

DEF MEMALIGN_ALIGNMENT = 16
cdef void *xmemalign(size_t size):
    cdef void *memptr = NULL
    if posix_memalign(&memptr, MEMALIGN_ALIGNMENT, size):
        return NULL
    return memptr

#inlined here because linking messes up with c++..
cdef extern from "Python.h":
    int PyObject_AsReadBuffer(object obj, const void **buffer, Py_ssize_t *buffer_len)
    int PyMemoryView_Check(object obj)
    object PyMemoryView_FromBuffer(Py_buffer *view)
    Py_buffer *PyMemoryView_GET_BUFFER(object mview)
    int PyBuffer_FillInfo(Py_buffer *view, object obj, void *buf, Py_ssize_t len, int readonly, int infoflags)
    int PyBUF_SIMPLE

cdef int object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len):
    cdef Py_buffer *rpybuf
    if PyMemoryView_Check(obj):
        rpybuf = PyMemoryView_GET_BUFFER(obj)
        if rpybuf.buf==NULL:
            return -1
        buffer[0] = rpybuf.buf
        buffer_len[0] = rpybuf.len
        return 0
    return PyObject_AsReadBuffer(obj, buffer, buffer_len)

cdef object memory_as_readonly_pybuffer(void *ptr, Py_ssize_t buf_len):
    cdef Py_buffer pybuf
    cdef Py_ssize_t shape[1]
    shape[0] = buf_len
    cdef int ret = PyBuffer_FillInfo(&pybuf, None, ptr, buf_len, 0, PyBUF_SIMPLE);
    if ret!=0:
        return None
    pybuf.format = "B"
    pybuf.shape = shape
    return PyMemoryView_FromBuffer(&pybuf)


from libc.stdint cimport uint8_t

cdef extern from "libyuv/convert.h" namespace "libyuv":
    #int BGRAToI420(const uint8_t* src_frame, ...
    #this is actually BGRX for little endian systems:
    int ARGBToI420(const uint8_t* src_frame, int src_stride_frame,
               uint8_t* dst_y, int dst_stride_y,
               uint8_t* dst_u, int dst_stride_u,
               uint8_t* dst_v, int dst_stride_v,
               int width, int height) nogil


cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)


def init_module():
    #nothing to do!
    log("csc_libyuv.init_module()")

def cleanup_module():
    log("csc_libyuv.cleanup_module()")

def get_type():
    return "libyuv"

def get_version():
    return 0

#hardcoded for now:
MAX_WIDTH = 32768
MAX_HEIGHT = 32768
IN_COLORSPACES = ["BGRX"]
OUT_COLORSPACES = ["YUV420P"]
def get_info():
    global IN_COLORSPACES, OUT_COLORSPACES, MAX_WIDTH, MAX_HEIGHT
    return {"version"           : get_version(),
            "input-formats"     : IN_COLORSPACES,
            "output-formats"    : OUT_COLORSPACES,
            "max-size"          : (MAX_WIDTH, MAX_HEIGHT),
            }

def get_input_colorspaces():
    return IN_COLORSPACES

def get_output_colorspaces(input_colorspace):
    assert input_colorspace in IN_COLORSPACES
    return OUT_COLORSPACES


def get_spec(in_colorspace, out_colorspace):
    assert in_colorspace in IN_COLORSPACES, "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, IN_COLORSPACES)
    assert out_colorspace in OUT_COLORSPACES, "invalid output colorspace: %s (must be one of %s)" % (out_colorspace, OUT_COLORSPACES)
    return csc_spec(ColorspaceConverter, codec_type=get_type(), setup_cost=0, min_w=8, min_h=2, can_scale=False, max_w=MAX_WIDTH, max_h=MAX_HEIGHT)


class YUVImageWrapper(ImageWrapper):

    def free(self):                             #@DuplicatedSignature
        log("YUVImageWrapper.free() cython_buffer=%#x", <unsigned long> self.cython_buffer)
        ImageWrapper.free(self)
        if self.cython_buffer>0:
            free(<void *> (<unsigned long> self.cython_buffer))
            self.cython_buffer = 0


cdef class ColorspaceConverter:
    cdef int width
    cdef int height

    cdef unsigned long frames
    cdef double time

    cdef object src_format
    cdef object dst_format
    cdef int out_stride[3]
    cdef unsigned long[3] offsets
    cdef unsigned long out_size[3]
    cdef unsigned long buffer_size

    cdef object __weakref__

    def init_context(self, int src_width, int src_height, src_format,
                           int dst_width, int dst_height, dst_format, int speed=100):    #@DuplicatedSignature
        log("libyuv.ColorspaceConverter.init_context%s", (src_width, src_height, src_format, dst_width, dst_height, dst_format, speed))
        assert src_format=="BGRX", "invalid source format: %s" % src_format
        assert dst_format=="YUV420P", "invalid destination format: %s" % dst_format
        assert src_width==dst_width, "libyuv cannot be used to scale yet"
        assert src_height==dst_height, "libyuv cannot be used to scale yet"
        self.src_format = "BGRX"
        self.dst_format = "YUV420P"
        self.width = src_width
        self.height = src_height
        #pre-calculate plane heights:
        self.buffer_size = 0
        divs = get_subsampling_divs(self.dst_format)
        for i in range(3):
            xdiv, ydiv = divs[i]
            out_height = src_height // ydiv
            self.out_stride[i] = roundup(dst_width // xdiv, 16)
            self.out_size[i] = self.out_stride[i] * out_height
            self.offsets[i] = self.buffer_size
            #add one extra line to height so we can access a full rowstride at a time,
            #no matter where we start to read on the last line
            self.buffer_size += (self.out_size[i] + self.out_stride[i])
        log("buffer size=%s", self.buffer_size)
        self.time = 0
        self.frames = 0

    def get_info(self):         #@DuplicatedSignature
        info = get_info()
        info.update({
                "frames"    : self.frames,
                "width"     : self.width,
                "height"    : self.height})
        if self.src_format:
            info["src_format"] = self.src_format
        if self.dst_format:
            info["dst_format"] = self.dst_format
        if self.frames>0 and self.time>0:
            pps = float(self.width) * float(self.height) * float(self.frames) / self.time
            info["total_time_ms"] = int(self.time*1000.0)
            info["pixels_per_second"] = int(pps)
        return info

    def __repr__(self):
        if not self.src_format or not self.dst_format:
            return "libyuv(uninitialized)"
        return "libyuv(%s %sx%s %s)" % (self.src_format, self.width, self.height, self.dst_format)

    def __dealloc__(self):                  #@DuplicatedSignature
        self.clean()

    def get_src_width(self):
        return self.width

    def get_src_height(self):
        return self.height

    def get_src_format(self):
        return self.src_format

    def get_dst_width(self):
        return self.width

    def get_dst_height(self):
        return self.height

    def get_dst_format(self):
        return self.dst_format

    def get_type(self):                     #@DuplicatedSignature
        return  "libyuv"


    def clean(self):                        #@DuplicatedSignature
        self.width = 0
        self.height = 0
        self.src_format = ""
        self.dst_format = ""
        self.frames = 0
        self.time = 0
        for i in range(3):
            self.out_stride[i] = 0
            self.out_size[i] = 0
        self.buffer_size = 0

    def is_closed(self):
        return self.buffer_size==0


    def convert_image(self, image):
        cdef Py_ssize_t pic_buf_len = 0
        cdef const uint8_t *input_image
        cdef uint8_t *output_buffer
        cdef uint8_t *out_planes[3]
        cdef int iplanes
        cdef int i, result
        cdef int width, height, stride
        start = time.time()
        iplanes = image.get_planes()
        pixels = image.get_pixels()
        stride = image.get_rowstride()
        width = image.get_width()
        height = image.get_height()
        assert iplanes==ImageWrapper.PACKED, "invalid plane input format: %s" % iplanes
        assert pixels, "failed to get pixels from %s" % image
        assert width>=self.width, "invalid image width: %s (minimum is %s)" % (width, self.width)
        assert height>=self.height, "invalid image height: %s (minimum is %s)" % (height, self.height)
        #get pointer to input:
        assert object_as_buffer(pixels, <const void**> &input_image, &pic_buf_len)==0
        #allocate output buffer:
        output_buffer = <unsigned char*> xmemalign(self.buffer_size)
        for i in range(3):
            out_planes[i] = output_buffer + self.offsets[i]
        with nogil:
            result = ARGBToI420(input_image, stride,
                           out_planes[0],  self.out_stride[0], out_planes[1], self.out_stride[1], out_planes[2], self.out_stride[2],
                           self.width, self.height)
        assert result==0, "libyuv BGRAToI420 failed and returned %i" % result
        planes = []
        strides = []
        for i in range(3):
            strides.append(self.out_stride[i])
            planes.append(memory_as_readonly_pybuffer(<void *> (<unsigned long> (out_planes[i])), self.out_size[i]))
        elapsed = time.time()-start
        log("libyuv.ARGBToI420 took %.1fms", self, 1000.0*elapsed)
        self.time += elapsed
        self.frames += 1
        out_image = YUVImageWrapper(0, 0, self.width, self.height, planes, self.dst_format, 24, strides, ImageWrapper._3_PLANES)
        out_image.cython_buffer = <unsigned long> output_buffer
        return out_image


def selftest(full=False):
    global MAX_WIDTH, MAX_HEIGHT
    from xpra.codecs.codec_checks import testcsc, get_csc_max_size
    from xpra.codecs.csc_libyuv import colorspace_converter
    maxw, maxh = MAX_WIDTH, MAX_HEIGHT
    in_csc = get_input_colorspaces()
    out_csc = get_output_colorspaces(in_csc[0])
    testcsc(colorspace_converter, full, in_csc, out_csc)
    if full:
        mw, mh = get_csc_max_size(colorspace_converter, in_csc, out_csc, limit_w=32768, limit_h=32768)
        MAX_WIDTH = min(maxw, mw)
        MAX_HEIGHT = min(maxh, mh)
