# This file is part of Xpra.
# Copyright (C) 2012-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import errno
import weakref
from xpra.log import Logger
log = Logger("decoder", "avcodec")

from xpra.os_util import bytestostr
from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.libav_common.av_log cimport override_logger, restore_logger, av_error_str #@UnresolvedImport
from xpra.codecs.libav_common.av_log import suspend_nonfatal_logging, resume_nonfatal_logging
from xpra.buffers.membuf cimport memalign, object_as_buffer, memory_as_pybuffer

from libc.stdint cimport uintptr_t, uint8_t


cdef extern from "string.h":
    void * memcpy(void * destination, void * source, size_t num) nogil
    void * memset(void * ptr, int value, size_t num) nogil
    void free(void * ptr) nogil

cdef extern from "../../inline.h":
    pass

cdef extern from "libavutil/mem.h":
    void av_free(void *ptr)

cdef extern from "libavcodec/version.h":
    int LIBAVCODEC_VERSION_MAJOR
    int LIBAVCODEC_VERSION_MINOR
    int LIBAVCODEC_VERSION_MICRO

#why can't we define this inside the avcodec.h section? (beats me)
ctypedef unsigned int AVCodecID
ctypedef long AVPixelFormat

cdef extern from "libavutil/pixfmt.h":
    AVPixelFormat AV_PIX_FMT_NONE
    AVPixelFormat AV_PIX_FMT_YUV420P
    AVPixelFormat AV_PIX_FMT_YUV422P
    AVPixelFormat AV_PIX_FMT_YUV444P
    AVPixelFormat AV_PIX_FMT_RGB24
    AVPixelFormat AV_PIX_FMT_0RGB
    AVPixelFormat AV_PIX_FMT_BGR0
    AVPixelFormat AV_PIX_FMT_ARGB
    AVPixelFormat AV_PIX_FMT_BGRA
    AVPixelFormat AV_PIX_FMT_GBRP

cdef extern from "libavcodec/avcodec.h":
    int CODEC_FLAG2_FAST

    ctypedef struct AVFrame:
        uint8_t **data
        int *linesize
        int format
        void *opaque
    ctypedef struct AVCodec:
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

    AVCodecID AV_CODEC_ID_H264
    AVCodecID AV_CODEC_ID_H265
    AVCodecID AV_CODEC_ID_VP8
    AVCodecID AV_CODEC_ID_VP9
    AVCodecID AV_CODEC_ID_MPEG4

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
    int avcodec_send_packet(AVCodecContext *avctx, const AVPacket *avpkt) nogil
    int avcodec_receive_frame(AVCodecContext *avctx, AVFrame *frame) nogil

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
#for planar formats, this is the number of bytes per channel
BYTES_PER_PIXEL = {
    AV_PIX_FMT_YUV420P  : 1,
    AV_PIX_FMT_YUV422P  : 1,
    AV_PIX_FMT_YUV444P  : 1,
    AV_PIX_FMT_RGB24    : 3,
    AV_PIX_FMT_0RGB     : 4,
    AV_PIX_FMT_BGR0     : 4,
    AV_PIX_FMT_ARGB     : 4,
    AV_PIX_FMT_BGRA     : 4,
    AV_PIX_FMT_GBRP     : 1,
    }

COLORSPACES = FORMAT_TO_ENUM.keys()
ENUM_TO_FORMAT = {}
for pix_fmt, av_enum in FORMAT_TO_ENUM.items():
    ENUM_TO_FORMAT[av_enum] = pix_fmt

def get_version():
    return (LIBAVCODEC_VERSION_MAJOR, LIBAVCODEC_VERSION_MINOR, LIBAVCODEC_VERSION_MICRO)

avcodec_register_all()
CODECS = []
if avcodec_find_decoder(AV_CODEC_ID_H264)!=NULL:
    CODECS.append("h264")
if avcodec_find_decoder(AV_CODEC_ID_VP8)!=NULL:
    CODECS.append("vp8")
if avcodec_find_decoder(AV_CODEC_ID_H265)!=NULL:
    CODECS.append("h265")
if avcodec_find_decoder(AV_CODEC_ID_MPEG4)!=NULL:
    CODECS.append("mpeg4")
