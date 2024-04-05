# This file is part of Xpra.
# Copyright (C) 2013 Arthur Huillet
# Copyright (C) 2012-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False, wraparound=False, cdivision=True, language_level=3
from __future__ import absolute_import

import os
import time

from xpra.log import Logger
log = Logger("csc", "libyuv")

from xpra.util import csv
from xpra.codecs.codec_constants import get_subsampling_divs, csc_spec
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.buffers.membuf cimport memalign, object_as_buffer, memory_as_pybuffer #pylint: disable=syntax-error

from xpra.monotonic_time cimport monotonic_time
from libc.stdint cimport uint8_t, uintptr_t
from libc.stdlib cimport free


cdef extern from "../../buffers/memalign.h":
    unsigned int MEMALIGN_ALIGNMENT


cdef extern from "libyuv/convert.h" namespace "libyuv":
    #int BGRAToI420(const uint8_t* src_frame, ...
    #this is actually BGRX for little endian systems:
    int ARGBToI420(const uint8_t* src_frame, int src_stride_frame,
               uint8_t* dst_y, int dst_stride_y,
               uint8_t* dst_u, int dst_stride_u,
               uint8_t* dst_v, int dst_stride_v,
               int width, int height) nogil

    int ARGBToJ420(const uint8_t* src_frame, int src_stride_frame,
               uint8_t* dst_y, int dst_stride_y,
               uint8_t* dst_u, int dst_stride_u,
               uint8_t* dst_v, int dst_stride_v,
               int width, int height) nogil


cdef extern from "libyuv/convert_from_argb.h" namespace "libyuv":
    int I420ToRGB24(const uint8_t* src_y, int src_stride_y,
                    const uint8_t* src_u, int src_stride_u,
                    const uint8_t* src_v, int src_stride_v,
                    uint8_t* dst_rgb24, int dst_stride_rgb24,
                    int width, int height) nogil

    int I420ToRGBA(const uint8_t* src_y, int src_stride_y,
                   const uint8_t* src_u, int src_stride_u,
                   const uint8_t* src_v, int src_stride_v,
                   uint8_t* dst_rgba, int dst_stride_rgba,
                   int width, int height) nogil

    int I420ToABGR(const uint8_t* src_y, int src_stride_y,
                   const uint8_t* src_u, int src_stride_u,
                   const uint8_t* src_v, int src_stride_v,
                   uint8_t* dst_abgr, int dst_stride_abgr,
                   int width, int height) nogil


cdef extern from "libyuv/scale.h" namespace "libyuv":
    ctypedef enum FilterMode:
        kFilterNone
        kFilterBilinear
        kFilterBox
    void ScalePlane(const uint8_t* src, int src_stride,
                int src_width, int src_height,
                uint8_t* dst, int dst_stride,
                int dst_width, int dst_height,
                FilterMode filtering) nogil

cdef extern from "libyuv/scale_argb.h" namespace "libyuv":
    int ARGBScale(const uint8_t* src_argb,
              int src_stride_argb,
              int src_width,
              int src_height,
              uint8_t* dst_argb,
              int dst_stride_argb,
              int dst_width,
              int dst_height,
              FilterMode filtering) nogil

cdef get_fiter_mode_str(FilterMode fm):
    if fm==kFilterNone:
        return "None"
    elif fm==kFilterBilinear:
        return "Bilinear"
    elif fm==kFilterBox:
        return  "Box"
    return "invalid"

cdef inline FilterMode get_filtermode(int speed):
    if speed>66:
        return kFilterNone
    elif speed>33:
        return kFilterBilinear
    return kFilterBox


cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)

cdef inline uintptr_t roundupl(uintptr_t n, uintptr_t m):
    return (n + m - 1) & ~(m - 1)

cdef inline uintptr_t memalign_ptr(uintptr_t ptr):
    return <uintptr_t> roundupl(<uintptr_t> ptr, MEMALIGN_ALIGNMENT)


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
COLORSPACES = {
    "BGRX" : ("YUV420P", ),
    "YUV420P" : ("RGB", "XBGR", "RGBX"),
}


def get_info():
    return {
        "version"           : get_version(),
        "formats"           : COLORSPACES,
        "max-size"          : (MAX_WIDTH, MAX_HEIGHT),
    }


def get_input_colorspaces():
    return tuple(COLORSPACES.keys())


def get_output_colorspaces(input_colorspace):
    return COLORSPACES.get(input_colorspace, ())


