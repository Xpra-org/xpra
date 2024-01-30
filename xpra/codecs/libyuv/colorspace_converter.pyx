# This file is part of Xpra.
# Copyright (C) 2013 Arthur Huillet
# Copyright (C) 2012-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from typing import Dict, Any, Tuple
from time import monotonic

from xpra.log import Logger
log = Logger("csc", "libyuv")

from xpra.util import typedict, csv
from xpra.codecs.codec_constants import get_subsampling_divs, csc_spec
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.buffers.membuf cimport getbuf, MemBuf, memalign, buffer_context   #pylint: disable=syntax-error

from libc.stdint cimport uint8_t, uintptr_t
from libc.stdlib cimport free


cdef extern from "Python.h":
    object PyMemoryView_FromMemory(char *mem, Py_ssize_t size, int flags)
    int PyBUF_WRITE

cdef extern from "libyuv/convert_from_argb.h" namespace "libyuv":
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

    int ARGBToNV12(const uint8_t* src_argb, int src_stride_argb,
                   uint8_t* dst_y, int dst_stride_y,
                   uint8_t* dst_uv, int dst_stride_uv,
                   int width, int height) nogil

    int NV12ToRGB24(const uint8_t* src_y, int src_stride_y,
                    const uint8_t* src_uv, int src_stride_uv,
                    uint8_t* dst_rgb24, int dst_stride_rgb24,
                    int width, int height) nogil

    int NV12ToARGB(const uint8_t* src_y, int src_stride_y,
                   const uint8_t* src_uv, int src_stride_uv,
                   uint8_t* dst_argb, int dst_stride_argb,
                   int width, int height) nogil

    int NV12ToABGR(const uint8_t* src_y, int src_stride_y,
                   const uint8_t* src_uv,int src_stride_uv,
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

cdef extern from "libyuv/planar_functions.h" namespace "libyuv":
    int ARGBGrayTo(const uint8_t* src_argb,
                   int src_stride_argb,
                   uint8_t* dst_argb,
                   int dst_stride_argb,
                   int width,
                   int height) nogil

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


DEF ALIGN = 4   #MEMALIGN_ALIGNMENT

cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)

cdef inline uintptr_t roundupl(uintptr_t n, uintptr_t m):
    return (n + m - 1) & ~(m - 1)

cdef inline uintptr_t memalign_ptr(uintptr_t ptr):
    return <uintptr_t> roundupl(<uintptr_t> ptr, ALIGN)


def init_module():
    #nothing to do!
    log("csc_libyuv.init_module()")

def cleanup_module():
    log("csc_libyuv.cleanup_module()")

def get_type() -> str:
    return "libyuv"

def get_version() -> Tuple[int,int]:
    return (1, 0)

#hardcoded for now:
MAX_WIDTH = 32768
MAX_HEIGHT = 32768
COLORSPACES = {
    "BGRX" : ("YUV420P", "NV12"),
    "NV12" : ("RGB", "BGRX", "RGBX"),
    }
def get_info() -> Dict[str,Any]:
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
                    setup_cost=0, min_w=8, min_h=2, can_scale=in_colorspace!="NV12",
                    max_w=MAX_WIDTH, max_h=MAX_HEIGHT)


class YUVImageWrapper(ImageWrapper):

    def _cn(self):
        return "libyuv.YUVImageWrapper"

    def free(self):
        cdef uintptr_t buf = self.cython_buffer
        self.cython_buffer = 0
        log("libyuv.YUVImageWrapper.free() cython_buffer=%#x", buf)
        super().free()
        if buf!=0:
            free(<void *> buf)