if avcodec_find_decoder(AV_CODEC_ID_VP9)!=NULL:
    VP9_CS = []
    #there used to be problems with YUV444P with older versions of ffmpeg:
    # "[vp9 @ ...] Invalid compressed header size"
    #this version definitely works (older versions may work too - untested):
    v = get_version()
    if v<(56, 26, 100):         #2.6.3
        log.warn("Warning: libavcodec version %s is too old:", ".".join((str(x) for x in v)))
        log.warn(" disabling VP9")
    else:
        VP9_CS = ["YUV420P"]
        if v<(56, 41, 100):     #2.7.1
            log.warn("Warning: libavcodec version %s is too old:", ".".join((str(x) for x in v)))
            log.warn(" disabling YUV444P support with VP9")
        else:
            VP9_CS.append("YUV444P")
    CODECS.append("vp9")
log("avcodec2.init_module: CODECS=%s", CODECS)


def init_module():
    log("dec_avcodec2.init_module()")
    override_logger()

def cleanup_module():
    log("dec_avcodec2.cleanup_module()")
    restore_logger()

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
    elif encoding in ("vp8", "mpeg4"):
        return ["YUV420P"]
    assert encoding=="vp9"
    return VP9_CS

def get_output_colorspace(encoding, csc):
    if encoding not in CODECS:
        return ""
    if encoding=="h264" and csc in ("RGB", "XRGB", "BGRX", "ARGB", "BGRA"):
        #h264 from plain RGB data is returned as "GBRP"!
        return "GBRP"
    elif encoding in ("vp8", "mpeg4"):
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
        log("%s.set_context(%#x, %#x)", self, <uintptr_t> avctx, <uintptr_t> frame)

    def __dealloc__(self):
        #By the time this wrapper is garbage collected,
        #we must have freed it!
        assert self.frame==NULL and self.avctx==NULL, "frame was freed by both, but not actually freed!"

    def __repr__(self):
        if self.frame==NULL:
            return "AVFrameWrapper(NULL)"
        return "AVFrameWrapper(%#x)" % <uintptr_t> self.frame

    def xpra_free(self):
        log("%s.xpra_free()", self)
        self.free()

    cdef free(self):
        log("%s.free() context=%#x, frame=%#x", self, <uintptr_t> self.avctx, <uintptr_t> self.frame)
        if self.avctx!=NULL and self.frame!=NULL:
            av_frame_unref(self.frame)
            self.frame = NULL
            self.avctx = NULL


