# This file is part of Xpra.
# Copyright (C) 2013 Arthur Huillet
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, initializedcheck=False, cdivision=True, always_allow_keywords=False

import os
import sys
import time
from typing import Any, Tuple, List, Dict
from collections.abc import Sequence

from xpra.util.objects import typedict
from xpra.codecs.constants import CSCSpec, get_subsampling_divs
from xpra.codecs.image import ImageWrapper

from xpra.log import Logger
log = Logger("csc", "cython")

from libc.stdint cimport uint8_t, uintptr_t # pylint: disable=syntax-error
from xpra.buffers.membuf cimport memalign, memfree, buffer_context


cdef extern from "Python.h":
    object PyMemoryView_FromMemory(char *mem, Py_ssize_t size, int flags)
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags)
    void PyBuffer_Release(Py_buffer *view)
    int PyBUF_ANY_CONTIGUOUS
    int PyBUF_WRITE


cdef inline int roundup(int n, int m) noexcept nogil:
    return (n + m - 1) & ~(m - 1)


#precalculate indexes in native endianness:
cdef uint8_t BGRX_R, BGRX_G, BGRX_B, BGRX_X
cdef uint8_t RGBX_R, RGBX_G, RGBX_B, RGBX_X
cdef uint8_t RGB_R, RGB_G, RGB_B
cdef uint8_t BGR_R, BGR_G, BGR_B

if sys.byteorder=="little":
    BGRX_B, BGRX_G, BGRX_R, BGRX_X = (0, 1, 2, 3)
    RGBX_R, RGBX_G, RGBX_B, RGBX_X = (0, 1, 2, 3)
    BGR_R, BGR_G, BGR_B = (2, 1, 0)
    RGB_R, RGB_G, RGB_B = (0, 1, 2)
else:
    BGRX_B, BGRX_G, BGRX_R, BGRX_X = (0, 1, 2, 3)
    RGBX_R, RGBX_G, RGBX_B, RGBX_X = (0, 1, 2, 3)
    BGR_R, BGR_G, BGR_B = (0, 1, 2)
    RGB_R, RGB_G, RGB_B = (2, 1, 0)

log("csc_cython: %s endian:", sys.byteorder)
log("csc_cython: byteorder(BGRX)=%s", (BGRX_B, BGRX_G, BGRX_R, BGRX_X))
log("csc_cython: byteorder(RGBX)=%s", (RGBX_R, RGBX_G, RGBX_B, RGBX_X))
log("csc_cython: byteorder(RGB)=%s", (RGB_R, RGB_G, RGB_B))
log("csc_cython: byteorder(BGR)=%s", (BGR_R, BGR_G, BGR_B))

#COLORSPACES = {"BGRX" : ["YUV420P"], "YUV420P" : ["RGB", "BGR", "RGBX", "BGRX"], "GBRP" : ["RGBX", "BGRX"] }


def get_CS(in_cs, valid_options) -> Sequence[str]:
    v = os.environ.get("XPRA_CSC_CYTHON_%s_COLORSPACES" % in_cs)
    if v is None:
        return valid_options
    if not v:
        return ()
    env_override = []
    for cs in v.split(","):
        if cs in valid_options:
            env_override.append(cs)
        else:
            log.warn("invalid colorspace override for %s: %s (only supports: %s)", in_cs, cs, valid_options)
    log("environment override for %s: %s", in_cs, env_override)
    return env_override


COLORSPACES: Dict[str, Sequence[str]] = {
    "BGRX"       : get_CS("BGRX",    ["YUV420P", "YUV444P"]),
    "RGBX"       : get_CS("RGBX",    ["YUV420P", "YUV444P"]),
    "BGR"        : get_CS("BGR",     ["YUV420P", "YUV444P"]),
    "RGB"        : get_CS("RGB",     ["YUV420P", "YUV444P"]),
    "YUV420P"    : get_CS("YUV420P", ["RGB", "BGR", "RGBX", "BGRX"]),
    "GBRP"       : get_CS("GBRP",    ["RGBX", "BGRX"]),
    "r210"       : get_CS("r210",    ["YUV420P", "BGR48", "YUV444P10"]),
    "YUV444P10"  : get_CS("YUV444P10", ["r210"]),
    "YUV444P"    : get_CS("YUV444P",  ["BGRX", "RGBX"]),
    "GBRP10"     : get_CS("GBRP10",  ["r210", ]),
}


def get_type() -> str:
    return "cython"


def get_version() -> Tuple[int, int]:
    return (4, 2)


def get_info() -> Dict[str, Any]:
    return {
        "version"   : (4, 1),
    }


def get_specs() -> Sequence[CSCSpec]:
    specs: Sequence[CSCSpec] = []
    for in_cs, out_css in COLORSPACES.items():
        can_scale = True
        width_mask = height_mask = 0xFFFF
        for out_cs in out_css:
            if in_cs in ("r210", "YUV444P") or out_cs=="r210":
                can_scale = False
            elif in_cs == "GBRP10":
                can_scale = False
            if in_cs == "YUV420P":
                #safer not to try to handle odd dimensions as input:
                width_mask = height_mask = 0xFFFE
            # low score as this should be used as fallback only:
            specs.append(CSCSpec(
                    input_colorspace=in_cs, output_colorspaces=(out_cs, ),
                    codec_class=Converter, codec_type=get_type(),
                    quality=50, speed=0, setup_cost=0, min_w=2, min_h=2,
                    max_w=16*1024, max_h=16*1024,
                    can_scale=can_scale,
                    width_mask=width_mask, height_mask=height_mask)
                )
    return specs


class CythonImageWrapper(ImageWrapper):

    def free(self) -> None:
        log("CythonImageWrapper.free() cython_buffer=%#x", <uintptr_t> self.cython_buffer)
        super().free()
        cb = self.cython_buffer
        if cb>0:
            self.cython_buffer = 0
            memfree(<void *> (<uintptr_t> cb))

    def _cn(self):
        return "CythonImageWrapper"



DEF STRIDE_ROUNDUP = 2

#Pre-calculate some coefficients and define them as constants
#We use integer calculations so everything is multiplied by 2**16
#To get the result as a byte, we just bitshift:

# RGB to YUV full range
# Y = 0.299 * R + 0.587 * G + 0.114 * B
DEF YR = 19595      # 0.299 * 2**16
DEF YG = 38470      # 0.587 * 2**16
DEF YB = 7471       # 0.114 * 2**16
DEF Yc = 0
DEF YC = 0
# U = -0.169 * R - 0.331 * G + 0.500 * B
DEF UR = -11076     #-0.169 * 2**16
DEF UG = -21692     #-0.331 * 2**16
DEF UB = 32768      # 0.500 * 2**16
DEF Uc = 128
DEF UC = 8388608
# V = 0.500 * R - 0.419 * G - 0.081 * B
DEF VR = 32768      # 0.500  * 2**16
DEF VG = -27460     #-0.419 * 2**16
DEF VB = -5308      #-0.081  * 2**16
DEF Vc = 128
DEF VC = 8388608


