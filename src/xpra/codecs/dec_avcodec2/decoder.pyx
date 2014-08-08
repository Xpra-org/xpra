# This file is part of Xpra.
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import weakref
from xpra.log import Logger
log = Logger("decoder", "avcodec")

#some consumers need a writeable buffer (ie: OpenCL...)
READ_ONLY = False

from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.codecs.image_wrapper import ImageWrapper


ctypedef unsigned long size_t
ctypedef unsigned char uint8_t

cdef extern from "Python.h":
    ctypedef int Py_ssize_t

cdef extern from "../buffers/buffers.h":
    object memory_as_pybuffer(void* ptr, Py_ssize_t buf_len, int readonly)
    int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)

cdef extern from "string.h":
    void * memcpy(void * destination, void * source, size_t num) nogil
    void * memset(void * ptr, int value, size_t num) nogil
    void free(void * ptr) nogil


cdef extern from "../inline.h":
    pass

cdef extern from "../buffers/memalign.h":
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

    int AV_PIX_FMT_YUV420P
    int AV_PIX_FMT_YUV422P
    int AV_PIX_FMT_YUV444P
    int AV_PIX_FMT_RGB24
    int AV_PIX_FMT_0RGB
    int AV_PIX_FMT_BGR0
    int AV_PIX_FMT_ARGB
    int AV_PIX_FMT_BGRA
    int AV_PIX_FMT_GBRP

    int CODEC_FLAG2_FAST


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
    AVCodecID AV_CODEC_ID_H264
    AVCodecID AV_CODEC_ID_H265
    AVCodecID AV_CODEC_ID_VP8
    AVCodecID AV_CODEC_ID_VP9

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


FORMAT_TO_ENUM = {
            "YUV420P"   : AV_PIX_FMT_YUV420P,
            "YUV422P"   : AV_PIX_FMT_YUV422P,
            "YUV444P"   : AV_PIX_FMT_YUV444P,
            "RGB"       : AV_PIX_FMT_RGB24,
            "XRGB"      : AV_PIX_FMT_0RGB,
            "BGRX"      : AV_PIX_FMT_BGR0,
            "ARGB"      : AV_PIX_FMT_ARGB,
            "BGRA"      : AV_PIX_FMT_BGRA,
            "GBRP"      : AV_PIX_FMT_GBRP,
            }

COLORSPACES = FORMAT_TO_ENUM.keys()
ENUM_TO_FORMAT = {}
for pix_fmt, av_enum in FORMAT_TO_ENUM.items():
    ENUM_TO_FORMAT[av_enum] = pix_fmt

avcodec_register_all()
CODECS = []
if avcodec_find_decoder(AV_CODEC_ID_H264)!=NULL:
    CODECS.append("h264")
if avcodec_find_decoder(AV_CODEC_ID_VP8)!=NULL:
    CODECS.append("vp8")
if avcodec_find_decoder(AV_CODEC_ID_VP9)!=NULL:
    CODECS.append("vp9")
if avcodec_find_decoder(AV_CODEC_ID_H265)!=NULL:
    CODECS.append("h265")
log("avcodec2.init_module: CODECS=%s", CODECS)


def init_module():
    log("dec_avcodec2.init_module()")

def cleanup_module():
    log("dec_avcodec2.cleanup_module()")

def get_version():
    return (LIBAVCODEC_VERSION_MAJOR, LIBAVCODEC_VERSION_MINOR, LIBAVCODEC_VERSION_MICRO)

def get_type():
    return "avcodec2"

def get_info():
    f = {}
    for e in get_encodings():
        f["formats.%s" % e] = get_input_colorspaces(e)
    return  {"version"      : get_version(),
             "encodings"    : get_encodings(),
             "formats"      : f,
             }

def get_encodings():
    global CODECS
    return CODECS

def get_input_colorspaces(encoding):
    if encoding not in CODECS:
        return []
    if encoding in ("h264", "h265"):
        return COLORSPACES
    elif encoding=="vp8":
        return ["YUV420P"]
    assert encoding=="vp9"
    #we only handle YUV420P encoding at present,
    #but we ought to be able to support the other YUV modes out of the box already:
    return ["YUV420P", "YUV422P", "YUV444P"]

