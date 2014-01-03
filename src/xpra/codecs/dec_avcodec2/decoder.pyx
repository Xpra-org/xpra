# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import weakref
from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_AVCODEC_DEBUG")
error = log.error

#some consumers need a writeable buffer (ie: OpenCL...)
READ_ONLY = False

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
    object PyBuffer_FromReadWriteMemory(void *ptr, Py_ssize_t size)
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1


cdef extern from "string.h":
    void * memcpy(void * destination, void * source, size_t num) nogil
    void * memset(void * ptr, int value, size_t num) nogil
    void free(void * ptr) nogil


cdef extern from "../inline.h":
    pass

cdef extern from "../memalign/memalign.h":
    void *xmemalign(size_t size)


ctypedef long AVPixelFormat


cdef extern from "libavutil/mem.h":
    void av_free(void *ptr)

cdef extern from "libavutil/error.h":
    int av_strerror(int errnum, char *errbuf, size_t errbuf_size)

cdef extern from "libavcodec/version.h":
    int LIBAVCODEC_VERSION_MAJOR
    int LIBAVCODEC_VERSION_MINOR
    int LIBAVCODEC_VERSION_MICRO

cdef extern from "libavcodec/avcodec.h":
    ctypedef struct AVFrame:
        uint8_t **data
        int *linesize
        int format
        void *opaque
    ctypedef struct AVCodec:
        pass
    ctypedef struct AVCodecID:
        pass
    ctypedef struct AVDictionary:
        pass
    ctypedef struct AVPacket:
        uint8_t *data
        int      size

    ctypedef struct AVCodecContext:
        int width
        int height
        AVPixelFormat pix_fmt
        int thread_safe_callbacks
        int thread_count
        int thread_type
        int flags
        int flags2
        int refcounted_frames

    AVPixelFormat PIX_FMT_NONE
    AVCodecID CODEC_ID_H264
    AVCodecID CODEC_ID_VP8
    #AVCodecID CODEC_ID_VP9

    #init and free:
    void avcodec_register_all()
    AVCodec *avcodec_find_decoder(AVCodecID id)
    AVCodecContext *avcodec_alloc_context3(const AVCodec *codec)
    int avcodec_open2(AVCodecContext *avctx, const AVCodec *codec, AVDictionary **options)
    AVFrame* av_frame_alloc()
    void av_frame_free(AVFrame **frame)
    int avcodec_close(AVCodecContext *avctx)

    #actual decoding:
    void av_init_packet(AVPacket *pkt) nogil
    void avcodec_get_frame_defaults(AVFrame *frame) nogil
    int avcodec_decode_video2(AVCodecContext *avctx, AVFrame *picture,
                                int *got_picture_ptr, const AVPacket *avpkt) nogil

    void av_frame_unref(AVFrame *frame) nogil


def get_version():
    return (LIBAVCODEC_VERSION_MAJOR, LIBAVCODEC_VERSION_MINOR, LIBAVCODEC_VERSION_MICRO)

def get_type():
    return "avcodec2"


COLORSPACES = None
FORMAT_TO_ENUM = {}
ENUM_TO_FORMAT = {}
def init_colorspaces():
    global COLORSPACES
    if COLORSPACES is not None:
        #done already!
        return
    #populate mappings:
    COLORSPACES = []
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
        av_enum = constants.get(av_enum_str)
        if av_enum is None:
            debug("colorspace format %s (%s) not supported by avcodec", pix_fmt, av_enum_str)
            continue
        FORMAT_TO_ENUM[pix_fmt] = av_enum
        ENUM_TO_FORMAT[av_enum] = pix_fmt
        COLORSPACES.append(pix_fmt)
    debug("colorspaces supported by avcodec %s: %s", get_version(), COLORSPACES)
    if len(COLORSPACES)==0:
        error("avcodec installation problem: no colorspaces found!")

def get_colorspaces():
    init_colorspaces()
    return COLORSPACES

