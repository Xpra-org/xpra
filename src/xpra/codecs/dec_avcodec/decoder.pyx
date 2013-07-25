# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_AVCODEC_DEBUG")
error = log.error

from xpra.codecs.codec_constants import get_subsampling_divs, get_colorspace_from_avutil_enum, RGB_FORMATS
from xpra.codecs.image_wrapper import ImageWrapper

include "constants.pxi"

cdef extern from *:
    ctypedef unsigned long size_t
    ctypedef unsigned char uint8_t

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    object PyBuffer_FromMemory(void *ptr, Py_ssize_t size)
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1

cdef extern from "string.h":
    void * memcpy(void * destination, void * source, size_t num) nogil
    void * memset(void * ptr, int value, size_t num) nogil
    void free(void * ptr) nogil


ctypedef long AVPixelFormat

cdef extern from "libavcodec/avcodec.h":
    ctypedef struct AVCodecContext:
        int width
        int height
        AVPixelFormat pix_fmt
    ctypedef struct AVFrame:
        uint8_t **data
        int *linesize
        int format
    ctypedef struct AVCodec:
        pass
    ctypedef struct AVCodecID:
        pass
    ctypedef struct AVDictionary:
        pass
    ctypedef struct AVPacket:
        uint8_t *data
        int      size

    AVPixelFormat PIX_FMT_NONE
    AVCodecID CODEC_ID_H264

    void avcodec_register_all()
    AVCodec *avcodec_find_decoder(AVCodecID id)
    AVCodecContext *avcodec_alloc_context3(const AVCodec *codec)
    int avcodec_open2(AVCodecContext *avctx, const AVCodec *codec, AVDictionary **options)
    AVFrame *avcodec_alloc_frame()
    void avcodec_free_frame(AVFrame **frame)
    int avcodec_close(AVCodecContext *avctx)
    void av_free(void *ptr)

    void av_init_packet(AVPacket *pkt) nogil
    void avcodec_get_frame_defaults(AVFrame *frame) nogil
    int avcodec_decode_video2(AVCodecContext *avctx, AVFrame *picture,
                                int *got_picture_ptr, const AVPacket *avpkt) nogil

cdef extern from "dec_avcodec.h":
    char *get_avcodec_version()
    char **get_supported_colorspaces()

cdef extern from "../memalign/memalign.h":
    void *xmemalign(size_t size)


COLORSPACES = []
FORMAT_TO_ENUM = {}
ENUM_TO_FORMAT = {}
#populate mappings:
for pix_fmt, av_enum_str in {
        "YUV420P"   : "AV_PIX_FMT_YUV420P",
        "YUV422P"   : "AV_PIX_FMT_YUV422P",
        "YUV444P"   : "AV_PIX_FMT_YUV444P",        
        "RGB"       : "AV_PIX_FMT_RGB24",
        "XRGB"      : "AV_PIX_FMT_0RGB",
        "BGRX"      : "AV_PIX_FMT_BGR0",
        "ARGB"      : "AV_PIX_FMT_ARGB",
        "BGRA"      : "AV_PIX_FMT_BGRA",
        "GBRP"      : "AV_PIX_FMT_GBRP",
     }.items():
    if av_enum_str not in const:
        continue
    av_enum = const[av_enum_str]
    FORMAT_TO_ENUM[pix_fmt] = av_enum
    ENUM_TO_FORMAT[av_enum] = pix_fmt
    COLORSPACES.append(pix_fmt)

def get_colorspaces():
    return COLORSPACES

def get_version():
    return get_avcodec_version()


