# This file is part of Xpra.
# Copyright (C) 2013 Arthur Huillet
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#!python
#cython: boundscheck=False, wraparound=False, overflowcheck=False, cdivision=True, unraisable_tracebacks=True

import os
import time
import struct
try:
    from xpra.build_info import CYTHON_VERSION as CYTHON_VERSION_STR
    CYTHON_VERSION = CYTHON_VERSION_STR.split(".")
except ImportError:
    CYTHON_VERSION = []


from xpra.log import Logger
log = Logger("csc", "cython")

from xpra.codecs.codec_constants import csc_spec
from xpra.codecs.image_wrapper import ImageWrapper

cdef extern from "stdlib.h":
    void free(void *ptr)


cdef extern from "../../buffers/buffers.h":
    object memory_as_pybuffer(void* ptr, Py_ssize_t buf_len, int readonly)
    int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)
    int get_buffer_api_version()

cdef extern from "../../buffers/memalign.h":
    int pad(int size) nogil
    void *xmemalign(size_t size) nogil

from libc.stdint cimport uint8_t

cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)

#precalculate indexes in native endianness:
cdef uint8_t BGRX_R, BGRX_G, BGRX_B, BGRX_X
cdef uint8_t RGBX_R, RGBX_G, RGBX_B, RGBX_X
cdef uint8_t RGB_R, RGB_G, RGB_B
cdef uint8_t BGR_R, BGR_G, BGR_B
import sys
if sys.byteorder=="little":
    BGRX_B, BGRX_G, BGRX_R, BGRX_X = 0, 1, 2, 3
    RGBX_R, RGBX_G, RGBX_B, RGBX_X = 0, 1, 2, 3
    BGR_R, BGR_G, BGR_B = 2, 1, 0
    RGB_R, RGB_G, RGB_B = 0, 1, 2
else:
    BGRX_B, BGRX_G, BGRX_R, BGRX_X = 0, 1, 2, 3
    RGBX_R, RGBX_G, RGBX_B, RGBX_X = 0, 1, 2, 3
    BGR_R, BGR_G, BGR_B = 0, 1, 2
    RGB_R, RGB_G, RGB_B = 2, 1, 0

log("csc_cython: %s endian:", sys.byteorder)
log("csc_cython: byteorder(BGRX)=%s", (BGRX_B, BGRX_G, BGRX_R, BGRX_X))
log("csc_cython: byteorder(RGBX)=%s", (RGBX_R, RGBX_G, RGBX_B, RGBX_X))
log("csc_cython: byteorder(RGB)=%s", (RGB_R, RGB_G, RGB_B))
log("csc_cython: byteorder(BGR)=%s", (BGR_R, BGR_G, BGR_B))

#COLORSPACES = {"BGRX" : ["YUV420P"], "YUV420P" : ["RGB", "BGR", "RGBX", "BGRX"], "GBRP" : ["RGBX", "BGRX"] }
def get_CS(in_cs, valid_options):
    v = os.environ.get("XPRA_CSC_CYTHON_%s_COLORSPACES" % in_cs)
    if not v:
        return valid_options
    env_override = []
    for cs in v.split(","):
        if cs in valid_options:
            env_override.append(cs)
        else:
            log.warn("invalid colorspace override for %s: %s (only supports: %s)", in_cs, cs, valid_options)
    log("environment override for %s: %s", in_cs, env_override)
    return env_override
COLORSPACES = {"BGRX"       : get_CS("BGRX",    ["YUV420P"]),
               "RGBX"       : get_CS("RGBX",    ["YUV420P"]),
               "BGR"        : get_CS("BGR",     ["YUV420P"]),
               "RGB"        : get_CS("RGB",     ["YUV420P"]),
               "YUV420P"    : get_CS("YUV420P", ["RGB", "BGR", "RGBX", "BGRX"]),
               "GBRP"       : get_CS("GBRP",    ["RGBX", "BGRX"])}

DEBUG_POINTS = []
dp = os.environ.get("XPRA_CSC_CYTHON_DEBUG_POINTS", "")
if dp:
    for point in dp.split(","):
        try:
            pv = [int(x) for x in point.split("x")]
            assert len(pv)==2
            DEBUG_POINTS.append((pv[0], pv[1]))
        except:
            log.error("invalid debug point %s", point)