def get_spec(in_colorspace, out_colorspace):
    assert in_colorspace in COLORSPACES, "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, COLORSPACES)
    assert out_colorspace in COLORSPACES[in_colorspace], "invalid output colorspace: %s (must be one of %s)" % (out_colorspace, COLORSPACES[in_colorspace])
    return csc_spec(in_colorspace, out_colorspace,
                    ColorspaceConverter, codec_type=get_type(),
                    quality=100, speed=100,
                    setup_cost=0, min_w=8, min_h=2, can_scale=in_colorspace!="YUV420P",
                    max_w=MAX_WIDTH, max_h=MAX_HEIGHT)


class YUVImageWrapper(ImageWrapper):

    def _cn(self):
        return "libyuv.YUVImageWrapper"

    def free(self):                             #@DuplicatedSignature
        cdef uintptr_t buf = self.cython_buffer
        self.cython_buffer = 0
        log("libyuv.YUVImageWrapper.free() cython_buffer=%#x", buf)
        ImageWrapper.free(self)
        if buf!=0:
            free(<void *> buf)


def argb_scale(image, int dst_width, int dst_height, FilterMode filtermode=kFilterNone):
    cdef iplanes = image.get_planes()
    pixels = image.get_pixels()
    cdef int stride = image.get_rowstride()
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    cdef int bpp = image.get_bytesperpixel()
    assert bpp in (3, 4), "invalid bytes per pixel: %s" % bpp
    assert iplanes==ImageWrapper.PACKED, "invalid plane input format: %s" % iplanes
    assert pixels, "failed to get pixels from %s" % image
    #allocate output buffer:
    cdef int dst_stride = dst_width*4

    cdef uint8_t* buf = <uint8_t*> memalign(dst_stride*dst_height)
    if not buf:
        raise RuntimeError("failed to allocate %i bytes for output buffer" % (dst_stride*height, ))
    cdef int result = -1
    cdef const uint8_t* src
    cdef Py_ssize_t pic_buf_len = 0
    assert object_as_buffer(pixels, <const void**> &src, &pic_buf_len)==0
    assert pic_buf_len >= stride*height
    with nogil:
        result = ARGBScale(src,
                           stride, width, height,
                           buf, dst_stride, dst_width, dst_height,
                           filtermode)
    assert result==0, "libyuv ARGBScale failed and returned %i" % result
    out = memory_as_pybuffer(<void *> buf, dst_stride*dst_height, True)
    scaled_image = YUVImageWrapper(0, 0, dst_width, dst_height, out,
                                   image.get_pixel_format(), image.get_depth(), dst_stride, bpp, ImageWrapper.PACKED)
    log("argb_scale(%s, %i, %i, %i)=%s", image, dst_width, dst_height, filtermode, scaled_image)
    scaled_image.cython_buffer = buf
    return scaled_image