cdef class Decoder:
    cdef AVCodec *codec
    cdef AVCodecContext *codec_ctx
    cdef AVPixelFormat pix_fmt
    cdef AVPixelFormat actual_pix_fmt
    cdef AVFrame *frame
    cdef char *colorspace
    cdef object last_image

    def init_context(self, int width, int height, colorspace):
        assert colorspace in COLORSPACES, "invalid colorspace: %s" % colorspace
        self.colorspace = NULL
        for x in COLORSPACES:
            if x==colorspace:
                self.colorspace = x
                break
        if self.colorspace==NULL:
            error("invalid pixel format: %s", colorspace)
            return  False
        self.pix_fmt = FORMAT_TO_ENUM.get(colorspace, PIX_FMT_NONE)
        if self.pix_fmt==PIX_FMT_NONE:
            error("invalid pixel format: %s", colorspace)
            return  False
        self.actual_pix_fmt = self.pix_fmt

        avcodec_register_all()

        self.codec = avcodec_find_decoder(CODEC_ID_H264)
        if self.codec==NULL:
            error("codec H264 not found!")
            return  False
        #from here on, we have to call clean_decoder():
        self.codec_ctx = avcodec_alloc_context3(self.codec)
        if self.codec_ctx==NULL:
            error("failed to allocate codec context!")
            self.clean_decoder()
            return  False

        self.codec_ctx.width = width
        self.codec_ctx.height = height
        self.codec_ctx.pix_fmt = self.pix_fmt
        if avcodec_open2(self.codec_ctx, self.codec, NULL) < 0:
            error("could not open codec")
            self.clean_decoder()
            return  False

        self.frame = avcodec_alloc_frame()
        if self.frame==NULL:
            error("could not allocate an AVFrame for decoding")
            self.clean_decoder()
            return  False
        return True

    def clean(self):
        if self.last_image:
            #make sure the ImageWrapper does not reference memory
            #that is going to be freed!
            self.last_image.clone_pixel_data()
            self.last_image = None
        self.clean_decoder()

    def clean_decoder(self):
        if self.frame!=NULL:
            avcodec_free_frame(&self.frame)
            self.frame = NULL
        if self.codec_ctx==NULL:
            avcodec_close(self.codec_ctx)
            av_free(self.codec_ctx)
            self.codec_ctx = NULL


    def get_info(self):
        return {
                "width"     : self.get_width(),
                "height"    : self.get_height(),
                "type"      : self.get_type(),
                "colorspace": self.get_colorspace(),
                }

    def is_closed(self):
        return self.codec_ctx==NULL

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        assert self.codec_ctx!=NULL
        return self.codec_ctx.width

    def get_height(self):
        assert self.codec_ctx!=NULL
        return self.codec_ctx.height

    def get_type(self):
        return "x264"

    def decompress_image(self, input, options):
        cdef unsigned char * padded_buf = NULL
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int len = 0
        cdef int got_picture
        cdef AVPacket avpkt
        assert self.codec_ctx!=NULL
        assert self.codec!=NULL
        if self.last_image:
            #if another thread is still using this image
            #it is probably too late to prevent a race...
            #(it may be using the buffer directly by now)
            #but at least try to prevent new threads from
            #using the same buffer we are about to write to:
            self.last_image.clone_pixel_data()
            self.last_image = None
        #copy input buffer into padded C buffer:
        PyObject_AsReadBuffer(input, <const void**> &buf, &buf_len)
        padded_buf = <unsigned char *> xmemalign(buf_len+128)
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 128)
        #now safe to run without gil:
        with nogil:
            av_init_packet(&avpkt)
            avcodec_get_frame_defaults(self.frame)
            avpkt.data = <uint8_t *> padded_buf
            avpkt.size = buf_len
            len = avcodec_decode_video2(self.codec_ctx, self.frame, &got_picture, &avpkt)
            free(padded_buf)
        if len < 0:
            raise Exception("avcodec_decode_video2 failed to decode this frame")

        #actual pixfmt:
        if self.pix_fmt!=self.frame.format:
            self.actual_pix_fmt = self.frame.format
            debug("avcodec actual output pixel format is %s: %s" % (self.pix_fmt, self.get_actual_colorspace()))

        #print("decompress image: colorspace=%s / %s" % (self.colorspace, self.get_colorspace()))
        cs = self.get_actual_colorspace()
        if cs.endswith("P"):
            out = []
            strides = []
            outsize = 0
            divs = get_subsampling_divs(cs)
            nplanes = 3
            for i in range(nplanes):
                _, dy = divs[i]
                if dy==1:
                    height = self.codec_ctx.height
                elif dy==2:
                    height = (self.codec_ctx.height+1)>>1
                else:
                    raise Exception("invalid height divisor %s" % dy)
                stride = self.frame.linesize[i]
                size = height * stride
                outsize += size
                plane = PyBuffer_FromMemory(<void *>self.frame.data[i], size)
                out.append(plane)
                strides.append(stride)
        else:
            strides = self.frame.linesize[0]+self.frame.linesize[1]+self.frame.linesize[2]
            outsize = self.codec_ctx.height * strides
            out = PyBuffer_FromMemory(<void *>self.frame.data[0], outsize)
            nplanes = 0
        if outsize==0:
            raise Exception("output size is zero!")
        debug("avcodec: %s bytes of %s", outsize, cs)
        img = ImageWrapper(0, 0, self.codec_ctx.width, self.codec_ctx.height, out, cs, 24, strides, nplanes)
        self.last_image = img
        return img

    def get_colorspace(self):
        return self.colorspace

    def get_actual_colorspace(self):
        return ENUM_TO_FORMAT.get(self.actual_pix_fmt, "unknown/invalid")