def argb_to_gray(image):
    cdef iplanes = image.get_planes()
    pixels = image.get_pixels()
    cdef int stride = image.get_rowstride()
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    assert iplanes==ImageWrapper.PACKED, "invalid plane input format: %s" % iplanes
    assert pixels, "failed to get pixels from %s" % image
    #allocate output buffer:
    cdef int dst_stride = width*4
    cdef MemBuf output_buffer = getbuf(dst_stride*height)
    if not output_buffer:
        raise RuntimeError("failed to allocate %i bytes for output buffer" % (dst_stride*height))
    cdef uint8_t* buf = <uint8_t*> output_buffer.get_mem()
    cdef int result = -1
    cdef const uint8_t* src
    with buffer_context(pixels) as bc:
        src = <const uint8_t *> (<uintptr_t> int(bc))
        with nogil:
            result = ARGBGrayTo(src, stride,
                                buf, dst_stride,
                                width, height)
    assert result==0, "libyuv BGRAToI420 failed and returned %i" % result
    out = memoryview(output_buffer)
    gray_image = ImageWrapper(0, 0, width, height, out, image.get_pixel_format(), 24, dst_stride, image.get_bytesperpixel(), ImageWrapper.PACKED)
    log("argb_to_gray(%s)=%s", image, gray_image)
    return gray_image


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
    cdef MemBuf output_buffer = getbuf(dst_stride*dst_height)
    if not output_buffer:
        raise RuntimeError("failed to allocate %i bytes for output buffer" % (dst_stride*height))
    cdef uint8_t* buf = <uint8_t*> output_buffer.get_mem()
    cdef int result = -1
    cdef const uint8_t* src
    with buffer_context(pixels) as bc:
        src = <const uint8_t *> (<uintptr_t> int(bc))
        with nogil:
            result = ARGBScale(src,
                               stride, width, height,
                               buf, dst_stride, dst_width, dst_height,
                               filtermode)
    assert result==0, "libyuv ARGBScale failed and returned %i" % result
    out = memoryview(output_buffer)
    scaled_image = ImageWrapper(0, 0, dst_width, dst_height, out,
                                image.get_pixel_format(), image.get_depth(), dst_stride, bpp, ImageWrapper.PACKED)
    log("argb_scale(%s, %i, %i, %i)=%s", image, dst_width, dst_height, filtermode, scaled_image)
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
                           int dst_width, int dst_height, dst_format, options:typedict=None):
        log("libyuv.ColorspaceConverter.init_context%s", (
            src_width, src_height, src_format, dst_width, dst_height, dst_format, options))
        if src_format not in COLORSPACES:
            raise ValueError(f"invalid input colorspace: {src_format}, must be one of " + csv(COLORSPACES.keys()))
        if dst_format not in COLORSPACES[src_format]:
            raise ValueError(f"invalid output colorspace {dst_format} for {src_format} input, must be one of " + csv(COLORSPACES.get(src_format, ())))
        self.src_format = src_format
        self.dst_format = dst_format
        cdef int speed = typedict(options or {}).intget("speed", 100)
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
        elif dst_format=="NV12":
            self.planes = 2
            self.yuv_scaling = False
            self.rgb_scaling = scaling
            self.init_yuv_output()
        elif dst_format in ("RGB", "BGRX", "RGBX"):
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
            self.out_stride[i]  = roundup(self.out_width[i], ALIGN)
            self.out_size[i]    = self.out_stride[i] * self.out_height[i]
            self.out_offsets[i] = self.out_buffer_size
            #add two extra lines to height so we can access two rowstrides at a time,
            #no matter where we start to read on the last line
            #and round up to memalign each plane:
            #(why two and not just one? libyuv will do this for input data with odd height)
            self.out_buffer_size += roundupl(self.out_size[i] + 2*self.out_stride[i], ALIGN)
            if self.yuv_scaling:
                self.scaled_width[i]    = self.dst_width // xdiv
                self.scaled_height[i]   = self.dst_height // ydiv
                self.scaled_stride[i]   = roundup(self.scaled_width[i], ALIGN)
                self.scaled_size[i]     = self.scaled_stride[i] * self.scaled_height[i]
                self.scaled_offsets[i]  = self.scaled_buffer_size
                self.scaled_buffer_size += self.scaled_size[i] + self.out_stride[i]
        if self.yuv_scaling:
            #re-use the same temporary buffer every time before scaling:
            self.output_buffer = <uint8_t *> memalign(self.out_buffer_size)
            if self.output_buffer==NULL:
                raise RuntimeError("failed to allocate %i bytes for output buffer" % self.out_buffer_size)
        log("buffer size=%i, yuv_scaling=%s, rgb_scaling=%s, filtermode=%s",
            self.out_buffer_size, self.yuv_scaling, self.rgb_scaling, get_fiter_mode_str(self.filtermode))

    def get_info(self) -> Dict[str,Any]:
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
            pps = self.src_width * self.src_height * self.frames / self.time
            info["total_time_ms"] = int(self.time*1000.0)
            info["pixels_per_second"] = int(pps)
        return info

    def __repr__(self):
        if not self.src_format or not self.dst_format:
            return "libyuv(uninitialized)"
        return "libyuv(%s %sx%s %s)" % (self.src_format, self.src_width, self.src_height, self.dst_format)

    def __dealloc__(self):
        self.clean()

    def get_src_width(self) -> int:
        return self.src_width

    def get_src_height(self) -> int:
        return self.src_height

    def get_src_format(self) -> str:
        return self.src_format

    def get_dst_width(self) -> int:
        return self.dst_width

    def get_dst_height(self) -> int:
        return self.dst_height

    def get_dst_format(self) -> str:
        return self.dst_format

    def get_type(self) -> str:
        return  "libyuv"


    def clean(self):
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

    def is_closed(self) -> bool:
        return self.out_buffer_size==0


    def convert_image(self, image):
        if self.src_format=="BGRX":
            return self.convert_bgrx_image(image)
        elif self.src_format=="NV12":
            return self.convert_nv12_image(image)
        else:
            raise RuntimeError(f"invalid source format {self.src_format}")

    def convert_nv12_image(self, image):
        cdef double start = monotonic()
        cdef int iplanes = image.get_planes()
        cdef int width = image.get_width()
        cdef int height = image.get_height()
        if width<self.src_width:
            raise ValueError(f"invalid image width: {width} (minimum is {self.src_width})")
        if height<self.src_height:
            raise ValueError(f"invalid image height: {height} (minimum is {self.src_height})")
        if iplanes!=2:
            raise ValueError(f"invalid plane input format: {iplanes}")
        if self.dst_format not in ("RGB", "BGRX", "RGBX"):
            raise ValueError(f"invalid dst format {self.dst_format}")
        if self.rgb_scaling:
            raise ValueError(f"cannot scale {self.src_format}")
        pixels = image.get_pixels()
        strides = image.get_rowstride()
        cdef int y_stride = strides[0]
        cdef int uv_stride = strides[1]
        cdef int Bpp = len(self.dst_format)
        cdef int rowstride = self.dst_width*Bpp
        cdef MemBuf rgb_buffer = getbuf(rowstride*height)
        cdef uintptr_t y, uv
        cdef uint8_t *rgb
        cdef int r = 0
        rgb_buffer = getbuf(self.out_buffer_size)
        if not rgb_buffer:
            raise RuntimeError(f"failed to allocate {self.out_buffer_size} bytes for output buffer")
        log("convert_nv12_image(%s) to %s", image, self.dst_format)
        with buffer_context(pixels[0]) as y_buf:
            y = <uintptr_t> int(y_buf)
            with buffer_context(pixels[1]) as uv_buf:
                uv = <uintptr_t> int(uv_buf)
                rgb = <uint8_t*> rgb_buffer.get_mem()
                if self.dst_format=="RGB":
                    with nogil:
                        r = NV12ToRGB24(<const uint8_t*> y, y_stride,
                                        <const uint8_t*> uv, uv_stride,
                                        rgb, rowstride,
                                        width, height)
                elif self.dst_format=="BGRX":
                    with nogil:
                        r = NV12ToARGB(<const uint8_t*> y, y_stride,
                                        <const uint8_t*> uv, uv_stride,
                                        rgb, rowstride,
                                        width, height)
                elif self.dst_format=="RGBX":
                    with nogil:
                        r = NV12ToABGR(<const uint8_t*> y, y_stride,
                                        <const uint8_t*> uv, uv_stride,
                                        rgb, rowstride,
                                        width, height)
                else:
                    raise RuntimeError(f"unexpected dst format {self.dst_format}")
        if r!=0:
            raise RuntimeError(f"libyuv NV12ToRGB failed and returned {r}")
        cdef double elapsed = monotonic()-start
        log(f"libyuv.NV12 to {self.dst_format} took %.1fms", 1000.0*elapsed)
        self.time += elapsed
        return ImageWrapper(0, 0, self.dst_width, self.dst_height,
                            rgb_buffer, self.dst_format, Bpp*8, rowstride, Bpp, ImageWrapper.PACKED)

    def convert_bgrx_image(self, image):
        cdef uint8_t *output_buffer
        cdef uint8_t *out_planes[3]
        cdef uint8_t *scaled_buffer
        cdef uint8_t *scaled_planes[3]
        cdef int i
        cdef double start = monotonic()
        cdef int iplanes = image.get_planes()
        cdef int width = image.get_width()
        cdef int height = image.get_height()
        if iplanes!=ImageWrapper.PACKED:
            raise ValueError(f"invalid plane input format: {iplanes}")
        if width<self.src_width:
            raise ValueError(f"invalid image width: {width} (minimum is {self.src_width})")
        if height<self.src_height:
            raise ValueError(f"invalid image height: {height} (minimum is {self.src_height})")
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
                raise RuntimeError(f"failed to allocate {self.out_buffer_size} bytes for output buffer")
        for i in range(self.planes):
            #offsets are aligned, so this is safe and gives us aligned pointers:
            out_planes[i] = <uint8_t*> (memalign_ptr(<uintptr_t> output_buffer) + self.out_offsets[i])
        #get pointer to input:
        cdef int result = -1
        cdef const uint8_t* src
        with buffer_context(pixels) as bc:
            src = <const uint8_t*> (<uintptr_t> int(bc))
            with nogil:
                if self.planes==2:
                    result = ARGBToNV12(src, stride,
                                        out_planes[0], self.out_stride[0],
                                        out_planes[1], self.out_stride[1],
                                        width, height)
                else:
                    result = ARGBToJ420(src, stride,
                                        out_planes[0], self.out_stride[0],
                                        out_planes[1], self.out_stride[1],
                                        out_planes[2], self.out_stride[2],
                                        width, height)
        if result!=0:
            raise RuntimeError(f"libyuv ARGBToJ420/NV12 failed and returned {result}")
        cdef double elapsed = monotonic()-start
        log("libyuv.ARGBToI420/NV12 took %.1fms", 1000.0*elapsed)
        self.time += elapsed
        cdef object planes = []
        cdef object strides = []
        cdef object out_image
        if self.yuv_scaling:
            start = monotonic()
            scaled_buffer = <unsigned char*> memalign(self.scaled_buffer_size)
            if scaled_buffer==NULL:
                raise RuntimeError(f"failed to allocate {self.scaled_buffer_size} bytes for scaled buffer")
            with nogil:
                for i in range(self.planes):
                    scaled_planes[i] = scaled_buffer + self.scaled_offsets[i]
                    ScalePlane(out_planes[i], self.out_stride[i],
                               self.out_width[i], self.out_height[i],
                               scaled_planes[i], self.scaled_stride[i],
                               self.scaled_width[i], self.scaled_height[i],
                               self.filtermode)
            elapsed = monotonic()-start
            log("libyuv.ScalePlane %i times, took %.1fms", self.planes, 1000.0*elapsed)
            for i in range(self.planes):
                strides.append(self.scaled_stride[i])
                planes.append(PyMemoryView_FromMemory(<char *> scaled_planes[i], self.scaled_size[i], PyBUF_WRITE))
            self.frames += 1
            out_image = YUVImageWrapper(0, 0, self.dst_width, self.dst_height, planes, self.dst_format, 24, strides, 1, self.planes)
            out_image.cython_buffer = <uintptr_t> scaled_buffer
        else:
            #use output buffer directly:
            for i in range(self.planes):
                strides.append(self.out_stride[i])
                planes.append(PyMemoryView_FromMemory(<char *> out_planes[i], self.out_size[i], PyBUF_WRITE))
            self.frames += 1
            out_image = YUVImageWrapper(0, 0, self.dst_width, self.dst_height, planes, self.dst_format, 24, strides, 1, self.planes)
            out_image.cython_buffer = <uintptr_t> output_buffer
        return out_image


def selftest(full=False):
    global MAX_WIDTH, MAX_HEIGHT
    from xpra.codecs.codec_checks import testcsc, get_csc_max_size
    from xpra.codecs.libyuv import colorspace_converter
    maxw, maxh = MAX_WIDTH, MAX_HEIGHT
    testcsc(colorspace_converter, full)
    if full:
        mw, mh = get_csc_max_size(colorspace_converter, limit_w=32768, limit_h=32768)
        MAX_WIDTH = min(maxw, mw)
        MAX_HEIGHT = min(maxh, mh)