CSC_CYTHON_VERSION = [1]


def init_module():
    #nothing to do!
    log("csc_cython.init_module()")

def cleanup_module():
    log("csc_cython.cleanup_module()")

def get_type():
    return "cython"

def get_version():
    return tuple([str(x) for x in CSC_CYTHON_VERSION] + CYTHON_VERSION)

def get_info():
    info = {"version"   : CSC_CYTHON_VERSION,
            "buffer_api": get_buffer_api_version()}
    if CYTHON_VERSION:
        info["Cython"] = CYTHON_VERSION
    return info

def get_input_colorspaces():
    return COLORSPACES.keys()

def get_output_colorspaces(input_colorspace):
    return COLORSPACES[input_colorspace]

def get_spec(in_colorspace, out_colorspace):
    assert in_colorspace in COLORSPACES, "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, get_input_colorspaces())
    assert out_colorspace in COLORSPACES.get(in_colorspace), "invalid output colorspace: %s (must be one of %s)" % (out_colorspace, get_output_colorspaces(in_colorspace))
    #low score as this should be used as fallback only:
    return csc_spec(ColorspaceConverter, codec_type=get_type(), quality=50, speed=10, setup_cost=10, min_w=2, min_h=2, max_w=16*1024, max_h=16*1024, can_scale=True)


class CythonImageWrapper(ImageWrapper):

    def free(self):                             #@DuplicatedSignature
        log("CythonImageWrapper.free() cython_buffer=%#x", <unsigned long> self.cython_buffer)
        ImageWrapper.free(self)
        cb = self.cython_buffer
        if cb>0:
            self.cython_buffer = 0
            free(<void *> (<unsigned long> cb))

    def __repr__(self):
        return "csc_cython.CythonImageWrapper(%s:%s:%s)" % (self.pixel_format, self.get_geometry(), ImageWrapper.PLANE_NAMES.get(self.planes))



DEF STRIDE_ROUNDUP = 2

#Pre-calculate some coefficients and define them as constants
#We use integer calculations so everything is multipled by 2**16
#To get the result as a byte, we just bitshift:
DEF shift = 16

#RGB to YUV
#Y[o] = clamp(0.257 * R + 0.504 * G + 0.098 * B + 16)
# Y = 0.257 * R + 0.504 * G + 0.098 * B + 16
DEF YR = 16843      # 0.257 * 2**16
DEF YG = 33030      # 0.504 * 2**16
DEF YB = 6423       # 0.098 * 2**16
DEF Yc = 16
DEF YC = 1048576    # 16    * 2**16
#U[y*self.dst_strides[1] + x] = clamp(-0.148 * Rsum/sum - 0.291 * Gsum/sum + 0.439 * Bsum/sum + 128)
# U = -0.148 * R - 0.291 * G + 0.439 * B + 128
DEF UR = -9699      #-0.148 * 2**16
DEF UG = -19071     #-0.291 * 2**16
DEF UB = 28770      # 0.439 * 2**16
DEF Uc = 128
DEF UC = 8388608    # 128   * 2**16
#V[y*self.dst_strides[2] + x] = clamp(0.439 * Rsum/sum - 0.368 * Gsum/sum - 0.071 * Bsum/sum + 128)
# V = 0.439 * R - 0.368 * G - 0.071 * B + 128
DEF VR = 28770      # 0.439  * 2**16
DEF VG = -24117     #-0.368  * 2**16
DEF VB = -4653      #-0.071  * 2**16
DEF Vc = 128
DEF VC = 8388608    # 128    * 2**16

DEF max_clamp = 16777216    #2**(16+8)

#YUV to RGB:
#Y, Cb and Cr are adjusted as:
#Y'  = Y - 16
#Cb' = Cb - 128
#Cr' = Cr - 128
# (see YC, UC and VC above)
#RGB:
#R = 1.164*Y'                 + 1.596 * Cr'
#G = 1.164*Y' - 0.391   * Cb' - 0.813   * Cr'
#B = 1.164*Y' + 2.018   * Cb'

