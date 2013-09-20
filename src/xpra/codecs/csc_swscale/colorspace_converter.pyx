# This file is part of Xpra.
# Copyright (C) 2013 Arthur Huillet
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_SWSCALE_DEBUG")
error = log.error

from xpra.codecs.codec_constants import codec_spec
from xpra.codecs.image_wrapper import ImageWrapper

include "constants.pxi"

cdef extern from "../memalign/memalign.h":
    int pad(int size) nogil
    void *xmemalign(size_t size) nogil

cdef extern from "stdlib.h":
    void free(void *ptr)

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    object PyBuffer_FromMemory(void *ptr, Py_ssize_t size)
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

ctypedef unsigned char uint8_t
ctypedef long AVPixelFormat
cdef extern from "csc_swscale.h":
    char *get_swscale_version()

cdef extern from "libavcodec/avcodec.h":
    AVPixelFormat PIX_FMT_NONE

ctypedef void SwsContext
cdef extern from "libswscale/swscale.h":
    ctypedef struct SwsFilter:
        pass

    SwsContext *sws_getContext(int srcW, int srcH, AVPixelFormat srcFormat,
                                int dstW, int dstH, AVPixelFormat dstFormat,
                                int flags, SwsFilter *srcFilter,
                                SwsFilter *dstFilter, const double *param)
    void sws_freeContext(SwsContext *context)

    int sws_scale(SwsContext *c, const uint8_t *const srcSlice[],
                  const int srcStride[], int srcSliceY, int srcSliceH,
                  uint8_t *const dst[], const int dstStride[]) nogil


def get_type():
    return "swscale"

def get_version():
    return get_swscale_version()


cdef class CSCPixelFormat:
    cdef AVPixelFormat av_enum
    cdef char* av_enum_name
    cdef float width_mult[4]
    cdef float height_mult[4]
    cdef char *pix_fmt
    def __init__(self, AVPixelFormat av_enum, char *av_enum_name, width_mult, height_mult, char *pix_fmt):
        self.av_enum = av_enum
        self.av_enum_name = av_enum_name
        for i in xrange(4):
            self.width_mult[i] = 0.0
            self.height_mult[i] = 0.0
        for i in xrange(4):
            self.width_mult[i] = width_mult[i]
            self.height_mult[i] = height_mult[i]
        self.pix_fmt = pix_fmt

#TODO: use a class!
COLORSPACES = []
#keeping this array in scope ensures the strings don't go away!
FORMAT_OPTIONS = [
    ("AV_PIX_FMT_NV12",     (1, 1, 0, 0),       (1, 0.5, 0, 0),     "NV12"),
    ("AV_PIX_FMT_RGB24",    (3, 0, 0, 0),       (1, 0, 0, 0),       "RGB"   ),
    ("AV_PIX_FMT_BGR24",    (3, 0, 0, 0),       (1, 0, 0, 0),       "BGR"   ),
    ("AV_PIX_FMT_0RGB",     (4, 0, 0, 0),       (1, 0, 0, 0),       "XRGB"  ),
    ("AV_PIX_FMT_BGR0",     (4, 0, 0, 0),       (1, 0, 0, 0),       "BGRX"  ),
    ("AV_PIX_FMT_ARGB",     (4, 0, 0, 0),       (1, 0, 0, 0),       "XRGB"  ),
    ("AV_PIX_FMT_BGRA",     (4, 0, 0, 0),       (1, 0, 0, 0),       "BGRX"  ),
    ("AV_PIX_FMT_YUV420P",  (1, 0.5, 0.5, 0),   (1, 0.5, 0.5, 0),   "YUV420P"),
    ("AV_PIX_FMT_YUV422P",  (1, 0.5, 0.5, 0),   (1, 1, 1, 0),       "YUV422P"),
    ("AV_PIX_FMT_YUV444P",  (1, 1, 1, 0),       (1, 1, 1, 0),       "YUV444P"),
    ("AV_PIX_FMT_GBRP",     (1, 1, 1, 0),       (1, 1, 1, 0),       "GBRP"   )
     ]