DEF MAX_CLAMP = 16777216    #2**(16+8)
DEF MAX_CLAMP10 = 67108864  #2**(16+10)


# YUV to RGB full range:
# Y, Cb and Cr are adjusted as:
# Y'  = Y - 0
# Cb' = Cb - 128
# Cr' = Cr - 128
# (see YC, UC and VC above)
# RGB:
# R = 1*Y'                 + 1.403 * Cr'
# G = 1*Y' - 0.344   * Cb' - 0.714 * Cr'
# B = 1*Y' + 1.770   * Cb'
DEF RY = 65536      #1        * 2**16
DEF RU = 0
DEF RV = 91947      #1.403    * 2**16

DEF GY = 65536      #1        * 2**16
DEF GU = -22544     #-0.344   * 2**16
DEF GV = -46793     #-0.714   * 2**16

DEF BY = 65536      #1        * 2**16
DEF BU = 115999     #1.77     * 2**16
DEF BV = 0


# YUV to RGB studio range:
# Y, Cb and Cr are adjusted as:
# Y'  = Y - 16
# Cb' = Cb - 16 - (240 - 16) // 2 = Cb - 128
# Cr' = Cr - 16 - (240 - 16) // 2 = Cr - 128
# (see YC, UC and VC above)
DEF SYc = 16
DEF SUc = 128
DEF SVc = 128
# RGB:
# we need to scale up:
# Y by 255 // (235-16) = 1.1643835616438356
# UV by 255 // (240-16) = 1.1383928571428572
# R = 1.1643835616438356 * Y'                                  + 1.1383928571428572 * 1.403 * Cr'
# G = 1.1643835616438356 * Y' - 1.1383928571428572*0.344 * Cb' - 1.1383928571428572 * 0.714 * Cr'
# B = 1.1643835616438356 * Y' + 1.1383928571428572*1.770 * Cb'
DEF SRY = 76309      #1 * 1.1643835616438356          * 2**16
DEF SRU = 0
DEF SRV = 104672     #1.403 * 1.1383928571428572      * 2**16

DEF SGY = 76309      #1 * 1.1643835616438356          * 2**16
DEF SGU = -25664     #-0.344 * 1.1383928571428572     * 2**16
DEF SGV = -53268     #-0.714 * 1.1383928571428572     * 2**16

DEF SBY = 76309      #1 * 1.1643835616438356          * 2**16
DEF SBU = 132052     #1.77 * 1.1383928571428572       * 2**16
DEF SBV = 0


cdef inline unsigned char clamp(const long value) noexcept nogil:
    if value <= 0:
        return 0
    cdef long v = value + 2**15
    if v >= MAX_CLAMP:
        return 0xff         #2**8-1
    return <unsigned char> (v>>16)


cdef inline unsigned short clamp10(const long value) noexcept nogil:
    if value <= 0:
        return 0
    cdef long v = value + 2**15
    if v >= MAX_CLAMP10:
        return 0x3ff        #2**10-1
    return <unsigned short> (v>>16)