DEF RY = 76284      #1.164    * 2**16
DEF RU = 0
DEF RV = 104582     #1.5958   * 2**16

DEF GY = 76284      #1.164    * 2**16
DEF GU = -25672     #-0.39173 * 2**16
DEF GV = -53274     #-0.81290 * 2**16

DEF BY = 76284      #1.164    * 2**16
DEF BU = 132186     #2.017    * 2**16
DEF BV = 0


cdef inline unsigned char clamp(const long v) nogil:
    if v<=0:
        return 0
    elif v>=max_clamp:
        return 255
    else:
        return <unsigned char> (v>>shift)


cdef class ColorspaceConverter:
    cdef unsigned int src_width
    cdef unsigned int src_height
    cdef object src_format
    cdef unsigned int dst_width
    cdef unsigned int dst_height
    cdef object dst_format
    cdef unsigned long[3] dst_strides
    cdef unsigned long[3] dst_sizes
    cdef unsigned long[3] offsets

    cdef convert_image_function

    cdef unsigned long frames
    cdef double time
    cdef unsigned long buffer_size

    cdef object __weakref__

    def init_context(self, int src_width, int src_height, src_format,
                           int dst_width, int dst_height, dst_format, int speed=100):    #@DuplicatedSignature
        cdef int i
        assert src_format in get_input_colorspaces(), "invalid input colorspace: %s (must be one of %s)" % (src_format, get_input_colorspaces())
        assert dst_format in get_output_colorspaces(src_format), "invalid output colorspace: %s (must be one of %s)" % (dst_format, get_output_colorspaces(src_format))
        log("csc_cython.ColorspaceConverter.init_context%s", (src_width, src_height, src_format, dst_width, dst_height, dst_format, speed))
        self.src_width = src_width
        self.src_height = src_height
        self.dst_width = dst_width
        self.dst_height = dst_height
        self.src_format = src_format[:]
        self.dst_format = dst_format[:]

        self.time = 0
        self.frames = 0

        #explicity clear all strides / sizes / offsets:
        for i in range(2):
            self.dst_strides[i] = 0
            self.dst_sizes[i]   = 0
            self.offsets[i]     = 0

        if src_format in ("BGRX", "RGBX", "RGB", "BGR") and dst_format=="YUV420P":
            self.dst_strides[0] = roundup(self.dst_width,   STRIDE_ROUNDUP)
            self.dst_strides[1] = roundup(self.dst_width/2, STRIDE_ROUNDUP)
            self.dst_strides[2] = roundup(self.dst_width/2, STRIDE_ROUNDUP)
            self.dst_sizes[0] = self.dst_strides[0] * self.dst_height
            self.dst_sizes[1] = self.dst_strides[1] * self.dst_height/2
            self.dst_sizes[2] = self.dst_strides[2] * self.dst_height/2
            #U channel follows Y with 1 line padding, V follows U with another line of padding:
            self.offsets[0] = 0
            self.offsets[1] = self.dst_strides[0] * (self.dst_height+1)
            self.offsets[2] = self.offsets[1] + (self.dst_strides[1] * (self.dst_height/2+1))
            #output buffer ends after V + 1 line of padding:
            self.buffer_size = self.offsets[2] + (self.dst_strides[2] * (self.dst_height/2+1))
            if src_format=="BGRX":
                self.convert_image_function = self.BGRX_to_YUV420P
            elif src_format=="RGBX":
                self.convert_image_function = self.RGBX_to_YUV420P
            elif src_format=="BGR":
                self.convert_image_function = self.BGR_to_YUV420P
            else:
                assert src_format=="RGB"
                self.convert_image_function = self.RGB_to_YUV420P
        elif src_format=="YUV420P" and dst_format in ("RGBX", "BGRX", "RGB", "BGR"):
            #3 or 4 bytes per pixel:
            self.dst_strides[0] = roundup(self.dst_width*len(dst_format), STRIDE_ROUNDUP)
            self.dst_sizes[0] = self.dst_strides[0] * self.dst_height
            self.offsets[0] = 0
            #output buffer ends after 1 line of padding:
            self.buffer_size = self.dst_sizes[0] + roundup(dst_width*len(dst_format), STRIDE_ROUNDUP)

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
            self.dst_strides[0] = roundup(self.dst_width*4, STRIDE_ROUNDUP)
            self.dst_sizes[0] = self.dst_strides[0] * self.dst_height
            self.offsets[0] = 0
            #output buffer ends after 1 line of padding:
            self.buffer_size = self.dst_sizes[0] + roundup(dst_width*4, STRIDE_ROUNDUP)

            if dst_format=="RGBX":
                self.convert_image_function = self.GBRP_to_RGBX
            else:
                assert dst_format=="BGRX"
                self.convert_image_function = self.GBRP_to_BGRX
        else:
            raise Exception("BUG: src_format=%s, dst_format=%s", src_format, dst_format)

    def clean(self):                        #@DuplicatedSignature
        #overzealous clean is cheap!
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

    def is_closed(self):
        return bool(self.convert_image_function)

    def get_info(self):      #@DuplicatedSignature
        info = {
                "frames"    : self.frames,
                "src_width" : self.src_width,
                "src_height": self.src_height,
                "dst_width" : self.dst_width,
                "dst_height": self.dst_height}
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
        return "csc_cython(%s %sx%s - %s %sx%s)" % (self.src_format, self.src_width, self.src_height,
                                                 self.dst_format, self.dst_width, self.dst_height)

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
        return  "cython"


    def convert_image(self, image):
        return self.convert_image_function(image)


    def BGR_to_YUV420P(self, image):
        return self.do_RGB_to_YUV420P(image, 3, BGR_R, BGR_G, BGR_B)

    def RGB_to_YUV420P(self, image):
        return self.do_RGB_to_YUV420P(image, 3, RGB_R, RGB_G, RGB_B)

    def BGRX_to_YUV420P(self, image):
        return self.do_RGB_to_YUV420P(image, 4, BGRX_R, BGRX_G, BGRX_B)

    def RGBX_to_YUV420P(self, image):
        return self.do_RGB_to_YUV420P(image, 4, RGBX_R, RGBX_G, RGBX_B)

    cdef do_RGB_to_YUV420P(self, image, const uint8_t Bpp, const uint8_t Rindex, const uint8_t Gindex, const uint8_t Bindex):
        cdef Py_ssize_t pic_buf_len = 0
        cdef const unsigned char *input_image
        cdef unsigned char *output_image
        cdef unsigned int input_stride
        cdef unsigned int x,y,o             #@DuplicatedSignature
        cdef unsigned int sx, sy, ox, oy
        cdef unsigned int workw, workh
        cdef unsigned int Ystride, Ustride, Vstride
        cdef unsigned char R, G, B
        cdef unsigned short Rsum, Gsum, Bsum
        cdef unsigned char sum, i, dx, dy
        cdef unsigned char *Y
        cdef unsigned char *U
        cdef unsigned char *V

        start = time.time()
        iplanes = image.get_planes()
        assert iplanes==ImageWrapper.PACKED, "invalid input format: %s planes" % iplanes
        assert image.get_width()>=self.src_width, "invalid image width: %s (minimum is %s)" % (image.get_width(), self.src_width)
        assert image.get_height()>=self.src_height, "invalid image height: %s (minimum is %s)" % (image.get_height(), self.src_height)
        pixels = image.get_pixels()
        assert pixels, "failed to get pixels from %s" % image
        input_stride = image.get_rowstride()
        log("convert_image(%s) input=%s, strides=%s" % (image, len(pixels), input_stride))

        assert object_as_buffer(pixels, <const void**> &input_image, &pic_buf_len)==0
        #allocate output buffer:
        output_image = <unsigned char*> xmemalign(self.buffer_size)
        Y = output_image + self.offsets[0]
        U = output_image + self.offsets[1]
        V = output_image + self.offsets[2]

        #copy to local variables (ensures C code will be optimized correctly)
        Ystride = self.dst_strides[0]
        Ustride = self.dst_strides[1]
        Vstride = self.dst_strides[2]
        cdef unsigned int src_width = self.src_width
        cdef unsigned int src_height = self.src_height
        cdef unsigned int dst_width = self.dst_width
        cdef unsigned int dst_height = self.dst_height

        #we process 4 pixels at a time:
        workw = roundup(dst_width/2, 2)
        workh = roundup(dst_height/2, 2)
        #from now on, we can release the gil:
        with nogil:
            for y in range(workh):
                for x in range(workw):
                    R = G = B = 0
                    Rsum = Gsum = Bsum = 0
                    sum = 0
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
                            Y[o] = clamp(YR * R + YG * G + YB * B + YC)
                            sum += 1
                            Rsum += R
                            Gsum += G
                            Bsum += B
                    #write 1U and 1V:
                    if sum>0:
                        Rsum /= sum
                        Gsum /= sum
                        Bsum /= sum
                        U[y*Ustride + x] = clamp(UR * Rsum + UG * Gsum + UB * Bsum + UC)
                        V[y*Vstride + x] = clamp(VR * Rsum + VG * Gsum + VB * Bsum + VC)

        if DEBUG_POINTS:
            for x,y in DEBUG_POINTS:
                o = min(y, src_height)*input_stride + min(x, src_width) * Bpp
                log.info("RGB(%ix%i)=%3i, %3i, %3i  ->  YUV=%3i, %3i, %3i", x, y,
                         #RGB:
                         input_image[o + BGRX_R],
                         input_image[o + BGRX_G],
                         input_image[o + BGRX_B],
                         #Y:
                         Y[min(y, dst_height) * Ystride + min(x, dst_width)],
                         #U:
                         U[min(y, dst_height)//2 * Ustride + min(x, dst_width)//2],
                         #V:
                         V[min(y, dst_height)//2 * Vstride + min(x, dst_width)//2])

        #create python buffer from each plane:
        planes = []
        strides = []
        for i in range(3):
            strides.append(self.dst_strides[i])
            planes.append(memory_as_pybuffer(<void *> (<unsigned long> (output_image + self.offsets[i])), self.dst_sizes[i], True))
        elapsed = time.time()-start
        log("%s took %.1fms", self, 1000.0*elapsed)
        self.time += elapsed
        self.frames += 1
        out_image = CythonImageWrapper(0, 0, dst_width, dst_height, planes, self.dst_format, 24, strides, ImageWrapper._3_PLANES)
        out_image.cython_buffer = <unsigned long> output_image
        return out_image


    def YUV420P_to_RGBX(self, image):
        return self.do_YUV420P_to_RGB(image, 4, RGBX_R, RGBX_G, RGBX_B, RGBX_X)

    def YUV420P_to_RGB(self, image):
        return self.do_YUV420P_to_RGB(image, 3, RGB_R, RGB_G, RGB_B, 0)

    def YUV420P_to_BGRX(self, image):
        return self.do_YUV420P_to_RGB(image, 4, BGRX_R, BGRX_G, BGRX_B, BGRX_X)

    def YUV420P_to_BGR(self, image):
        return self.do_YUV420P_to_RGB(image, 3, BGR_R, BGR_G, BGR_B, 0)

    cdef do_YUV420P_to_RGB(self, image, const uint8_t Bpp, const uint8_t Rindex, const uint8_t Gindex, const uint8_t Bindex, const uint8_t Xindex):
        cdef Py_ssize_t buf_len = 0
        cdef unsigned char *output_image        #
        cdef unsigned int x,y,o                 #@DuplicatedSignature
        cdef unsigned int sx, sy, ox, oy
        cdef unsigned int workw, workh          #
        cdef unsigned int stride
        cdef unsigned char *Ybuf
        cdef unsigned char *Ubuf
        cdef unsigned char *Vbuf
        cdef unsigned char dx, dy
        cdef short Y, U, V
        cdef unsigned int Ystride, Ustride, Vstride      #
        cdef object rgb

        start = time.time()
        iplanes = image.get_planes()
        assert iplanes==ImageWrapper._3_PLANES, "invalid input format: %s planes" % iplanes
        assert image.get_width()>=self.src_width, "invalid image width: %s (minimum is %s)" % (image.get_width(), self.src_width)
        assert image.get_height()>=self.src_height, "invalid image height: %s (minimum is %s)" % (image.get_height(), self.src_height)
        planes = image.get_pixels()
        assert planes, "failed to get pixels from %s" % image
        input_strides = image.get_rowstride()
        log("do_YUV420P_to_RGB(%s) strides=%s", (image, Bpp, Rindex, Gindex, Bindex, Xindex), input_strides)

        #copy to local variables:
        stride = self.dst_strides[0]
        Ystride = input_strides[0]
        Ustride = input_strides[1]
        Vstride = input_strides[2]
        cdef unsigned int src_width = self.src_width
        cdef unsigned int src_height = self.src_height
        cdef unsigned int dst_width = self.dst_width
        cdef unsigned int dst_height = self.dst_height

        assert object_as_buffer(planes[0], <const void**> &Ybuf, &buf_len)==0, "failed to convert %s to a buffer" % type(planes[0])
        assert buf_len>=Ystride*image.get_height(), "buffer for Y plane is too small: %s bytes, expected at least %s" % (buf_len, Ystride*image.get_height())
        assert object_as_buffer(planes[1], <const void**> &Ubuf, &buf_len)==0, "failed to convert %s to a buffer" % type(planes[1])
        assert buf_len>=Ustride*image.get_height()//2, "buffer for U plane is too small: %s bytes, expected at least %s" % (buf_len, Ustride*image.get_height()/2)
        assert object_as_buffer(planes[2], <const void**> &Vbuf, &buf_len)==0, "failed to convert %s to a buffer" % type(planes[2])
        assert buf_len>=Vstride*image.get_height()//2, "buffer for V plane is too small: %s bytes, expected at least %s" % (buf_len, Vstride*image.get_height()/2)

        #allocate output buffer:
        output_image = <unsigned char*> xmemalign(self.buffer_size)

        #we process 4 pixels at a time:
        workw = roundup(dst_width//2, 2)
        workh = roundup(dst_height//2, 2)
        #from now on, we can release the gil:
        with nogil:
            for y in range(workh):
                for x in range(workw):
                    #assert x*2<=src_width and y*2<=src_height
                    #read U and V for the next 4 pixels:
                    sx = x*src_width//dst_width
                    sy = y*src_height//dst_height
                    U = Ubuf[sy*Ustride + sx] - Uc
                    V = Vbuf[sy*Vstride + sx] - Vc
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
                            Y = Ybuf[sy*Ystride + sx] - Yc
                            o = oy*stride + ox * Bpp
                            output_image[o + Rindex] = clamp(RY * Y + RU * U + RV * V)
                            output_image[o + Gindex] = clamp(GY * Y + GU * U + GV * V)
                            output_image[o + Bindex] = clamp(BY * Y + BU * U + BV * V)
                            if Bpp==4:
                                output_image[o + Xindex] = 255
        if DEBUG_POINTS:
            for x,y in DEBUG_POINTS:
                o = min(y, dst_height)*stride + min(x, dst_width) * Bpp
                log.info("YUV(%ix%i)=%3i, %3i, %3i  ->  RGB=%3i, %3i, %3i", x, y,
                         #Y:
                         Ybuf[min(y, src_height) * Ystride + min(x, src_width)],
                         #U:
                         Ubuf[min(y, src_height)//2 * Ustride + min(x, src_width)//2],
                         #V:
                         Vbuf[min(y, src_height)//2 * Vstride + min(x, src_width)//2],
                         #RGB:
                         output_image[o + Rindex],
                         output_image[o + Gindex],
                         output_image[o + Bindex])

        rgb = memory_as_pybuffer(<void *> output_image, self.dst_sizes[0], True)
        elapsed = time.time()-start
        log("%s took %.1fms", self, 1000.0*elapsed)
        self.time += elapsed
        self.frames += 1
        out_image = CythonImageWrapper(0, 0, dst_width, dst_height, rgb, self.dst_format, 24, stride, ImageWrapper.PACKED)
        out_image.cython_buffer = <unsigned long> output_image
        return out_image


    def GBRP_to_RGBX(self, image):
        return self.do_RGBP_to_RGB(image, 2, 0, 1, RGBX_R, RGBX_G, RGBX_B, RGBX_X)

    def GBRP_to_BGRX(self, image):
        return self.do_RGBP_to_RGB(image, 2, 0, 1, RGBX_B, RGBX_G, RGBX_R, RGBX_X)

    cdef do_RGBP_to_RGB(self, image, const uint8_t Rsrc, const uint8_t Gsrc, const uint8_t Bsrc,
                                     const uint8_t Rdst, const uint8_t Gdst, const uint8_t Bdst, const uint8_t Xdst):
        cdef Py_ssize_t buf_len = 0             #
        cdef unsigned char *output_image        #@DuplicatedSignature
        cdef unsigned int x,y,o                 #@DuplicatedSignature
        cdef unsigned int sx, sy                #@DuplicatedSignature
        cdef unsigned int stride                #@DuplicatedSignature
        cdef unsigned char *Gbuf                #@DuplicatedSignature
        cdef unsigned char *Gptr
        cdef unsigned char *Bbuf                #@DuplicatedSignature
        cdef unsigned char *Bptr
        cdef unsigned char *Rbuf                #@DuplicatedSignature
        cdef unsigned char *Rptr
        cdef unsigned char sum
        cdef unsigned int Gstride, Bstride, Rstride
        cdef object rgb                         #@DuplicatedSignature

        start = time.time()
        iplanes = image.get_planes()
        assert iplanes==ImageWrapper._3_PLANES, "invalid input format: %s planes" % iplanes
        assert image.get_width()>=self.src_width, "invalid image width: %s (minimum is %s)" % (image.get_width(), self.src_width)
        assert image.get_height()>=self.src_height, "invalid image height: %s (minimum is %s)" % (image.get_height(), self.src_height)
        planes = image.get_pixels()
        assert planes, "failed to get pixels from %s" % image
        input_strides = image.get_rowstride()
        log("do_RGBP_to_RGB(%s) strides=%s", (image, Rsrc, Gsrc, Bsrc, Rdst, Gdst, Bdst, Xdst), input_strides)

        #copy to local variables:
        Rstride = input_strides[Rsrc]
        Gstride = input_strides[Gsrc]
        Bstride = input_strides[Bsrc]
        stride = self.dst_strides[0]
        cdef unsigned int src_width = self.src_width
        cdef unsigned int src_height = self.src_height
        cdef unsigned int dst_width = self.dst_width
        cdef unsigned int dst_height = self.dst_height

        assert object_as_buffer(planes[Rsrc], <const void**> &Rbuf, &buf_len)==0
        assert buf_len>=Rstride*image.get_height(), "buffer for R plane is too small: %s bytes, expected at least %s" % (buf_len, Rstride*image.get_height())
        assert object_as_buffer(planes[Gsrc], <const void**> &Gbuf, &buf_len)==0
        assert buf_len>=Gstride*image.get_height(), "buffer for G plane is too small: %s bytes, expected at least %s" % (buf_len, Gstride*image.get_height())
        assert object_as_buffer(planes[Bsrc], <const void**> &Bbuf, &buf_len)==0
        assert buf_len>=Bstride*image.get_height(), "buffer for B plane is too small: %s bytes, expected at least %s" % (buf_len, Bstride*image.get_height())

        #allocate output buffer:
        output_image = <unsigned char*> xmemalign(self.buffer_size)

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

        rgb = memory_as_pybuffer(<void *> output_image, self.dst_sizes[0], True)
        elapsed = time.time()-start
        log("%s took %.1fms", self, 1000.0*elapsed)
        self.time += elapsed
        self.frames += 1
        out_image = CythonImageWrapper(0, 0, dst_width, dst_height, rgb, self.dst_format, 24, stride, ImageWrapper.PACKED)
        out_image.cython_buffer = <unsigned long> output_image
        return out_image


def selftest(full=False):
    from xpra.codecs.codec_checks import testcsc
    from xpra.codecs.csc_cython import colorspace_converter
    testcsc(colorspace_converter, full)