def get_output_colorspace(encoding, csc):
    if encoding not in CODECS:
        return ""
    if encoding=="h264" and csc in ("RGB", "XRGB", "BGRX", "ARGB", "BGRA"):
        #h264 from plain RGB data is returned as "GBRP"!
        return "GBRP"
    elif encoding=="vp8":
        return "YUV420P"
    #everything else as normal:
    return csc


cdef void clear_frame(AVFrame *frame):
    assert frame!=NULL, "frame is not set!"
    for i in range(4):
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
        log("%s.set_context(%#x, %#x)", self, <unsigned long> avctx, <unsigned long> frame)

    def __dealloc__(self):
        #By the time this wrapper is garbage collected,
        #we must have freed it!
        assert self.frame==NULL and self.avctx==NULL, "frame was freed by both, but not actually freed!"

    def __str__(self):
        if self.frame==NULL:
            return "AVFrameWrapper(NULL)"
        return "AVFrameWrapper(%#x)" % <unsigned long> self.frame

    def xpra_free(self):
        log("%s.xpra_free()", self)
        self.free()

    cdef free(self):
        log("%s.free() context=%#x, frame=%#x", self, <unsigned long> self.avctx, <unsigned long> self.frame)
        if self.avctx!=NULL and self.frame!=NULL:
            av_frame_unref(self.frame)
            self.frame = NULL
            self.avctx = NULL


class AVImageWrapper(ImageWrapper):
    """
        Wrapper which allows us to call xpra_free on the decoder
        when the image is freed, or once we have made a copy of the pixels.
    """

    def __repr__(self):                          #@DuplicatedSignature
        return ImageWrapper.__repr__(self)+"-(%s)" % self.av_frames

    def free(self):                             #@DuplicatedSignature
        log("AVImageWrapper.free()")
        ImageWrapper.free(self)
        self.xpra_free_frame()

    def clone_pixel_data(self):
        log("AVImageWrapper.clone_pixel_data()")
        ImageWrapper.clone_pixel_data(self)
        self.xpra_free_frame()

    def xpra_free_frame(self):
        log("AVImageWrapper.xpra_free_frame() av_frames=%s", self.av_frames)
        if self.av_frames:
            for av_frame in self.av_frames:
                av_frame.xpra_free()
            self.av_frames = None