FORMATS = {}
for av_enum_name, width_mult, height_mult, pix_fmt in FORMAT_OPTIONS:
    av_enum = constants.get(av_enum_name)
    if av_enum is None:
        debug("av pixel mode %s is not available", av_enum_name)
        continue
    FORMATS[pix_fmt] = CSCPixelFormat(av_enum, av_enum_name, width_mult, height_mult, pix_fmt)
    if pix_fmt not in COLORSPACES:
        COLORSPACES.append(pix_fmt)
debug("swscale pixel formats: %s", FORMATS)
debug("colorspaces: %s", COLORSPACES)


cdef int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)


cdef class SWSFlags:
    cdef int flags
    cdef char* flags_strs[3]
    def __init__(self, int flags, flags_str):           #@DuplicatedSignature
        self.flags = flags
        cdef int i = 0
        for i in xrange(3):
            if i<len(flags_str):
                self.flags_strs[i] = flags_str[i]
            else:
                self.flags_strs[i] = NULL

    def get_flags(self):
        return self.flags


#keeping this array in scope ensures the strings don't go away!
FLAGS_OPTIONS = [
            (30, ("SWS_BICUBIC", "SWS_ACCURATE_RND")),
            (60, ("SWS_BICUBLIN", "SWS_ACCURATE_RND")),
            (80, ("SWS_FAST_BILINEAR", "SWS_ACCURATE_RND")),
        ]
cdef int flags                                          #@DuplicatedSignature
FLAGS = []
for speed, flags_strs in FLAGS_OPTIONS:
    flags = 0
    for flags_str in flags_strs:
        flag_val = constants.get(flags_str)
        if flag_val is None:
            log.warn("av flag %s is missing!", flags_str)
            continue
        debug("%s=%s", flags_str, flag_val)
        flags |= flag_val
    debug("%s=%s", flags_strs, flags)
    FLAGS.append((speed, SWSFlags(flags, flags_strs)))
debug("swscale flags: %s", FLAGS)


cdef get_swscale_flags(int speed):
    for s, swsflags in FLAGS:
        if s>=speed:
            return swsflags.get_flags()
    _, swsflags = FLAGS[-1]
    return swsflags.get_flags()

def get_swscale_flags_strs(int flags):
    strs = []
    for flag in ("SWS_BICUBIC", "SWS_BICUBLIN", "SWS_FAST_BILINEAR", "SWS_ACCURATE_RND"):
        flag_value = constants.get(flag, 0)
        if flag_value & flags>0:
            strs.append(flag)
    return strs


def get_input_colorspaces():
    return COLORSPACES

def get_output_colorspaces(input_colorspace):
    #exclude input colorspace:
    return [x for x in COLORSPACES if x!=input_colorspace]

def get_spec(in_colorspace, out_colorspace):
    assert in_colorspace in COLORSPACES, "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, COLORSPACES)
    assert out_colorspace in COLORSPACES, "invalid output colorspace: %s (must be one of %s)" % (out_colorspace, COLORSPACES)
    #setup cost is very low (usually less than 1ms!)
    #there are restrictions on dimensions (8x2 minimum!)
    #swscale can be used to scale (obviously)
    return codec_spec(ColorspaceConverter, codec_type=get_type(), setup_cost=20, min_w=8, min_h=2, can_scale=True)


cdef class CSCImage:
    """
        Allows us to call free_csc_image
        when this object is garbage collected
    """
    cdef uint8_t *buf[4]
    cdef int freed

    cdef set_plane(self, int plane, uint8_t *buf):
        assert plane in (0, 1, 2, 3)
        self.buf[plane] = buf

    def __dealloc__(self):
        #debug("CSCImage.__dealloc__()")
        self.free()

    def free(self):
        #debug("CSCImage.free() freed=%s", bool(self.freed))
        if self.freed==0:
            self.freed = 1
            if self.buf[0]==NULL:
                raise Exception("buffer is already freed!?")
            free(self.buf[0])
            for i in xrange(4):
                self.buf[i] = NULL