CODECS = None
def get_encodings():
    global CODECS
    if CODECS is None:
        avcodec_register_all()
        CODECS = []
        if avcodec_find_decoder(CODEC_ID_H264)!=NULL:
            CODECS.append("h264")
        if avcodec_find_decoder(CODEC_ID_VP8)!=NULL:
            CODECS.append("vp8")
        #if avcodec_find_decoder(CODEC_ID_VP9)!=NULL:
        #    CODECS.append("vp9")
    return CODECS


cdef void clear_frame(AVFrame *frame):
    assert frame!=NULL, "frame is not set!"
    for i in xrange(4):
        frame.data[i] = NULL


cdef class AVFrameWrapper:
    """
        Wraps an AVFrame so we can free it
        once both xpra and avcodec are done with it.
    """
    cdef AVCodecContext *avctx
    cdef AVFrame *frame
    cdef int xpra_freed

    cdef set_context(self, AVCodecContext *avctx, AVFrame *frame):
        self.avctx = avctx
        self.frame = frame
        debug("%s.set_context(%s, %s)", self, hex(<unsigned long> avctx), hex(<unsigned long> frame))

    def __dealloc__(self):
        #By the time this wrapper is garbage collected,
        #we must have freed it!
        assert self.frame==NULL and self.avctx==NULL, "frame was freed by both, but not actually freed!"

    def __str__(self):
        if self.frame==NULL:
            return "AVFrameWrapper(NULL)"
        return "AVFrameWrapper(%s)" % hex(<unsigned long> self.frame)

    def xpra_free(self):
        debug("%s.xpra_free()", self)
        self.free()

    cdef free(self):
        debug("%s.free() context=%s, frame=%s", self, hex(<unsigned long> self.avctx), hex(<unsigned long> self.frame))
        if self.avctx!=NULL and self.frame!=NULL:
            av_frame_unref(self.frame)
            self.frame = NULL
            self.avctx = NULL


class AVImageWrapper(ImageWrapper):
    """
        Wrapper which allows us to call xpra_free on the decoder
        when the image is freed, or once we have made a copy of the pixels.
    """

    def __str__(self):                          #@DuplicatedSignature
        return ImageWrapper.__str__(self)+"-(%s)" % self.av_frame

    def free(self):                             #@DuplicatedSignature
        debug("AVImageWrapper.free()")
        ImageWrapper.free(self)
        self.xpra_free_frame()

    def clone_pixel_data(self):
        debug("AVImageWrapper.clone_pixel_data()")
        ImageWrapper.clone_pixel_data(self)
        self.xpra_free_frame()

    def xpra_free_frame(self):
        debug("AVImageWrapper.xpra_free_frame() av_frame=%s", self.av_frame)
        if self.av_frame:
            self.av_frame.xpra_free()
            self.av_frame = None