cdef inline unsigned char clamp_studio_UV(const long value) noexcept nogil:
    if value <= 0:
        return 16
    cdef long v = value + 2**15
    if v >= MAX_CLAMP:
        return 240
    # 240-16
    return <unsigned char> (16 + (v // 74898))


cdef inline unsigned char clamp_studio_Y(const long value) noexcept nogil:
    if value <= 0:
        return 16
    cdef long v = value + 2**15
    if v >= MAX_CLAMP:
        return 235
    # 235-16
    return <unsigned char> (16 + (v // 76608))


cdef inline void r210_to_BGR48_copy(unsigned short *bgr48, const unsigned int *r210,
                                    unsigned int w, unsigned int h,
                                    unsigned int src_stride, unsigned int dst_stride) noexcept nogil:
    cdef unsigned int y
    cdef unsigned int i
    cdef unsigned int v
    for y in range(h):
        i = y*dst_stride//2
        for x in range(w):
            v = r210[x]
            bgr48[i] = v&0x000003ff
            bgr48[i+1] = (v&0x000ffc00) >> 10
            bgr48[i+2] = (v&0x3ff00000) >> 20
            i += 3
        r210 = <unsigned int*> ((<uintptr_t> r210) + src_stride)


cdef inline void gbrp10_to_r210_copy(uintptr_t r210, uintptr_t[3] gbrp10,
                                     unsigned int width, unsigned int height,
                                     unsigned int src_stride, unsigned int dst_stride) noexcept nogil:
    cdef unsigned int x, y
    cdef unsigned short *b
    cdef unsigned short *g
    cdef unsigned short *r
    cdef unsigned int *dst
    for y in range(height):
        dst = <unsigned int*> (r210 + y*dst_stride)
        g = <unsigned short*> ((<uintptr_t> gbrp10[0]) + y*src_stride)
        b = <unsigned short*> ((<uintptr_t> gbrp10[1]) + y*src_stride)
        r = <unsigned short*> ((<uintptr_t> gbrp10[2]) + y*src_stride)
        for x in range(width):
            dst[x] = (b[x] & 0x3ff) + ((g[x] & 0x3ff)<<10) + ((r[x] & 0x3ff)<<20)


cdef inline void r210_to_YUV444P10_copy(unsigned short *Y, unsigned short *U, unsigned short *V, uintptr_t r210data,
                                        unsigned int width, unsigned int height,
                                        unsigned int Ystride, unsigned int Ustride, unsigned int Vstride,
                                        unsigned int r210_stride) noexcept nogil:
    cdef const unsigned int *r210_row
    cdef unsigned int r210
    cdef unsigned int R, G, B
    cdef unsigned int x, y
    for y in range(height):
        r210_row = <unsigned int*> (r210data + r210_stride*y)
        for x in range(width):
            r210 = r210_row[x]
            R = (r210&0x3ff00000) >> 20
            G = (r210&0x000ffc00) >> 10
            B = (r210&0x000003ff)
            Y[x] = clamp10(YR * R + YG * G + YB * B + YC*4)
            U[x] = clamp10(UR * R + UG * G + UB * B + UC*4)
            V[x] = clamp10(VR * R + VG * G + VB * B + VC*4)
        Y = <unsigned short *> ((<uintptr_t> Y) + Ystride)
        U = <unsigned short *> ((<uintptr_t> U) + Ustride)
        V = <unsigned short *> ((<uintptr_t> V) + Vstride)


cdef inline void YUV444P10_to_r210_copy(uintptr_t r210data, const unsigned short *Ybuf, const unsigned short *Ubuf, const unsigned short *Vbuf,
                                        unsigned int width, unsigned int height,
                                        unsigned int r210_stride,
                                        unsigned int Ystride, unsigned int Ustride, unsigned int Vstride) noexcept nogil:
        cdef unsigned short *Yrow
        cdef unsigned short *Urow
        cdef unsigned short *Vrow
        cdef short Y, U, V
        cdef unsigned int *r210row
        cdef unsigned int x, y
        for y in range(height):
            Yrow = <unsigned short*> ((<uintptr_t> Ybuf) + y*Ystride)
            Urow = <unsigned short*> ((<uintptr_t> Ubuf) + y*Ustride)
            Vrow = <unsigned short*> ((<uintptr_t> Vbuf) + y*Vstride)
            r210row = <unsigned int*> (r210data + y*r210_stride)
            for x in range(width):
                Y = (Yrow[x] & 0x3ff) - Yc*4
                U = (Urow[x] & 0x3ff) - Uc*4
                V = (Vrow[x] & 0x3ff) - Vc*4
                r210row[x] = (
                    (clamp10(RY * Y + RU * U + RV * V)<<20) |
                    (clamp10(GY * Y + GU * U + GV * V)<<10) |
                    (clamp10(BY * Y + BU * U + BV * V))
                    )


cdef inline void YUV444P_to_BGRX_copy(uintptr_t bgrxdata,
                                     const unsigned char *Ybuf, const unsigned char *Ubuf, const unsigned char *Vbuf,
                                     unsigned int width, unsigned int height,
                                     unsigned int rgb_stride,
                                     unsigned int Ystride, unsigned int Ustride, unsigned int Vstride,
                                     unsigned char full_range) noexcept nogil:
        cdef unsigned char *Yrow
        cdef unsigned char *Urow
        cdef unsigned char *Vrow
        cdef short Y, U, V
        cdef unsigned int *bgrxrow
        cdef unsigned int x, y
        if full_range:
            for y in range(height):
                Yrow = <unsigned char*> ((<uintptr_t> Ybuf) + y*Ystride)
                Urow = <unsigned char*> ((<uintptr_t> Ubuf) + y*Ustride)
                Vrow = <unsigned char*> ((<uintptr_t> Vbuf) + y*Vstride)
                bgrxrow = <unsigned int*> (bgrxdata + y*rgb_stride)
                for x in range(width):
                    Y = Yrow[x] - Yc
                    U = Urow[x] - Uc
                    V = Vrow[x] - Vc
                    bgrxrow[x] = (
                        (<unsigned int> (0xff)<<24) |
                        (clamp(RY * Y + RU * U + RV * V)<<16) |
                        (clamp(GY * Y + GU * U + GV * V)<<8) |
                        (clamp(BY * Y + BU * U + BV * V))
                    )
        else:
            for y in range(height):
                Yrow = <unsigned char*> ((<uintptr_t> Ybuf) + y*Ystride)
                Urow = <unsigned char*> ((<uintptr_t> Ubuf) + y*Ustride)
                Vrow = <unsigned char*> ((<uintptr_t> Vbuf) + y*Vstride)
                bgrxrow = <unsigned int*> (bgrxdata + y*rgb_stride)
                for x in range(width):
                    Y = Yrow[x] - SYc
                    U = Urow[x] - SUc
                    V = Vrow[x] - SVc
                    bgrxrow[x] = (
                        (<unsigned int> (0xff)<<24) |
                        (clamp(SRY * Y + SRU * U + SRV * V)<<16) |
                        (clamp(SGY * Y + SGU * U + SGV * V)<<8) |
                        (clamp(SBY * Y + SBU * U + SBV * V))
                    )


cdef inline void YUV444P_to_RGBX_copy(uintptr_t rgbxdata,
                                     const unsigned char *Ybuf, const unsigned char *Ubuf, const unsigned char *Vbuf,
                                     unsigned int width, unsigned int height,
                                     unsigned int rgb_stride,
                                     unsigned int Ystride, unsigned int Ustride, unsigned int Vstride,
                                     unsigned char full_range) noexcept nogil:
        cdef unsigned char *Yrow
        cdef unsigned char *Urow
        cdef unsigned char *Vrow
        cdef short Y, U, V
        cdef unsigned int *bgrxrow
        cdef unsigned int x, y
        if full_range:
            for y in range(height):
                Yrow = <unsigned char*> ((<uintptr_t> Ybuf) + y*Ystride)
                Urow = <unsigned char*> ((<uintptr_t> Ubuf) + y*Ustride)
                Vrow = <unsigned char*> ((<uintptr_t> Vbuf) + y*Vstride)
                rgbxrow = <unsigned int*> (rgbxdata + y*rgb_stride)
                for x in range(width):
                    Y = Yrow[x] - Yc
                    U = Urow[x] - Uc
                    V = Vrow[x] - Vc
                    rgbxrow[x] = (
                        (<unsigned int> 0xff<<24) |
                        (clamp(BY * Y + GU * U + GV * V)<<8) |
                        (clamp(GY * Y + RU * U + RV * V)<<16) |
                        (clamp(RY * Y + BU * U + BV * V))
                    )
        else:
            for y in range(height):
                Yrow = <unsigned char*> ((<uintptr_t> Ybuf) + y*Ystride)
                Urow = <unsigned char*> ((<uintptr_t> Ubuf) + y*Ustride)
                Vrow = <unsigned char*> ((<uintptr_t> Vbuf) + y*Vstride)
                rgbxrow = <unsigned int*> (rgbxdata + y*rgb_stride)
                for x in range(width):
                    Y = Yrow[x] - SYc
                    U = Urow[x] - SUc
                    V = Vrow[x] - SVc
                    rgbxrow[x] = (
                        (<unsigned int> 0xff<<24) |
                        (clamp(SBY * Y + SGU * U + SGV * V)<<8) |
                        (clamp(SGY * Y + SRU * U + SRV * V)<<16) |
                        (clamp(SRY * Y + SBU * U + SBV * V))
                    )


cdef class Converter:
    cdef unsigned int src_width
    cdef unsigned int src_height
    cdef object src_format
    cdef unsigned int dst_width
    cdef unsigned int dst_height
    cdef object dst_format
    cdef unsigned long[3] dst_strides
    cdef unsigned long[3] dst_sizes
    cdef unsigned long[3] offsets
    cdef unsigned char full_range

    cdef convert_image_function

    cdef unsigned long frames
    cdef double time
    cdef unsigned long buffer_size

    cdef object __weakref__

    def init_context(self, int src_width, int src_height, src_format: str,
                           int dst_width, int dst_height, dst_format: str, options: typedict) -> None:
        cdef int i
        assert src_format in COLORSPACES, "invalid input colorspace: %s (must be one of %s)" % (src_format, tuple(COLORSPACES.keys()))
        assert dst_format in COLORSPACES[src_format], "invalid output colorspace: %s (must be one of %s)" % (dst_format, COLORSPACES[src_format])
        log("csc_cython.Converter.init_context%s", (
            src_width, src_height, src_format, dst_width, dst_height, dst_format, options))
        self.src_width = src_width
        self.src_height = src_height
        self.dst_width = dst_width
        self.dst_height = dst_height
        self.src_format = src_format
        self.dst_format = dst_format
        self.full_range = options.boolget("full-range", True)

        self.time = 0
        self.frames = 0

        #explicitly clear all strides / sizes / offsets:
        for i in range(2):
            self.dst_strides[i] = 0
            self.dst_sizes[i]   = 0
            self.offsets[i]     = 0

        def assert_no_scaling() -> None:
            assert src_width==dst_width and src_height==dst_height, "scaling is not supported for %s to %s" % (src_format, dst_format)

        def allocate_yuv(fmt="YUV420P", Bpp=1) -> None:
            divs = get_subsampling_divs(fmt)
            assert divs, "invalid pixel format '%s'" % fmt
            for i, div in enumerate(divs):
                xdiv, ydiv = div
                self.dst_strides[i] = roundup(roundup(self.dst_width*Bpp, xdiv)//xdiv, STRIDE_ROUNDUP)
                self.dst_sizes[i] = self.dst_strides[i] * roundup(self.dst_height, ydiv)//ydiv
            #U channel follows Y with 1 line padding, V follows U with another line of padding:
            self.offsets[0] = 0
            self.offsets[1] = self.offsets[0] + self.dst_sizes[0] + self.dst_strides[0]
            self.offsets[2] = self.offsets[1] + self.dst_sizes[1] + self.dst_strides[1]
            #output buffer ends after V + 1 line of padding:
            self.buffer_size = self.offsets[2] + self.dst_sizes[2] + self.dst_strides[2]
            log("allocate_yuv(%s, %i) buffer_size=%s, sizes=%s, strides=%s",
                fmt, Bpp, self.buffer_size,
                (self.dst_sizes[0], self.dst_sizes[1], self.dst_sizes[2]),
                (self.dst_strides[0], self.dst_strides[1], self.dst_strides[2])
                )

        def allocate_rgb(Bpp=4) -> None:
            self.dst_strides[0] = roundup(self.dst_width*Bpp, STRIDE_ROUNDUP)
            self.dst_sizes[0] = self.dst_strides[0] * self.dst_height
            self.buffer_size = self.dst_sizes[0]+self.dst_strides[0]
            log("allocate_rgb(%i) buffer_size=%s, dst size=%s, stride=%s",
                Bpp, self.buffer_size, self.dst_sizes[0], self.dst_strides[0])

        if src_format in ("BGRX", "RGBX", "RGB", "BGR", "r210") and dst_format in ("YUV420P", "YUV444P"):
            if dst_format == "YUV420P":
                allocate_yuv(dst_format)
                if src_format=="BGRX":
                    self.convert_image_function = self.BGRX_to_YUV420P
                elif src_format=="RGBX":
                    self.convert_image_function = self.RGBX_to_YUV420P
                elif src_format=="BGR":
                    self.convert_image_function = self.BGR_to_YUV420P
                elif src_format=="RGB":
                    self.convert_image_function = self.RGB_to_YUV420P
                else:
                    assert src_format=="r210"
                    self.convert_image_function = self.r210_to_YUV420P
            elif dst_format == "YUV444P":
                allocate_yuv(dst_format)
                if src_format=="BGRX":
                    self.convert_image_function = self.BGRX_to_YUV444P
                elif src_format=="RGBX":
                    self.convert_image_function = self.RGBX_to_YUV444P
                elif src_format=="BGR":
                    self.convert_image_function = self.BGR_to_YUV444P
                elif src_format=="RGB":
                    self.convert_image_function = self.RGB_to_YUV444P
                else:
                    raise ValueError(f"unsupported dst format {dst_format} for {src_format}")
            else:
                raise ValueError(f"unsupported dst format {dst_format}")
        elif src_format=="r210" and dst_format=="BGR48":
            assert_no_scaling()
            allocate_rgb(6)
            self.convert_image_function = self.r210_to_BGR48
        elif src_format=="r210" and dst_format=="YUV444P10":
            assert_no_scaling()
            allocate_yuv(dst_format, 2)
            self.convert_image_function = self.r210_to_YUV444P10
        elif src_format=="YUV444P10" and dst_format=="r210":
            assert_no_scaling()
            allocate_rgb(4)
            self.convert_image_function = self.YUV444P10_to_r210
        elif src_format=="YUV444P" and (dst_format=="BGRX" or dst_format=="RGBX"):
            assert_no_scaling()
            allocate_rgb(3)
            self.convert_image_function = self.YUV444P_to_RGB
        elif src_format=="GBRP10" and dst_format=="r210":
            assert_no_scaling()
            allocate_rgb(4)
            self.convert_image_function = self.GBRP10_to_r210
        elif src_format=="YUV420P" and dst_format in ("RGBX", "BGRX", "RGB", "BGR"):
            #3 or 4 bytes per pixel:
            allocate_rgb(len(dst_format))
            if dst_format=="RGBX":
                self.convert_image_function = self.YUV420P_to_RGBX
            elif dst_format=="BGRX":
                self.convert_image_function = self.YUV420P_to_BGRX
            elif dst_format=="RGB":
                self.convert_image_function = self.YUV420P_to_RGB
            else:
                assert dst_format=="BGR"
                self.convert_image_function = self.YUV420P_to_BGR
        elif src_format=="GBRP" and dst_format in ("RGBX", "BGRX"):
            #4 bytes per pixel:
            allocate_rgb(4)
            if dst_format=="RGBX":
                self.convert_image_function = self.GBRP_to_RGBX
            else:
                assert dst_format=="BGRX"
                self.convert_image_function = self.GBRP_to_BGRX
        else:
            raise ValueError("BUG: src_format=%s, dst_format=%s", src_format, dst_format)

    def clean(self) -> None:
        # overzealous clean is cheap!
        cdef int i                          #
        self.src_width = 0
        self.src_height = 0
        self.dst_width = 0
        self.dst_height = 0
        self.src_format = ""
        self.dst_format = ""
        self.time = 0
        self.frames = 0
        for i in range(3):
            self.dst_strides[i] = 0
            self.dst_sizes[i] = 0
            self.offsets[i] = 0
        self.convert_image_function = None
        self.buffer_size = 0

    def is_closed(self) -> bool:
        return self.convert_image_function is None

    def get_info(self) -> Dict[str,Any]:
        info = {
                "frames"    : self.frames,
                "src_width" : self.src_width,
                "src_height": self.src_height,
                "dst_width" : self.dst_width,
                "dst_height": self.dst_height,
                }
        if self.src_format:
            info["src_format"] = self.src_format
        if self.dst_format:
            info["dst_format"] = self.dst_format
        if self.frames>0 and self.time>0:
            pps = float(self.src_width) * float(self.src_height) * float(self.frames) / self.time
            info["total_time_ms"] = int(self.time * 1000)
            info["pixels_per_second"] = int(pps)
        return info

    def __repr__(self):
        return "csc_cython(%s %sx%s - %s %sx%s)" % (self.src_format, self.src_width, self.src_height,
                                                 self.dst_format, self.dst_width, self.dst_height)

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
        return "cython"


    def convert_image(self, image: ImageWrapper) -> CythonImageWrapper:
        cdef double start = time.time()
        fn = self.convert_image_function
        r = fn(image)
        cdef double elapsed = time.time()-start
        log("%s took %.1fms", fn, 1000.0*elapsed)
        self.time += elapsed
        self.frames += 1
        return r


    def r210_to_YUV420P(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGB_to_YUV420P(image, 4, 0, 0, 0)

    def BGR_to_YUV420P(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGB_to_YUV420P(image, 3, BGR_R, BGR_G, BGR_B)

    def RGB_to_YUV420P(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGB_to_YUV420P(image, 3, RGB_B, RGB_G, RGB_R)

    def BGRX_to_YUV420P(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGB_to_YUV420P(image, 4, BGRX_R, BGRX_G, BGRX_B)

    def RGBX_to_YUV420P(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGB_to_YUV420P(image, 4, RGBX_B, RGBX_G, RGBX_R)

    cdef do_RGB_to_YUV420P(self,
                           image: ImageWrapper,
                           const uint8_t Bpp,
                           const uint8_t Rindex,
                           const uint8_t Gindex,
                           const uint8_t Bindex,
                           ):
        cdef const unsigned int *input_r210
        cdef unsigned int x,y,o
        cdef unsigned int sx, sy, ox, oy
        cdef unsigned unsigned int r210
        cdef unsigned char R, G, B
        cdef unsigned short Rsum, Gsum, Bsum
        cdef unsigned char count, dx, dy

        self.validate_rgb_image(image)
        pixels = image.get_pixels()
        cdef unsigned int input_stride = image.get_rowstride()
        log("do_RGB_to_YUV420P(%s, %i, %i, %i, %i) input=%s, strides=%s", image, Bpp, Rindex, Gindex, Bindex, len(pixels), input_stride)

        #allocate output buffer:
        cdef unsigned char *output_image = <unsigned char*> memalign(self.buffer_size)
        cdef unsigned char *Y = output_image + self.offsets[0]
        cdef unsigned char *U = output_image + self.offsets[1]
        cdef unsigned char *V = output_image + self.offsets[2]

        #copy to local variables (ensures C code will be optimized correctly)
        cdef unsigned int Ystride = self.dst_strides[0]
        cdef unsigned int Ustride = self.dst_strides[1]
        cdef unsigned int Vstride = self.dst_strides[2]
        cdef unsigned int src_width = self.src_width
        cdef unsigned int src_height = self.src_height
        cdef unsigned int dst_width = self.dst_width
        cdef unsigned int dst_height = self.dst_height
        cdef unsigned char full_range = self.full_range

        #we process 4 pixels at a time:
        cdef unsigned int workw = roundup(dst_width, 2)//2
        cdef unsigned int workh = roundup(dst_height, 2)//2

        cdef Py_buffer py_buf
        if PyObject_GetBuffer(pixels, &py_buf, PyBUF_ANY_CONTIGUOUS):
            raise ValueError("failed to read pixel data from %s" % type(pixels))
        cdef const unsigned char *input_image = <const unsigned char *> py_buf.buf

        #from now on, we can release the gil:
        if self.src_format=="r210":
            assert Bpp==4
            input_r210 = <unsigned int*> input_image
            with nogil:
                for y in range(workh):
                    for x in range(workw):
                        Rsum = Gsum = Bsum = 0
                        count = 0
                        for dy in range(2):
                            oy = y*2 + dy
                            if oy>=dst_height:
                                break
                            sy = oy*src_height//dst_height
                            for dx in range(2):
                                ox = x*2 + dx
                                if ox>=dst_width:
                                    break
                                sx = ox*src_width//dst_width
                                o = sy*input_stride + sx*Bpp
                                r210 = input_r210[o//4]
                                B = (r210&0x3ff00000) >> 22
                                G = (r210&0x000ffc00) >> 12
                                R = (r210&0x000003ff) >> 2
                                o = oy*Ystride + ox
                                Y[o] = clamp(YR * R + YG * G + YB * B + YC)
                                count += 1
                                Rsum += R
                                Gsum += G
                                Bsum += B
                        #write 1U and 1V:
                        if count>0:
                            U[y*Ustride + x] = clamp(UR * Rsum//count + UG * Gsum//count + UB * Bsum//count + UC)
                            V[y*Vstride + x] = clamp(VR * Rsum//count + VG * Gsum//count + VB * Bsum//count + VC)
        else:
            with nogil:
                for y in range(workh):
                    for x in range(workw):
                        Rsum = Gsum = Bsum = 0
                        count = 0
                        for dy in range(2):
                            oy = y*2 + dy
                            if oy>=dst_height:
                                break
                            sy = oy*src_height//dst_height
                            for dx in range(2):
                                ox = x*2 + dx
                                if ox>=dst_width:
                                    break
                                sx = ox*src_width//dst_width
                                o = sy*input_stride + sx*Bpp
                                R = input_image[o + Rindex]
                                G = input_image[o + Gindex]
                                B = input_image[o + Bindex]
                                o = oy*Ystride + ox
                                if full_range:
                                    Y[o] = clamp(YR * R + YG * G + YB * B + YC)
                                else:
                                    Y[o] = clamp_studio_Y(YR * R + YG * G + YB * B + YC)
                                count += 1
                                Rsum += R
                                Gsum += G
                                Bsum += B
                        #write 1U and 1V:
                        if count>0:
                            Rsum /= count
                            Gsum /= count
                            Bsum /= count
                            if full_range:
                                U[y*Ustride + x] = clamp(UR * Rsum + UG * Gsum + UB * Bsum + UC)
                                V[y*Vstride + x] = clamp(VR * Rsum + VG * Gsum + VB * Bsum + VC)
                            else:
                                U[y*Ustride + x] = clamp_studio_UV(UR * Rsum + UG * Gsum + UB * Bsum + UC)
                                V[y*Vstride + x] = clamp_studio_UV(VR * Rsum + VG * Gsum + VB * Bsum + VC)
        PyBuffer_Release(&py_buf)
        return self.planar3_image_wrapper(<void *> output_image)

    def BGR_to_YUV444P(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGB_to_YUV444P(image, 3, BGR_R, BGR_G, BGR_B)

    def RGB_to_YUV444P(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGB_to_YUV444P(image, 3, RGB_B, RGB_G, RGB_R)

    def BGRX_to_YUV444P(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGB_to_YUV444P(image, 4, BGRX_R, BGRX_G, BGRX_B)

    def RGBX_to_YUV444P(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGB_to_YUV444P(image, 4, RGBX_B, RGBX_G, RGBX_R)

    cdef do_RGB_to_YUV444P(self,
                           image: ImageWrapper,
                           const uint8_t Bpp,
                           const uint8_t Rindex,
                           const uint8_t Gindex,
                           const uint8_t Bindex,
                           ):
        cdef unsigned int x, y, o
        cdef unsigned int sx, sy
        cdef unsigned char R, G, B

        self.validate_rgb_image(image)
        pixels = image.get_pixels()
        cdef unsigned int input_stride = image.get_rowstride()
        log("do_RGB_to_YUV444P(%s, %i, %i, %i, %i) input=%s, strides=%s", image, Bpp, Rindex, Gindex, Bindex, len(pixels), input_stride)

        #allocate output buffer:
        cdef unsigned char *output_image = <unsigned char*> memalign(self.buffer_size)
        cdef unsigned char *Y = output_image + self.offsets[0]
        cdef unsigned char *U = output_image + self.offsets[1]
        cdef unsigned char *V = output_image + self.offsets[2]

        #copy to local variables (ensures C code will be optimized correctly)
        cdef unsigned int Ystride = self.dst_strides[0]
        cdef unsigned int Ustride = self.dst_strides[1]
        cdef unsigned int Vstride = self.dst_strides[2]
        cdef unsigned int src_width = self.src_width
        cdef unsigned int src_height = self.src_height
        cdef unsigned int dst_width = self.dst_width
        cdef unsigned int dst_height = self.dst_height
        cdef unsigned char full_range = self.full_range

        cdef const unsigned char *input_image
        cdef uintptr_t buf
        with buffer_context(pixels) as bc:
            input_image = <const unsigned char *> (<uintptr_t> int(bc))
            # buf_size = len(bc)
            with nogil:
                for y in range(dst_height):
                    for x in range(dst_width):
                        sx = x * src_width // dst_width
                        sy = y * src_height // dst_height
                        o = sy * input_stride + sx * Bpp
                        # assert o + Bpp <= buf_size
                        R = input_image[o + Rindex]
                        G = input_image[o + Gindex]
                        B = input_image[o + Bindex]
                        if full_range:
                            Y[y * Ystride + x] = clamp(YR * R + YG * G + YB * B + YC)
                            U[y * Ustride + x] = clamp(UR * R + UG * G + UB * B + UC)
                            V[y * Vstride + x] = clamp(VR * R + VG * G + VB * B + VC)
                        else:
                            Y[y * Ystride + x] = clamp_studio_Y(YR * R + YG * G + YB * B + YC)
                            U[y * Ustride + x] = clamp_studio_UV(UR * R + UG * G + UB * B + UC)
                            V[y * Vstride + x] = clamp_studio_UV(VR * R + VG * G + VB * B + VC)
        return self.planar3_image_wrapper(<void *> output_image)

    cdef object planar3_image_wrapper(self, void *buf, unsigned char bpp=24):
        #create python buffer from each plane:
        planes = []
        strides = []
        cdef unsigned char i
        for i in range(3):
            strides.append(self.dst_strides[i])
            planes.append(PyMemoryView_FromMemory(<char *> ((<uintptr_t> buf) + self.offsets[i]), self.dst_sizes[i], PyBUF_WRITE))
        out_image = CythonImageWrapper(0, 0, self.dst_width, self.dst_height,
                                       planes, self.dst_format, bpp, strides,
                                       planes=ImageWrapper.PLANAR_3)
        out_image.set_full_range(self.full_range)
        out_image.cython_buffer = <uintptr_t> buf
        return out_image

    def validate_rgb_image(self, image: ImageWrapper) -> None:
        assert image.get_planes()==ImageWrapper.PACKED, "invalid input format: %s planes" % image.get_planes()
        assert image.get_width()>=self.src_width, "invalid image width: %s (minimum is %s)" % (image.get_width(), self.src_width)
        assert image.get_height()>=self.src_height, "invalid image height: %s (minimum is %s)" % (image.get_height(), self.src_height)
        assert image.get_pixels(), "failed to get pixels from %s" % image

    def r210_to_YUV444P10(self, image: ImageWrapper) -> CythonImageWrapper:
        self.validate_rgb_image(image)
        pixels = image.get_pixels()
        cdef unsigned int input_stride = image.get_rowstride()
        log("r210_to_YUV444P10(%s) input=%s, strides=%s", image, len(pixels), input_stride)

        #allocate output buffer:
        cdef void *output_image = memalign(self.buffer_size)
        cdef unsigned short *Y = <unsigned short *> ((<uintptr_t> output_image) + self.offsets[0])
        cdef unsigned short *U = <unsigned short *> ((<uintptr_t> output_image) + self.offsets[1])
        cdef unsigned short *V = <unsigned short *> ((<uintptr_t> output_image) + self.offsets[2])
        #copy to local variables (ensures C code will be optimized correctly)
        cdef unsigned int Ystride = self.dst_strides[0]
        cdef unsigned int Ustride = self.dst_strides[1]
        cdef unsigned int Vstride = self.dst_strides[2]

        cdef uintptr_t buf
        with buffer_context(pixels) as bc:
            buf = <uintptr_t> int(bc)
            if image.is_thread_safe():
                with nogil:
                    r210_to_YUV444P10_copy(Y, U, V, buf,
                                           self.dst_width, self.dst_height,
                                           Ystride, Ustride, Vstride,
                                           input_stride)
            else:
                r210_to_YUV444P10_copy(Y, U, V, buf,
                                       self.dst_width, self.dst_height,
                                       Ystride, Ustride, Vstride,
                                       input_stride)
        return self.planar3_image_wrapper(output_image)

    def YUV444P10_to_r210(self, image: ImageWrapper) -> CythonImageWrapper:
        self.validate_planar3_image(image)
        planes = image.get_pixels()
        input_strides = image.get_rowstride()
        log("YUV444P10_to_r210(%s) strides=%s", image, input_strides)

        #copy to local variables:
        cdef unsigned int width = self.dst_width
        cdef unsigned int height = self.dst_height

        #allocate output buffer:
        cdef char *output_image = <char *> memalign(self.buffer_size)
        cdef unsigned int stride = self.dst_strides[0]

        cdef unsigned int YUVstrides[3]
        cdef Py_buffer py_buf[3]
        cdef const unsigned short * YUV[3]
        cdef int i
        for i in range(3):
            YUVstrides[i] = input_strides[i]
            if PyObject_GetBuffer(planes[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                raise ValueError("failed to read pixel data from %s" % type(planes[i]))
            YUV[i] = <const unsigned short *> py_buf[i].buf
            min_len = YUVstrides[i]*image.get_height()
            assert py_buf.len>=min_len, "buffer for Y plane is too small: %s bytes, expected at least %s" % (py_buf.len, min_len)

        if image.is_thread_safe():
            with nogil:
                YUV444P10_to_r210_copy(<uintptr_t> output_image, YUV[0], YUV[1], YUV[2],
                                       width, height,
                                       stride,
                                       YUVstrides[0], YUVstrides[1], YUVstrides[2])
        else:
            YUV444P10_to_r210_copy(<uintptr_t> output_image, YUV[0], YUV[1], YUV[2],
                                   width, height,
                                   stride,
                                   YUVstrides[0], YUVstrides[1], YUVstrides[2])
        for i in range(3):
            PyBuffer_Release(&py_buf[i])
        return self.packed_image_wrapper(output_image, 30)

    def YUV444P_to_RGB(self, image: ImageWrapper) -> CythonImageWrapper:
        self.validate_planar3_image(image)
        planes = image.get_pixels()
        input_strides = image.get_rowstride()
        log("YUV444P_to_RGB(%s) strides=%s", image, input_strides)

        #copy to local variables:
        cdef unsigned int width = self.dst_width
        cdef unsigned int height = self.dst_height

        #allocate output buffer:
        cdef char *output_image = <char *> memalign(self.buffer_size)
        cdef unsigned int stride = self.dst_strides[0]
        cdef unsigned char full_range = self.full_range

        cdef unsigned int YUVstrides[3]
        cdef Py_buffer py_buf[3]
        cdef const unsigned char * YUV[3]
        cdef int i
        for i in range(3):
            YUVstrides[i] = input_strides[i]
            if PyObject_GetBuffer(planes[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                raise ValueError("failed to read pixel data from %s" % type(planes[i]))
            YUV[i] = <const unsigned char *> py_buf[i].buf
            min_len = YUVstrides[i]*image.get_height()
            assert py_buf.len>=min_len, "buffer for Y plane is too small: %s bytes, expected at least %s" % (py_buf.len, min_len)

        assert self.dst_format=="BGRX" or self.dst_format=="RGBX"
        if image.is_thread_safe():
            if self.dst_format=="BGRX":
                with nogil:
                    YUV444P_to_BGRX_copy(<uintptr_t> output_image, YUV[0], YUV[1], YUV[2],
                                         width, height,
                                         stride,
                                         YUVstrides[0], YUVstrides[1], YUVstrides[2],
                                         full_range)
            else:
                with nogil:
                    YUV444P_to_RGBX_copy(<uintptr_t> output_image, YUV[0], YUV[1], YUV[2],
                                         width, height,
                                         stride,
                                         YUVstrides[0], YUVstrides[1], YUVstrides[2],
                                         full_range)
        else:
            if self.dst_format=="BGRX":
                YUV444P_to_BGRX_copy(<uintptr_t> output_image, YUV[0], YUV[1], YUV[2],
                                     width, height,
                                     stride,
                                     YUVstrides[0], YUVstrides[1], YUVstrides[2],
                                     full_range)
            else:
                YUV444P_to_RGBX_copy(<uintptr_t> output_image, YUV[0], YUV[1], YUV[2],
                                     width, height,
                                     stride,
                                     YUVstrides[0], YUVstrides[1], YUVstrides[2],
                                     full_range)
        for i in range(3):
            PyBuffer_Release(&py_buf[i])
        return self.packed_image_wrapper(output_image, 30)

    def r210_to_BGR48(self, image: ImageWrapper) -> CythonImageWrapper:
        self.validate_rgb_image(image)
        pixels = image.get_pixels()
        input_stride = image.get_rowstride()
        log("r210_to_BGR48(%s) input=%s, strides=%s", image, len(pixels), input_stride)

        #allocate output buffer:
        cdef unsigned short *bgr48 = <unsigned short*> memalign(self.dst_sizes[0])

        cdef unsigned int w = self.src_width
        cdef unsigned int h = self.src_height
        cdef unsigned int src_stride = image.get_rowstride()
        cdef unsigned int dst_stride = self.dst_strides[0]

        assert (dst_stride%2)==0

        cdef const unsigned int *r210
        with buffer_context(pixels) as bc:
            r210 = <const unsigned int*> (<uintptr_t> int(bc))
            if image.is_thread_safe():
                with nogil:
                    r210_to_BGR48_copy(bgr48, r210, w, h, src_stride, dst_stride)
            else:
                r210_to_BGR48_copy(bgr48, r210, w, h, src_stride, dst_stride)
        return self.packed_image_wrapper(<char *> bgr48, 48)

    cdef object packed_image_wrapper(self, char *buf, unsigned char bpp=24):
        pybuf = PyMemoryView_FromMemory(buf, self.dst_sizes[0], PyBUF_WRITE)
        out_image = CythonImageWrapper(0, 0, self.dst_width, self.dst_height, pybuf, self.dst_format, bpp, self.dst_strides[0], planes=ImageWrapper.PACKED)
        out_image.cython_buffer = <uintptr_t> buf
        return out_image

    def validate_planar3_image(self, image: ImageWrapper) -> None:
        assert image.get_planes()==ImageWrapper.PLANAR_3, "invalid input format: %s planes" % image.get_planes()
        assert image.get_width()>=self.src_width, "invalid image width: %s (minimum is %s)" % (image.get_width(), self.src_width)
        assert image.get_height()>=self.src_height, "invalid image height: %s (minimum is %s)" % (image.get_height(), self.src_height)
        assert image.get_pixels(), "failed to get pixels from %s" % image

    def GBRP10_to_r210(self, image: ImageWrapper) -> CythonImageWrapper:
        self.validate_planar3_image(image)
        pixels = image.get_pixels()
        input_strides = image.get_rowstride()
        cdef unsigned int w = self.src_width
        cdef unsigned int h = self.src_height
        cdef unsigned int src_stride = input_strides[0]
        cdef unsigned int dst_stride = self.dst_strides[0]
        assert input_strides[1]==src_stride and input_strides[2]==src_stride, "mismatch in rowstrides: %s" % (input_strides,)
        assert src_stride>=w*2
        assert dst_stride>=w*4
        assert self.dst_sizes[0]>=dst_stride*h

        #allocate output buffer:
        cdef unsigned int *r210 = <unsigned int*> memalign(self.dst_sizes[0])

        cdef uintptr_t gbrp10[3]
        cdef unsigned int i
        cdef Py_buffer py_buf[3]
        for i in range(3):
            if PyObject_GetBuffer(pixels[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                raise ValueError("failed to read pixel data from %s" % type(pixels[i]))
            gbrp10[i] = <uintptr_t> py_buf[i].buf
            assert (<unsigned long> py_buf[i].len)>=src_stride*h, "input plane '%s' is too small: %i bytes" % ("GBR"[i], py_buf[i].len)

        if image.is_thread_safe():
            with nogil:
                gbrp10_to_r210_copy(<uintptr_t> r210, gbrp10,
                                    w, h,
                                    src_stride, dst_stride)
        else:
            gbrp10_to_r210_copy(<uintptr_t> r210, gbrp10,
                                w, h,
                                src_stride, dst_stride)
        for i in range(3):
            PyBuffer_Release(&py_buf[i])
        return self.packed_image_wrapper(<char *> r210, 30)

    def YUV420P_to_RGBX(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_YUV420P_to_RGB(image, 4, RGBX_B, RGBX_G, RGBX_R, RGBX_X)

    def YUV420P_to_RGB(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_YUV420P_to_RGB(image, 3, RGB_B, RGB_G, RGB_R, 0)

    def YUV420P_to_BGRX(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_YUV420P_to_RGB(image, 4, BGRX_R, BGRX_G, BGRX_B, BGRX_X)

    def YUV420P_to_BGR(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_YUV420P_to_RGB(image, 3, BGR_R, BGR_G, BGR_B, 0)

    cdef do_YUV420P_to_RGB(self, image: ImageWrapper,
                           const uint8_t Bpp,
                           const uint8_t Rindex,
                           const uint8_t Gindex,
                           const uint8_t Bindex,
                           const uint8_t Xindex,
                           ):
        cdef unsigned int x,y,o
        cdef unsigned int sx, sy, ox, oy
        cdef unsigned char dx, dy
        cdef short Y, U, V

        self.validate_planar3_image(image)
        planes = image.get_pixels()
        input_strides = image.get_rowstride()
        log("do_YUV420P_to_RGB(%s) strides=%s", (image, Bpp, Rindex, Gindex, Bindex, Xindex), input_strides)

        #allocate output buffer:
        cdef unsigned char *output_image = <unsigned char*> memalign(self.buffer_size)

        #copy to local variables:
        cdef unsigned int stride = self.dst_strides[0]
        cdef unsigned int src_width = self.src_width
        cdef unsigned int src_height = self.src_height
        cdef unsigned int dst_width = self.dst_width
        cdef unsigned int dst_height = self.dst_height
        cdef unsigned int Ystride = input_strides[0]
        cdef unsigned int Ustride = input_strides[1]
        cdef unsigned int Vstride = input_strides[2]
        cdef Py_buffer py_buf[3]
        cdef int i
        for i in range(3):
            if PyObject_GetBuffer(planes[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                raise ValueError("failed to read pixel data from %s" % type(planes[i]))
            min_len = input_strides[i]*image.get_height()
            assert py_buf.len>=min_len, "buffer for Y plane is too small: %s bytes, expected at least %s" % (py_buf.len, min_len)
        cdef unsigned char *Ybuf = <unsigned char *> py_buf[0].buf
        cdef unsigned char *Ubuf = <unsigned char *> py_buf[1].buf
        cdef unsigned char *Vbuf = <unsigned char *> py_buf[2].buf
        cdef unsigned char full_range = self.full_range

        cdef unsigned char yc = Yc
        cdef unsigned char uc = Uc
        cdef unsigned char vc = Vc
        cdef int ry = RY, ru = RU, rv = RV
        cdef int gy = GY, gu = GU, gv = GV
        cdef int by = BY, bu = BU, bv = BV
        if not full_range:
            yc = SYc
            uc = SUc
            vc = SVc
            ry = SRY
            ru = SRU
            rv = SRV
            gy = SGY
            gu = SGU
            gv = SGV
            by = SBY
            bu = SBU
            bv = SBV

        #we process 4 pixels at a time:
        cdef unsigned int workw = roundup(dst_width//2, 2)
        cdef unsigned int workh = roundup(dst_height//2, 2)
        #from now on, we can release the gil:
        with nogil:
            for y in range(workh):
                for x in range(workw):
                    #assert x*2<=src_width and y*2<=src_height
                    #read U and V for the next 4 pixels:
                    sx = x*src_width//dst_width
                    sy = y*src_height//dst_height
                    U = Ubuf[sy*Ustride + sx] - uc
                    V = Vbuf[sy*Vstride + sx] - vc
                    #now read up to 4 Y values and write an RGBX pixel for each:
                    for dy in range(2):
                        oy = y*2 + dy
                        if oy>=dst_height:
                            break
                        sy = oy*src_height//dst_height
                        for dx in range(2):
                            ox = x*2 + dx
                            if ox>=dst_width:
                                break
                            sx = ox*src_width//dst_width
                            Y = Ybuf[sy*Ystride + sx] - yc
                            o = oy*stride + ox * Bpp
                            output_image[o + Rindex] = clamp(ry * Y + ru * U + rv * V)
                            output_image[o + Gindex] = clamp(gy * Y + gu * U + gv * V)
                            output_image[o + Bindex] = clamp(by * Y + bu * U + bv * V)
                            if Bpp==4:
                                output_image[o + Xindex] = 255
        for i in range(3):
            PyBuffer_Release(&py_buf[i])
        return self.packed_image_wrapper(<char *> output_image, 24)

    def GBRP_to_RGBX(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGBP_to_RGB(image, 2, 0, 1, RGBX_R, RGBX_G, RGBX_B, RGBX_X)

    def GBRP_to_BGRX(self, image: ImageWrapper) -> CythonImageWrapper:
        return self.do_RGBP_to_RGB(image, 2, 0, 1, RGBX_B, RGBX_G, RGBX_R, RGBX_X)

    cdef do_RGBP_to_RGB(self, image: ImageWrapper,
                        const uint8_t Rsrc,
                        const uint8_t Gsrc,
                        const uint8_t Bsrc,
                        const uint8_t Rdst,
                        const uint8_t Gdst,
                        const uint8_t Bdst,
                        const uint8_t Xdst,
                        ):
        cdef unsigned int x,y,o
        cdef unsigned int sx, sy
        cdef unsigned char *Gptr
        cdef unsigned char *Bptr
        cdef unsigned char *Rptr

        self.validate_planar3_image(image)
        planes = image.get_pixels()
        input_strides = image.get_rowstride()
        log("do_RGBP_to_RGB(%s) strides=%s", (image, Rsrc, Gsrc, Bsrc, Rdst, Gdst, Bdst, Xdst), input_strides)

        #allocate output buffer:
        cdef unsigned char *output_image = <unsigned char*> memalign(self.buffer_size)

        #copy to local variables:
        cdef unsigned int Rstride = input_strides[Rsrc]
        cdef unsigned int Gstride = input_strides[Gsrc]
        cdef unsigned int Bstride = input_strides[Bsrc]
        cdef unsigned int stride = self.dst_strides[0]
        cdef unsigned int src_width = self.src_width
        cdef unsigned int src_height = self.src_height
        cdef unsigned int dst_width = self.dst_width
        cdef unsigned int dst_height = self.dst_height
        cdef Py_buffer py_buf[3]
        cdef int i
        for i in range(3):
            if PyObject_GetBuffer(planes[i], &py_buf[i], PyBUF_ANY_CONTIGUOUS):
                raise ValueError("failed to read pixel data from %s" % type(planes[i]))
            min_len = input_strides[i]*image.get_height()
            assert py_buf.len>=min_len, "buffer for G plane is too small: %s bytes, expected at least %s" % (py_buf.len, min_len)
        cdef unsigned char *Gbuf = <unsigned char*> py_buf[Gsrc].buf
        cdef unsigned char *Bbuf = <unsigned char*> py_buf[Bsrc].buf
        cdef unsigned char *Rbuf = <unsigned char*> py_buf[Rsrc].buf

        #from now on, we can release the gil:
        with nogil:
            for y in range(dst_height):
                o = stride*y
                sy = y*src_height/dst_height
                Rptr  = Rbuf + (sy * Rstride)
                Gptr  = Gbuf + (sy * Gstride)
                Bptr  = Bbuf + (sy * Bstride)
                for x in range(dst_width):
                    sx = x*src_width/dst_width
                    output_image[o+Rdst] = Rptr[sx]
                    output_image[o+Gdst] = Gptr[sx]
                    output_image[o+Bdst] = Bptr[sx]
                    output_image[o+Xdst] = 255
                    o += 4
        for i in range(3):
            PyBuffer_Release(&py_buf[i])
        return self.packed_image_wrapper(<char *> output_image, 24)


def selftest(full=False):
    from xpra.codecs.checks import testcsc
    from xpra.codecs.csc_cython import converter
    testcsc(converter, full)