class AVImageWrapper(ImageWrapper):
    """
        Wrapper which allows us to call xpra_free on the decoder
        when the image is freed, or once we have made a copy of the pixels.
    """

    def _cn(self):                          #@DuplicatedSignature
        return "AVImageWrapper-%s" % self.av_frame

    def free(self):                             #@DuplicatedSignature
        log("AVImageWrapper.free()")
        ImageWrapper.free(self)
        self.xpra_free_frame()

    def clone_pixel_data(self):
        log("AVImageWrapper.clone_pixel_data()")
        ImageWrapper.clone_pixel_data(self)
        self.xpra_free_frame()

    def xpra_free_frame(self):
        av_frame = self.av_frame
        log("AVImageWrapper.xpra_free_frame() av_frame=%s", av_frame)
        if av_frame:
            self.av_frame = None
            av_frame.xpra_free()


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
    cdef object weakref_images
    cdef AVFrame *av_frame
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
        self.pix_fmt = FORMAT_TO_ENUM.get(colorspace, AV_PIX_FMT_NONE)
        if self.pix_fmt==AV_PIX_FMT_NONE:
            log.error("invalid pixel format: %s", colorspace)
            return  False
        self.actual_pix_fmt = self.pix_fmt

        avcodec_register_all()

        cdef AVCodecID CodecID
        if self.encoding=="h264":
            CodecID = AV_CODEC_ID_H264
        elif self.encoding=="h265":
            CodecID = AV_CODEC_ID_H265
        elif self.encoding=="vp8":
            CodecID = AV_CODEC_ID_VP8
        elif self.encoding=="vp9":
            CodecID = AV_CODEC_ID_VP9
        elif self.encoding=="mpeg4":
            CodecID = AV_CODEC_ID_MPEG4
        else:
            raise Exception("invalid codec; %s" % self.encoding)
        self.codec = avcodec_find_decoder(CodecID)
        if self.codec==NULL:
            log.error("codec %s not found!" % self.encoding)
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
            log.error("could not open codec: %s", av_error_str(r))
            self.clean_decoder()
            return  False
        #up to 3 AVFrame objects used:
        self.av_frame = av_frame_alloc()
        if self.av_frame==NULL:
            log.error("could not allocate an AVFrame for decoding")
            self.clean_decoder()
            return  False
        self.frames = 0
        #to keep track of images not freed yet:
        #(we want a weakref.WeakSet() but this is python2.7+ only..)
        self.weakref_images = []
        #register this decoder in the global dictionary:
        log("dec_avcodec.Decoder.init_context(%s, %s, %s) self=%s", width, height, colorspace, self.get_info())
        return True

    def clean(self):
        self.clean_decoder()
        self.codec = NULL
        self.pix_fmt = 0
        self.actual_pix_fmt = 0
        self.colorspace = ""
        self.weakref_images = []
        self.av_frame = NULL                        #should be redundant
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
                if not img.freed:
                    img.clone_pixel_data()

        if self.av_frame!=NULL:
            log("clean_decoder() freeing AVFrame: %#x", <uintptr_t> self.av_frame)
            av_frame_free(&self.av_frame)
            #redundant: self.frame = NULL

        cdef unsigned long ctx_key          #@DuplicatedSignature
        log("clean_decoder() freeing AVCodecContext: %#x", <uintptr_t> self.codec_ctx)
        if self.codec_ctx!=NULL:
            r = avcodec_close(self.codec_ctx)
            if r!=0:
                log.error("Error: failed to close decoder context %#x:", <uintptr_t> self.codec_ctx)
                log.error(" %s", av_error_str(r))
            av_free(self.codec_ctx)
            self.codec_ctx = NULL
        log("clean_decoder() done")

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

    def log_av_error(self, int buf_len, err_no, options={}):
        msg = av_error_str(err_no)
        self.log_error(buf_len, msg, options, "error %i" % err_no)

    def log_error(self, int buf_len, err, options={}, error_type="error"):
        log.error("Error: avcodec %s decoding %i bytes of %s data:", error_type, buf_len, self.encoding)
        log.error(" '%s'", err)
        log.error(" frame %i", self.frames)
        if options:
            log.error(" frame options:")
            for k,v in options.items():
                log.error("   %s=%s", k, v)
        log.error(" decoder state:")
        for k,v in self.get_info().items():
            log.error("   %s = %s", k, v)

    def decompress_image(self, input, options):
        cdef unsigned char * padded_buf = NULL
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int size
        cdef int ret = 0
        cdef int nplanes
        cdef AVPacket avpkt
        cdef unsigned long frame_key                #@DuplicatedSignature
        cdef AVFrameWrapper framewrapper
        cdef AVFrame *av_frame
        cdef object img
        assert self.codec_ctx!=NULL, "no codec context! (not initialized or already closed)"
        assert self.codec!=NULL

        #copy the whole input buffer into a padded C buffer:
        assert object_as_buffer(input, <const void**> &buf, &buf_len)==0
        padded_buf = <unsigned char *> memalign(buf_len+128)
        assert padded_buf!=NULL, "failed to allocate %i bytes of memory" % (buf_len+128)
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 128)

        #note: plain RGB output, will redefine those:
        out = []
        strides = []
        outsize = 0

        #ensure we can detect if the frame buffer got allocated:
        clear_frame(self.av_frame)
        #now safe to run without gil:
        with nogil:
            av_init_packet(&avpkt)
            avpkt.data = <uint8_t *> (padded_buf)
            avpkt.size = buf_len
            ret = avcodec_send_packet(self.codec_ctx, &avpkt)
        if ret!=0:
            free(padded_buf)
            log("%s.decompress_image(%s:%s, %s) avcodec_send_packet failure: %s", self, type(input), buf_len, options, av_error_str(ret))
            self.log_av_error(buf_len, ret, options)
            return None
        with nogil:
            ret = avcodec_receive_frame(self.codec_ctx, self.av_frame)
        free(padded_buf)
        if ret==-errno.EAGAIN:
            d = options.get("delayed", 0)
            if d>0:
                log("avcodec_decode_video2 %i delayed pictures", d)
                return None
            self.log_error(buf_len, "no picture", options)
            return None
        if ret!=0:
            av_frame_unref(self.av_frame)
            log("%s.decompress_image(%s:%s, %s) avcodec_decode_video2 failure: %s", self, type(input), buf_len, options, av_error_str(ret))
            self.log_av_error(buf_len, ret, options)
            return None

        log("avcodec_decode_video2 returned %i", ret)
        if self.actual_pix_fmt!=self.av_frame.format:
            if self.av_frame.format==-1:
                self.log_error(buf_len, "unknown format returned")
                return None
            self.actual_pix_fmt = self.av_frame.format
            if self.actual_pix_fmt not in ENUM_TO_FORMAT:
                av_frame_unref(self.av_frame)
                log.error("unknown output pixel format: %s, expected %s (%s)", self.actual_pix_fmt, self.pix_fmt, self.colorspace)
                return None
            log("avcodec actual output pixel format is %s (%s), expected %s (%s)", self.actual_pix_fmt, self.get_actual_colorspace(), self.pix_fmt, self.colorspace)

        cs = self.get_actual_colorspace()
        if cs.endswith("P"):
            divs = get_subsampling_divs(cs)
            nplanes = 3
            for i in range(3):
                _, dy = divs[i]
                if dy==1:
                    height = self.codec_ctx.height
                elif dy==2:
                    height = (self.codec_ctx.height+1)>>1
                else:
                    av_frame_unref(self.av_frame)
                    raise Exception("invalid height divisor %s" % dy)
                stride = self.av_frame.linesize[i]
                size = height * stride
                outsize += size

                out.append(memory_as_pybuffer(<void *>self.av_frame.data[i], size, True))
                strides.append(stride)
                log("decompress_image() read back yuv plane %s: %s bytes", i, size)
        else:
            #RGB mode: "out" is a single buffer
            strides = self.av_frame.linesize[0]+self.av_frame.linesize[1]+self.av_frame.linesize[2]
            outsize = self.codec_ctx.height * strides
            out = memory_as_pybuffer(<void *>self.av_frame.data[0], outsize, True)
            nplanes = 0
            log("decompress_image() read back rgb buffer: %s bytes", outsize)

        if outsize==0:
            av_frame_unref(self.av_frame)
            raise Exception("output size is zero!")
        if self.codec_ctx.width<self.width or self.codec_ctx.height<self.height:
            raise Exception("%s context dimension %ix%i is smaller than the codec's expected size of %ix%i for frame %i" % (self.encoding, self.codec_ctx.width, self.codec_ctx.height, self.width, self.height, self.frames+1))

        bpp = BYTES_PER_PIXEL.get(self.actual_pix_fmt, 0)
        framewrapper = AVFrameWrapper()
        framewrapper.set_context(self.codec_ctx, self.av_frame)
        img = AVImageWrapper(0, 0, self.width, self.height, out, cs, 24, strides, bpp, nplanes, thread_safe=False)
        img.av_frame = framewrapper
        self.frames += 1
        #add to weakref list after cleaning it up:
        self.weakref_images = [x for x in self.weakref_images if x() is not None]
        self.weakref_images.append(weakref.ref(img))
        log("%s:", self)
        log("decompress_image(%s:%s, %s)=%s", type(input), buf_len, options, img)
        return img


    def get_colorspace(self):
        return self.colorspace

    def get_actual_colorspace(self):
        return ENUM_TO_FORMAT.get(self.actual_pix_fmt, "unknown/invalid")


def selftest(full=False):
    global CODECS
    from xpra.codecs.codec_checks import testdecoder
    from xpra.codecs.dec_avcodec2 import decoder
    global CODECS
    try:
        suspend_nonfatal_logging()
        CODECS = testdecoder(decoder, full)
    finally:
        resume_nonfatal_logging()