class CSCImageWrapper(ImageWrapper):

    def free(self):                             #@DuplicatedSignature
        debug("CSCImageWrapper.free() csc_image=%s", self.csc_image)
        ImageWrapper.free(self)
        if self.csc_image:
            self.csc_image.free()
            self.csc_image = None


cdef class ColorspaceConverter:
    cdef int src_width
    cdef int src_height
    cdef AVPixelFormat src_format_enum
    cdef char* src_format
    cdef int dst_width
    cdef int dst_height
    cdef AVPixelFormat dst_format_enum
    cdef char* dst_format

    cdef int frames
    cdef double time
    cdef SwsContext *context
    cdef int flags                              #@DuplicatedSignature

    cdef int out_height[4]
    cdef int out_stride[4]
    cdef int out_size[4]
    cdef int buffer_size

    def init_context(self, int src_width, int src_height, src_format,
                           int dst_width, int dst_height, dst_format, int speed=100):    #@DuplicatedSignature
        debug("swscale.ColorspaceConverter.init_context%s", (src_width, src_height, src_format, dst_width, dst_height, dst_format, speed))
        cdef CSCPixelFormat src
        cdef CSCPixelFormat dst
        #src:
        src = FORMATS.get(src_format)
        debug("source format=%s", src)
        assert src, "invalid source format: %s" % src_format
        self.src_format = src.pix_fmt
        self.src_format_enum = src.av_enum
        #dst:
        dst = FORMATS.get(dst_format)
        debug("destination format=%s", dst)
        assert dst, "invalid destination format: %s" % dst_format
        self.dst_format = dst.pix_fmt
        self.dst_format_enum = dst.av_enum
        #pre-calculate plane heights:
        self.buffer_size = 0
        for i in range(4):
            self.out_height[i] = (int) (dst_height * dst.height_mult[i])
            self.out_stride[i] = roundup((int) (dst_width * dst.width_mult[i]), 4)
            #add one extra line to height so we can read a full rowstride
            #no matter where we start to read on the last line.
            #MEMALIGN may be redundant here but it is very cheap
            if dst_format=="NV12" and i==0:
                #no padding: packed UV plane follows Y plane
                self.out_size[i] = self.out_stride[i] * self.out_height[i]
            else:
                self.out_size[i] = pad(self.out_stride[i] * (self.out_height[i]+1))
            self.buffer_size += self.out_size[i]
        debug("buffer size=%s", self.buffer_size)

        self.src_width = src_width
        self.src_height = src_height
        self.dst_width = dst_width
        self.dst_height = dst_height

        self.flags = get_swscale_flags(speed)
        self.time = 0
        self.frames = 0

        self.context = sws_getContext(self.src_width, self.src_height, self.src_format_enum,
                                      self.dst_width, self.dst_height, self.dst_format_enum,
                                      self.flags, NULL, NULL, NULL)
        debug("sws context=%s", hex(<long> self.context))
        assert self.context!=NULL, "sws_getContext returned NULL"

    def get_info(self):
        info = {
                "flags"     : get_swscale_flags_strs(self.flags),
                "frames"    : self.frames,
                "src_width" : self.src_width,
                "src_height": self.src_height,
                "src_format": self.src_format,
                "dst_width" : self.dst_width,
                "dst_height": self.dst_height,
                "dst_format": self.dst_format}
        if self.frames>0 and self.time>0:
            pps = float(self.src_width) * float(self.src_height) * float(self.frames) / self.time
            info["total_time_ms"] = int(self.time*1000.0)
            info["pixels_per_second"] = int(pps)
        return info

    def __str__(self):
        if self.src_format==NULL or self.dst_format==NULL:
            return "swscale(uninitialized)"
        return "swscale(%s %sx%s - %s %sx%s)" % (self.src_format, self.src_width, self.src_height,
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
        return  "swscale"


    def clean(self):                        #@DuplicatedSignature
        debug("swscale.ColorspaceConverter.clean()")
        if self.context!=NULL:
            sws_freeContext(self.context)
            self.context = NULL

    def convert_image(self, image):
        cdef Py_ssize_t pic_buf_len = 0
        assert self.context!=NULL
        cdef const uint8_t *input_image[4]
        cdef uint8_t *output_image[4]
        cdef int input_stride[4]
        cdef int iplanes,oplanes
        cdef int i                          #@DuplicatedSignature
        cdef int height
        cdef int stride
        cdef int result
        start = time.time()
        iplanes = image.get_planes()
        assert iplanes in ImageWrapper.PLANE_OPTIONS, "invalid number of planes: %s" % iplanes
        input = image.get_pixels()
        strides = image.get_rowstride()
        if iplanes==ImageWrapper.PACKED:
            #magic: repack raw pixels/rowstride:
            input = [input]
            strides = [strides]
            iplanes = 1
        #print("convert_image(%s) input=%s, strides=%s" % (image, len(input), strides))
        assert len(input)==iplanes, "expected %s planes but found %s" % (iplanes, len(input))
        assert len(strides)==iplanes, "expected %s rowstrides but found %s" % (iplanes, len(strides))
        for i in xrange(4):
            if i<iplanes:
                input_stride[i] = strides[i]
                PyObject_AsReadBuffer(input[i], <const void**> &input_image[i], &pic_buf_len)
            else:
                input_stride[i] = 0
                input_image[i] = NULL
        with nogil:
            output_image[0] = <uint8_t*> xmemalign(self.buffer_size)
            for i in xrange(3):
                output_image[1+i] = output_image[i] + self.out_size[i]
            result = sws_scale(self.context, input_image, input_stride, 0, self.src_height, output_image, self.out_stride)
        assert result==self.dst_height, "invalid output height: %s, expected %s" % (result, self.dst_height)
        #now parse the output:
        csci = CSCImage()           #keep a reference to memory for cleanup
        for i in range(4):
            csci.set_plane(i, NULL)
        if self.dst_format.endswith("P"):
            #planar mode, assume 3 planes:
            oplanes = ImageWrapper._3_PLANES
            out = []
            strides = []
            for i in range(3):
                if self.out_stride[i]>0 and output_image[i]!=NULL:
                    stride = self.out_stride[i]
                    plane = PyBuffer_FromMemory(<void *>output_image[i], self.out_height[i] * self.out_stride[i])
                else:
                    stride = 0
                    plane = None
                csci.set_plane(i, output_image[i])
                out.append(plane)
                strides.append(stride)
        elif str(self.dst_format)=="NV12":
            #Y plane, followed by U and V packed
            oplanes = ImageWrapper.PACKED
            strides = self.out_stride[0]
            out = PyBuffer_FromMemory(<void *>output_image[0], self.buffer_size)
            csci.set_plane(0, output_image[0])
        else:
            #assume no planes, plain RGB packed pixels:
            oplanes = ImageWrapper.PACKED
            strides = self.out_stride[0]
            out = PyBuffer_FromMemory(<void *>output_image[0], self.out_height[0] * self.out_stride[0])
            csci.set_plane(0, output_image[0])
        elapsed = time.time()-start
        debug("%s took %.1fms", self, 1000.0*elapsed)
        self.time += elapsed
        self.frames += 1
        out_image = CSCImageWrapper(0, 0, self.dst_width, self.dst_height, out, self.dst_format, 24, strides, oplanes)
        out_image.csc_image = csci
        return out_image