cdef class ColorspaceConverter:
    cdef int src_width
    cdef int src_height
    cdef int dst_width
    cdef int dst_height
    cdef uint8_t yuv_scaling
    cdef uint8_t rgb_scaling
    cdef int planes

    cdef unsigned long frames
    cdef double time

    cdef object src_format
    cdef object dst_format
    cdef int out_stride[3]
    cdef int out_width[3]
    cdef int out_height[3]
    cdef unsigned long[3] out_offsets
    cdef unsigned long out_size[3]
    cdef unsigned long out_buffer_size
    #when yuv_scaling:
    cdef uint8_t *output_buffer
    cdef FilterMode filtermode
    cdef int scaled_stride[3]
    cdef int scaled_width[3]
    cdef int scaled_height[3]
    cdef unsigned long[3] scaled_offsets
    cdef unsigned long scaled_size[3]
    cdef unsigned long scaled_buffer_size

    cdef object __weakref__

    def init_context(self, int src_width, int src_height, src_format,
                           int dst_width, int dst_height, dst_format, int speed=100):
        log("libyuv.ColorspaceConverter.init_context%s", (
            src_width, src_height, src_format, dst_width, dst_height, dst_format, speed))
        if src_format not in COLORSPACES:
            raise ValueError("invalid input colorspace: %s, must be one of %s" % (src_format, csv(COLORSPACES.keys())))
        if dst_format not in COLORSPACES[src_format]:
            raise ValueError("invalid output colorspace for %s to %s, output must be one of %s" % (src_format, dst_format, csv(COLORSPACES.get(src_format, ()))))
        self.src_format = src_format
        self.dst_format = dst_format
        self.filtermode = get_filtermode(speed)
        self.src_width = src_width
        self.src_height = src_height
        self.dst_width = dst_width
        self.dst_height = dst_height
        self.out_buffer_size = 0
        self.scaled_buffer_size = 0
        self.time = 0
        self.frames = 0
        self.output_buffer = NULL
        cdef uint8_t scaling = int(src_width!=dst_width or src_height!=dst_height)
        if dst_format=="YUV420P":
            self.planes = 3
            self.yuv_scaling = scaling
            self.rgb_scaling = False
            self.init_yuv_output()
        elif dst_format in ("RGB", "BGRX", "RGBX", "XBGR"):
            if scaling:
                raise ValueError(f"cannot scale {src_format} to {dst_format}")
            self.planes = 1
            self.yuv_scaling = False
            self.rgb_scaling = False
            self.out_buffer_size = dst_width*len(dst_format)*dst_height
        else:
            raise ValueError(f"invalid destination format: {dst_format!r}")
        log(f"{src_format} -> {dst_format} planes={self.planes}, yuv-scaling={self.yuv_scaling}, rgb-scaling={self.rgb_scaling}, output buffer-size={self.out_buffer_size}")

    def init_yuv_output(self):
        #pre-calculate unscaled YUV plane heights:
        divs = get_subsampling_divs(self.dst_format)
        for i in range(self.planes):
            xdiv, ydiv = divs[i]
            if self.rgb_scaling:
                #we scale before csc to the dst size:
                self.out_width[i]   = self.dst_width // xdiv
                self.out_height[i]  = self.dst_height // ydiv
            else:
                #we don't scale, so the size is the src size:
                self.out_width[i]   = self.src_width // xdiv
                self.out_height[i]  = self.src_height // ydiv
            self.out_stride[i]  = roundup(self.out_width[i], MEMALIGN_ALIGNMENT)
            self.out_size[i]    = self.out_stride[i] * self.out_height[i]
            self.out_offsets[i] = self.out_buffer_size
            #add two extra lines to height so we can access two rowstrides at a time,
            #no matter where we start to read on the last line
            #and round up to memalign each plane:
            #(why two and not just one? libyuv will do this for input data with odd height)
            self.out_buffer_size += roundupl(self.out_size[i] + 2*self.out_stride[i], MEMALIGN_ALIGNMENT)
            if self.yuv_scaling:
                self.scaled_width[i]    = self.dst_width // xdiv
                self.scaled_height[i]   = self.dst_height // ydiv
                self.scaled_stride[i]   = roundup(self.scaled_width[i], MEMALIGN_ALIGNMENT)
                self.scaled_size[i]     = self.scaled_stride[i] * self.scaled_height[i]
                self.scaled_offsets[i]  = self.scaled_buffer_size
                self.scaled_buffer_size += self.scaled_size[i] + self.out_stride[i]
        if self.yuv_scaling:
            #re-use the same temporary buffer every time before scaling:
            self.output_buffer = <uint8_t *> memalign(self.out_buffer_size)
            if self.output_buffer==NULL:
                raise Exception("failed to allocate %i bytes for output buffer" % (self.out_buffer_size, ))
        log("buffer size=%i, yuv_scaling=%s, rgb_scaling=%s, filtermode=%s",
            self.out_buffer_size, self.yuv_scaling, self.rgb_scaling, get_fiter_mode_str(self.filtermode))

    def get_info(self):
        info = get_info()
        info.update({
                "frames"    : int(self.frames),
                "src_width" : self.src_width,
                "src_height": self.src_height,
                "dst_width" : self.dst_width,
                "dst_height": self.dst_height,
                "planes"    : self.planes,
                })
        if self.yuv_scaling:
            info["yuv-scaling"] = True
        if self.rgb_scaling:
            info["rgb-scaling"] = True
        if self.src_format:
            info["src_format"] = self.src_format
        if self.dst_format:
            info["dst_format"] = self.dst_format
        if self.frames>0 and self.time>0:
            pps = float(self.src_width) * float(self.src_height) * float(self.frames) / self.time
            info["total_time_ms"] = int(self.time*1000.0)
            info["pixels_per_second"] = int(pps)
        return info

    def __repr__(self):
        if not self.src_format or not self.dst_format:
            return "libyuv(uninitialized)"
        return "libyuv(%s %sx%s %s)" % (self.src_format, self.src_width, self.src_height, self.dst_format)

    def __dealloc__(self):                  #@DuplicatedSignature
        self.clean()

    def get_src_width(self):
        return self.src_width

    def get_src_height(self):
        return self.src_height

    def get_src_format(self):
        return self.src_format

    def get_dst_width(self):
        return self.dst_width

    def get_dst_height(self):
        return self.dst_height

    def get_dst_format(self):
        return self.dst_format

    def get_type(self):                     #@DuplicatedSignature
        return  "libyuv"


    def clean(self):                        #@DuplicatedSignature
        self.src_width = 0
        self.src_height = 0
        self.dst_width = 0
        self.dst_height = 0
        self.src_format = ""
        self.dst_format = ""
        self.frames = 0
        self.time = 0
        self.yuv_scaling = 0
        self.rgb_scaling = 0
        for i in range(3):
            self.out_stride[i] = 0
            self.out_size[i] = 0
        cdef uint8_t *output_buffer = self.output_buffer
        self.output_buffer = NULL
        if output_buffer:
            free(output_buffer)
        self.out_buffer_size = 0

    def is_closed(self):
        return self.out_buffer_size==0


    def convert_image(self, image):
        cdef int width = image.get_width()
        cdef int height = image.get_height()
        if width<self.src_width:
            raise ValueError("invalid image width: %s (minimum is %s)" % (width, self.src_width))
        if height<self.src_height:
            raise ValueError("invalid image height: %s (minimum is %s)" % (height, self.src_height))

        if self.src_format in ("BGRX", "BGRA"):
            return self.convert_bgrx_image(image)
        elif self.src_format=="YUV420P":
            return self.convert_yuv420p_image(image)
        else:
            raise RuntimeError("invalid source format %s" % (self.src_format, ))

    def convert_yuv420p_image(self, image):
        cdef double start = monotonic_time()
        cdef int iplanes = image.get_planes()
        cdef int width = image.get_width()
        cdef int height = image.get_height()
        if iplanes!=3:
            raise ValueError("invalid number of planes: %s for %s" % (iplanes, self.src_format))
        if self.dst_format not in ("RGB", "XBGR", "RGBX"):
            raise ValueError("invalid dst format %s" % (self.dst_format, ))
        if self.rgb_scaling:
            raise ValueError("cannot scale %s" % (self.src_format, ))
        pixels = image.get_pixels()
        strides = image.get_rowstride()
        cdef int y_stride = strides[0]
        cdef int u_stride = strides[1]
        cdef int v_stride = strides[2]
        cdef int Bpp = len(self.dst_format)
        cdef int rowstride = self.dst_width*Bpp
        cdef uintptr_t y, u, v
        cdef uint8_t *rgb
        cdef int r = 0
        log("convert_yuv420p_image(%s) to %s", image, self.dst_format)

        rgb = <uint8_t*> memalign(self.out_buffer_size)
        if not rgb:
            raise RuntimeError("failed to allocate %s bytes for output buffer" % (self.out_buffer_size, ))

        cdef Py_ssize_t pic_buf_len = 0
        assert object_as_buffer(pixels[0], <const void**> &y, &pic_buf_len)==0
        assert object_as_buffer(pixels[1], <const void**> &u, &pic_buf_len)==0
        assert object_as_buffer(pixels[2], <const void**> &v, &pic_buf_len)==0

        if self.dst_format=="RGB":
            with nogil:
                r = I420ToRGB24(<const uint8_t*> y, y_stride,
                                <const uint8_t*> u, u_stride,
                                <const uint8_t*> v, v_stride,
                                rgb, rowstride,
                                width, height)
        elif self.dst_format=="XBGR":
            with nogil:
                r = I420ToRGBA(<const uint8_t*> y, y_stride,
                               <const uint8_t*> u, u_stride,
                               <const uint8_t*> v, v_stride,
                               rgb, rowstride,
                               width, height)
        elif self.dst_format=="RGBX":
            with nogil:
                r = I420ToABGR(<const uint8_t*> y, y_stride,
                               <const uint8_t*> u, u_stride,
                               <const uint8_t*> v, v_stride,
                               rgb, rowstride,
                               width, height)
        else:
            raise RuntimeError("unexpected dst format %s", self.dst_format)
        if r!=0:
            raise RuntimeError("libyuv YUV420PToRGB failed and returned %s", r)
        cdef double elapsed = monotonic_time()-start
        log("libyuv.YUV420P to %s took %.1fms", self.dst_format, 1000.0*elapsed)
        self.time += elapsed
        rgb_buffer = memory_as_pybuffer(<void *> rgb, self.out_buffer_size, True)
        rgb_image = YUVImageWrapper(0, 0, self.dst_width, self.dst_height,
                                    rgb_buffer, self.dst_format, Bpp*8, rowstride, Bpp, ImageWrapper.PACKED)
        rgb_image.cython_buffer = <uintptr_t> rgb
        return rgb_image

    def convert_bgrx_image(self, image):
        cdef uint8_t *output_buffer
        cdef uint8_t *out_planes[3]
        cdef uint8_t *scaled_buffer
        cdef uint8_t *scaled_planes[3]
        cdef int i
        cdef double start = monotonic_time()
        cdef int iplanes = image.get_planes()
        cdef int width = image.get_width()
        cdef int height = image.get_height()
        if iplanes!=ImageWrapper.PACKED:
            raise ValueError("invalid plane input format: %s" % (iplanes, ))
        if self.rgb_scaling:
            #first downscale:
            image = argb_scale(image, self.dst_width, self.dst_height, self.filtermode)
            width = self.dst_width
            height = self.dst_height
        cdef int stride = image.get_rowstride()
        pixels = image.get_pixels()
        assert pixels, "failed to get pixels from %s" % image
        if self.yuv_scaling:
            #re-use the same temporary buffer every time:
            output_buffer = self.output_buffer
        else:
            #allocate output buffer:
            output_buffer = <unsigned char*> memalign(self.out_buffer_size)
            if output_buffer==NULL:
                raise Exception("failed to allocate %s bytes for output buffer" % (self.out_buffer_size, ))
        for i in range(self.planes):
            #offsets are aligned, so this is safe and gives us aligned pointers:
            out_planes[i] = <uint8_t*> (memalign_ptr(<uintptr_t> output_buffer) + self.out_offsets[i])
        #get pointer to input:
        cdef const uint8_t* src
        cdef Py_ssize_t pic_buf_len = 0
        assert object_as_buffer(pixels, <const void**> &src, &pic_buf_len)==0
        assert pic_buf_len>=(stride*height), "pixel buffer is too small: %s, expected at least %s (%ix%i)" % (pic_buf_len, stride*height*4, stride, height)
        cdef int result = -1
        with nogil:
            result = ARGBToJ420(src, stride,
                                out_planes[0], self.out_stride[0],
                                out_planes[1], self.out_stride[1],
                                out_planes[2], self.out_stride[2],
                                width, height)
        if result!=0:
            raise RuntimeError("libyuv ARGBToJ420 failed and returned %s" % (result, ))
        cdef double elapsed = monotonic_time()-start
        log("libyuv.ARGBToI420 took %.1fms", 1000.0*elapsed)
        self.time += elapsed
        cdef object planes = []
        cdef object strides = []
        cdef object out_image
        if self.yuv_scaling:
            start = monotonic_time()
            scaled_buffer = <unsigned char*> memalign(self.scaled_buffer_size)
            if scaled_buffer==NULL:
                raise RuntimeError("failed to allocate %s bytes for scaled buffer" % (self.scaled_buffer_size, ))
            with nogil:
                for i in range(self.planes):
                    scaled_planes[i] = scaled_buffer + self.scaled_offsets[i]
                    ScalePlane(out_planes[i], self.out_stride[i],
                               self.out_width[i], self.out_height[i],
                               scaled_planes[i], self.scaled_stride[i],
                               self.scaled_width[i], self.scaled_height[i],
                               self.filtermode)
            elapsed = monotonic_time()-start
            log("libyuv.ScalePlane %i times, took %.1fms", self.planes, 1000.0*elapsed)
            for i in range(self.planes):
                strides.append(self.scaled_stride[i])
                planes.append(memory_as_pybuffer(<void *> scaled_planes[i], self.scaled_size[i], True))
            self.frames += 1
            out_image = YUVImageWrapper(0, 0, self.dst_width, self.dst_height, planes, self.dst_format, 24, strides, 1, self.planes)
            out_image.cython_buffer = <uintptr_t> scaled_buffer
        else:
            #use output buffer directly:
            for i in range(self.planes):
                strides.append(self.out_stride[i])
                planes.append(memory_as_pybuffer(<void *> out_planes[i], self.out_size[i], True))
            self.frames += 1
            out_image = YUVImageWrapper(0, 0, self.dst_width, self.dst_height, planes, self.dst_format, 24, strides, 1, self.planes)
            out_image.cython_buffer = <uintptr_t> output_buffer
        return out_image


def selftest(full=False):
    global MAX_WIDTH, MAX_HEIGHT
    from xpra.codecs.codec_checks import testcsc, get_csc_max_size
    from xpra.codecs.csc_libyuv import colorspace_converter
    maxw, maxh = MAX_WIDTH, MAX_HEIGHT
    testcsc(colorspace_converter, full)
    if full:
        in_csc = get_input_colorspaces()
        out_csc = get_output_colorspaces(in_csc[0])
        mw, mh = get_csc_max_size(colorspace_converter, in_csc, out_csc, limit_w=32768, limit_h=32768)
        MAX_WIDTH = min(maxw, mw)
        MAX_HEIGHT = min(maxh, mh)