cdef class Decoder:
    """
        This wraps the AVCodecContext and its configuration,
        also tracks AVFrames.
    """
    cdef AVCodec *codec
    cdef AVCodecContext *codec_ctx
    cdef AVPixelFormat pix_fmt
    cdef AVPixelFormat actual_pix_fmt
    cdef char *colorspace
    cdef object framewrappers
    cdef object weakref_images
    cdef AVFrame *frame                             #@DuplicatedSignature
    cdef int frames
    cdef int width
    cdef int height
    cdef object encoding

    def init_context(self, encoding, int width, int height, colorspace):
        cdef int r
        init_colorspaces()
        assert encoding in ("vp8", "h264")
        self.encoding = encoding
        self.width = width
        self.height = height
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

        if self.encoding=="h264":
            self.codec = avcodec_find_decoder(CODEC_ID_H264)
            if self.codec==NULL:
                error("codec H264 not found!")
                return  False
        else:
            assert self.encoding=="vp8"
            self.codec = avcodec_find_decoder(CODEC_ID_VP8)
            if self.codec==NULL:
                error("codec VP8 not found!")
                return  False

        #from here on, we have to call clean_decoder():
        self.codec_ctx = avcodec_alloc_context3(self.codec)
        if self.codec_ctx==NULL:
            error("failed to allocate codec context!")
            self.clean_decoder()
            return  False

        self.codec_ctx.refcounted_frames = 1
        self.codec_ctx.width = width
        self.codec_ctx.height = height
        self.codec_ctx.pix_fmt = self.pix_fmt
        #self.codec_ctx.get_buffer2 = avcodec_get_buffer2
        #self.codec_ctx.release_buffer = avcodec_release_buffer
        self.codec_ctx.thread_safe_callbacks = 1
        self.codec_ctx.thread_type = 2      #FF_THREAD_SLICE: allow more than one thread per frame
        self.codec_ctx.thread_count = 0     #auto
        self.codec_ctx.flags2 |= CODEC_FLAG2_FAST   #may cause "no deblock across slices" - which should be fine
        r = avcodec_open2(self.codec_ctx, self.codec, NULL)
        if r<0:
            error("could not open codec: %s", self.av_error_str(r))
            self.clean_decoder()
            return  False
        self.frame = av_frame_alloc()
        if self.frame==NULL:
            error("could not allocate an AVFrame for decoding")
            self.clean_decoder()
            return  False
        self.frames = 0
        #to keep track of frame wrappers:
        self.framewrappers = {}
        #to keep track of images not freed yet:
        #(we want a weakref.WeakSet() but this is python2.7+ only..)
        self.weakref_images = []
        #register this decoder in the global dictionary:
        debug("dec_avcodec.Decoder.init_context(%s, %s, %s) self=%s", width, height, colorspace, self.get_info())
        return True

    def clean(self):
        self.clean_decoder()

    def clean_decoder(self):
        cdef int r                      #@DuplicateSignature
        debug("%s.clean_decoder()", self)
        #we may have images handed out, ensure we don't reference any memory
        #that needs to be freed using avcodec_release_buffer(..)
        #as this requires the context to still be valid!
        #copying the pixels should ensure we free the AVFrameWrapper associated with it:
        if self.weakref_images:
            images = [y for y in [x() for x in self.weakref_images] if y is not None]
            self.weakref_images = []
            debug("clean_decoder() cloning pixels for images still in use: %s", images)
            for img in images:
                img.clone_pixel_data()

        debug("clean_decoder() freeing AVFrame: %s", hex(<unsigned long> self.frame))
        if self.frame!=NULL:
            av_frame_free(&self.frame)
            #redundant: self.frame = NULL

        cdef unsigned long ctx_key          #@DuplicatedSignature
        debug("clean_decoder() freeing AVCodecContext: %s", hex(<unsigned long> self.codec_ctx))
        if self.codec_ctx!=NULL:
            r = avcodec_close(self.codec_ctx)
            if r!=0:
                log.warn("error closing decoder context %s: %s", hex(<unsigned long> self.codec_ctx), self.av_error_str(r))
            av_free(self.codec_ctx)
            self.codec_ctx = NULL
        debug("clean_decoder() done")

    cdef av_error_str(self, errnum):
        cdef char[128] err_str
        if av_strerror(errnum, err_str, 128)==0:
            return str(err_str[:128])
        return str(errnum)

    def __str__(self):                      #@DuplicatedSignature
        return "dec_avcodec.Decoder(%s)" % self.get_info()

    def get_info(self):
        info = {
                "type"      : self.get_type(),
                "frames"    : self.frames,
                "width"     : self.width,
                "height"    : self.height,
                }
        if self.framewrappers is not None:
            info["buffers"] = len(self.framewrappers)
        if self.colorspace:
            info["colorspace"] = self.colorspace
            info["actual_colorspace"] = self.get_actual_colorspace()
        if not self.is_closed():
            info["decoder_width"] = self.codec_ctx.width
            info["decoder_height"] = self.codec_ctx.height
        else:
            info["closed"] = True
        return info

    def is_closed(self):
        return self.codec_ctx==NULL

    def __dealloc__(self):                          #@DuplicatedSignature
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_encoding(self):
        return "h264"

    def get_type(self):                             #@DuplicatedSignature
        return "avcodec"

    def decompress_image(self, input, options):
        cdef unsigned char * padded_buf = NULL
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int len = 0
        cdef int got_picture
        cdef AVPacket avpkt
        cdef unsigned long frame_key                #@DuplicatedSignature
        cdef AVFrameWrapper framewrapper
        cdef object img
        assert self.codec_ctx!=NULL
        assert self.codec!=NULL
        #copy input buffer into padded C buffer:
        PyObject_AsReadBuffer(input, <const void**> &buf, &buf_len)
        padded_buf = <unsigned char *> xmemalign(buf_len+128)
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 128)
        #ensure we can detect if the frame buffer got allocated:
        clear_frame(self.frame)
        #now safe to run without gil:
        with nogil:
            av_init_packet(&avpkt)
            avpkt.data = <uint8_t *> padded_buf
            avpkt.size = buf_len
            len = avcodec_decode_video2(self.codec_ctx, self.frame, &got_picture, &avpkt)
            free(padded_buf)
        if len < 0: #for testing add: or options.get("frame", 0)%100==99:
            self.frame_error()
            log.warn("%s.decompress_image(%s:%s, %s) avcodec_decode_video2 failure: %s", self, type(input), buf_len, options, self.av_error_str(len))
            return None
            #raise Exception("avcodec_decode_video2 failed to decode this frame and returned %s, decoder=%s" % (len, self.get_info()))

        if self.actual_pix_fmt!=self.frame.format:
            self.actual_pix_fmt = self.frame.format
            if self.actual_pix_fmt not in ENUM_TO_FORMAT:
                self.frame_error()
                raise Exception("unknown output pixel format: %s, expected %s (%s)" % (self.actual_pix_fmt, self.pix_fmt, self.colorspace))
            debug("avcodec actual output pixel format is %s (%s), expected %s (%s)", self.actual_pix_fmt, self.get_actual_colorspace(), self.pix_fmt, self.colorspace)

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
                    self.frame_error()
                    raise Exception("invalid height divisor %s" % dy)
                stride = self.frame.linesize[i]
                size = height * stride
                outsize += size
                if READ_ONLY:
                    plane = PyBuffer_FromMemory(<void *>self.frame.data[i], size)
                else:
                    plane = PyBuffer_FromReadWriteMemory(<void *>self.frame.data[i], size)
                out.append(plane)
                strides.append(stride)
        else:
            strides = self.frame.linesize[0]+self.frame.linesize[1]+self.frame.linesize[2]
            outsize = self.codec_ctx.height * strides
            if READ_ONLY:
                out = PyBuffer_FromMemory(<void *>self.frame.data[0], outsize)
            else:
                out = PyBuffer_FromReadWriteMemory(<void *>self.frame.data[0], outsize)
            nplanes = 0
        if outsize==0:
            self.frame_error()
            raise Exception("output size is zero!")
        assert self.codec_ctx.width>=self.width, "codec width is smaller than our width: %s<%s" % (self.codec_ctx.width, self.width)
        assert self.codec_ctx.height>=self.height, "codec height is smaller than our height: %s<%s" % (self.codec_ctx.height, self.height)
        img = AVImageWrapper(0, 0, self.width, self.height, out, cs, 24, strides, nplanes)
        img.av_frame = None
        framewrapper = AVFrameWrapper()
        framewrapper.set_context(self.codec_ctx, self.frame)
        img.av_frame = framewrapper
        self.frames += 1
        #add to weakref list after cleaning it up:
        self.weakref_images = [x for x in self.weakref_images if x() is not None]
        ref = weakref.ref(img)
        self.weakref_images.append(ref)
        debug("%s.decompress_image(%s:%s, %s)=%s", self, type(input), buf_len, options, img)
        return img


    cdef AVFrameWrapper frame_error(self):
        av_frame_unref(self.frame)

    def get_colorspace(self):
        return self.colorspace

    def get_actual_colorspace(self):
        return ENUM_TO_FORMAT.get(self.actual_pix_fmt, "unknown/invalid")