cdef class Decoder:
    """
        This wraps the AVCodecContext and its configuration,
        also tracks AVFrames.
        It also handles reconstructing a single ImageWrapper
        constructed from 3-pass decoding (see plane_sizes).
    """
    cdef AVCodec *codec
    cdef AVCodecContext *codec_ctx
    cdef AVPixelFormat pix_fmt
    cdef AVPixelFormat actual_pix_fmt
    cdef object colorspace
    cdef object framewrappers
    cdef object weakref_images
    #we usually use just one, but 3-pass decoding will use all 3
    cdef AVFrame *av_frames[3]
    #this is the actual number of images we have returned
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object encoding

    cdef object __weakref__

    def init_context(self, encoding, int width, int height, colorspace):
        cdef int r
        cdef int i
        assert encoding in CODECS
        self.encoding = encoding
        self.width = width
        self.height = height
        assert colorspace in COLORSPACES, "invalid colorspace: %s" % colorspace
        self.colorspace = ""
        for x in COLORSPACES:
            if x==colorspace:
                self.colorspace = x
                break
        if not self.colorspace:
            log.error("invalid pixel format: %s", colorspace)
            return  False
        self.pix_fmt = FORMAT_TO_ENUM.get(colorspace, PIX_FMT_NONE)
        if self.pix_fmt==PIX_FMT_NONE:
            log.error("invalid pixel format: %s", colorspace)
            return  False
        self.actual_pix_fmt = self.pix_fmt

        avcodec_register_all()

        if self.encoding=="h264":
            self.codec = avcodec_find_decoder(AV_CODEC_ID_H264)
            if self.codec==NULL:
                log.error("codec H264 not found!")
                return  False
        elif self.encoding=="h265":
            self.codec = avcodec_find_decoder(AV_CODEC_ID_H265)
            if self.codec==NULL:
                log.error("codec H265 (HEVC) not found!")
                return  False
        else:
            assert self.encoding=="vp8"
            self.codec = avcodec_find_decoder(AV_CODEC_ID_VP8)
            if self.codec==NULL:
                log.error("codec VP8 not found!")
                return  False

        #from here on, we have to call clean_decoder():
        self.codec_ctx = avcodec_alloc_context3(self.codec)
        if self.codec_ctx==NULL:
            log.error("failed to allocate codec context!")
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
            log.error("could not open codec: %s", self.av_error_str(r))
            self.clean_decoder()
            return  False
        #up to 3 AVFrame objects used:
        for i in range(3):
            self.av_frames[i] = av_frame_alloc()
            if self.av_frames[i]==NULL:
                log.error("could not allocate an AVFrame for decoding")
                self.clean_decoder()
                return  False
        self.frames = 0
        #to keep track of frame wrappers:
        self.framewrappers = {}
        #to keep track of images not freed yet:
        #(we want a weakref.WeakSet() but this is python2.7+ only..)
        self.weakref_images = []
        #register this decoder in the global dictionary:
        log("dec_avcodec.Decoder.init_context(%s, %s, %s) self=%s", width, height, colorspace, self.get_info())
        return True

    def clean(self):
        cdef int i                                  #
        self.clean_decoder()
        self.codec = NULL
        self.pix_fmt = 0
        self.actual_pix_fmt = 0
        self.colorspace = ""
        self.framewrappers = {}
        self.weakref_images = []
        for i in range(3):
            self.av_frames[i] = NULL                #should be redundant
        self.frames = 0
        self.width = 0
        self.height = 0
        self.encoding = ""


    def clean_decoder(self):
        cdef int r, i
        log("%s.clean_decoder()", self)
        #we may have images handed out, ensure we don't reference any memory
        #that needs to be freed using avcodec_release_buffer(..)
        #as this requires the context to still be valid!
        #copying the pixels should ensure we free the AVFrameWrapper associated with it:
        if self.weakref_images:
            images = [y for y in [x() for x in self.weakref_images] if y is not None]
            self.weakref_images = []
            log("clean_decoder() cloning pixels for images still in use: %s", images)
            for img in images:
                img.clone_pixel_data()

        for i in range(3):
            if self.av_frames[i]!=NULL:
                log("clean_decoder() freeing AVFrame: %#x", <unsigned long> self.av_frames[i])
                av_frame_free(&self.av_frames[i])
            #redundant: self.frame = NULL

        cdef unsigned long ctx_key          #@DuplicatedSignature
        log("clean_decoder() freeing AVCodecContext: %#x", <unsigned long> self.codec_ctx)
        if self.codec_ctx!=NULL:
            r = avcodec_close(self.codec_ctx)
            if r!=0:
                log.warn("error closing decoder context %#x: %s", <unsigned long> self.codec_ctx, self.av_error_str(r))
            av_free(self.codec_ctx)
            self.codec_ctx = NULL
        log("clean_decoder() done")

    cdef av_error_str(self, errnum):
        cdef char[128] err_str
        if av_strerror(errnum, err_str, 128)==0:
            e = str(err_str[:128])
            p = e.find("\0")
            if p>=0:
                e = e[:p]
            return e
        return str(errnum)

    def __repr__(self):                      #@DuplicatedSignature
        if self.is_closed():
            return "dec_avcodec.Decoder(*closed*)"
        return "dec_avcodec.Decoder(%s)" % self.get_info()

    def get_info(self):                      #@DuplicatedSignature
        info = {"version"   : get_version(),
                "encoding"  : self.encoding,
                "formats"   : get_input_colorspaces(self.encoding),
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
        return self.encoding

    def get_type(self):                             #@DuplicatedSignature
        return "avcodec"

    def decompress_image(self, input, options):
        cdef unsigned char * padded_buf = NULL
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int offset
        cdef int size
        cdef int len = 0
        cdef int step, steps
        cdef int nplanes
        cdef int got_picture
        cdef AVPacket avpkt
        cdef unsigned long frame_key                #@DuplicatedSignature
        cdef AVFrameWrapper framewrapper
        cdef AVFrame *av_frame
        cdef object img
        cdef object plane_offsets, plane_sizes
        assert self.codec_ctx!=NULL
        assert self.codec!=NULL

        #copy the whole input buffer into a padded C buffer:
        assert object_as_buffer(input, <const void**> &buf, &buf_len)==0
        padded_buf = <unsigned char *> xmemalign(buf_len+128)
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 128)

        #support for separate colour planes:
        #(each plane is sent in its own frame)
        plane_sizes = options.get("plane_sizes")
        if plane_sizes is not None:
            #this is the separate colour plane format
            #each loop will only collect one plane:
            steps = 3
            nplanes = 1
            #the actual format is fixed:
            assert options.get("csc")=="YUV444P"
            self.actual_pix_fmt = FORMAT_TO_ENUM["YUV444P"]
            plane_offsets = [0, plane_sizes[0], plane_sizes[0]+plane_sizes[1]]
        else:
            #regular format (not using separate colour planes)
            #either RGB or YUV output
            #for YUV output, we need 3 planes:
            steps = 1
            nplanes = 3
            plane_offsets = [0]
            plane_sizes = [buf_len]
        #note: plain RGB output, will redefine those:
        out = []
        strides = []
        outsize = 0
        framewrappers = []
        for step in range(steps):
            offset = plane_offsets[step]
            size = plane_sizes[step]

            av_frame = self.av_frames[step]
            #ensure we can detect if the frame buffer got allocated:
            clear_frame(av_frame)
            #now safe to run without gil:
            log("decompress_image() step %s/%s using offset=%s and size=%s", step, steps, offset, size)
            with nogil:
                av_init_packet(&avpkt)
                avpkt.data = <uint8_t *> (padded_buf+offset)
                avpkt.size = size
                len = avcodec_decode_video2(self.codec_ctx, av_frame, &got_picture, &avpkt)
            if len<0:
                av_frame_unref(av_frame)
                log.warn("%s.decompress_image(%s:%s, %s) avcodec_decode_video2 failure: %s", self, type(input), buf_len, options, self.av_error_str(len))
                return None

            if steps==1:
                if self.actual_pix_fmt!=av_frame.format:
                    self.actual_pix_fmt = av_frame.format
                    if self.actual_pix_fmt not in ENUM_TO_FORMAT:
                        av_frame_unref(av_frame)
                        raise Exception("unknown output pixel format: %s, expected %s (%s)" % (self.actual_pix_fmt, self.pix_fmt, self.colorspace))
                    log("avcodec actual output pixel format is %s (%s), expected %s (%s)", self.actual_pix_fmt, self.get_actual_colorspace(), self.pix_fmt, self.colorspace)

            cs = self.get_actual_colorspace()
            if cs.endswith("P"):
                divs = get_subsampling_divs(cs)
                for i in range(nplanes):
                    _, dy = divs[i]
                    if dy==1:
                        height = self.codec_ctx.height
                    elif dy==2:
                        height = (self.codec_ctx.height+1)>>1
                    else:
                        av_frame_unref(av_frame)
                        raise Exception("invalid height divisor %s" % dy)
                    stride = av_frame.linesize[i]
                    size = height * stride
                    outsize += size

                    out.append(memory_as_pybuffer(<void *>av_frame.data[i], size, READ_ONLY))
                    strides.append(stride)
                    log("decompress_image() read back yuv plane %s: %s bytes", i, size)
            else:
                assert steps==1
                #RGB mode: "out" is a single buffer
                strides = av_frame.linesize[0]+av_frame.linesize[1]+av_frame.linesize[2]
                outsize = self.codec_ctx.height * strides
                out = memory_as_pybuffer(<void *>av_frame.data[0], outsize, READ_ONLY)
                nplanes = 0
                log("decompress_image() read back rgb buffer: %s bytes", outsize)

            #FIXME: we could lose track of framewrappers if an error occurs before the end:
            framewrapper = AVFrameWrapper()
            framewrapper.set_context(self.codec_ctx, av_frame)
            framewrappers.append(framewrapper)

            if outsize==0:
                av_frame_unref(av_frame)
                raise Exception("output size is zero!")

        free(padded_buf)
        assert self.codec_ctx.width>=self.width, "codec width is smaller than our width: %s<%s" % (self.codec_ctx.width, self.width)
        assert self.codec_ctx.height>=self.height, "codec height is smaller than our height: %s<%s" % (self.codec_ctx.height, self.height)
        img = AVImageWrapper(0, 0, self.width, self.height, out, cs, 24, strides, nplanes*steps, thread_safe=False)
        img.av_frames = framewrappers
        self.frames += 1
        #add to weakref list after cleaning it up:
        self.weakref_images = [x for x in self.weakref_images if x() is not None]
        self.weakref_images.append(weakref.ref(img))
        log("%s.decompress_image(%s:%s, %s)=%s", self, type(input), buf_len, options, img)
        return img


    def get_colorspace(self):
        return self.colorspace

    def get_actual_colorspace(self):
        return ENUM_TO_FORMAT.get(self.actual_pix_fmt, "unknown/invalid")
