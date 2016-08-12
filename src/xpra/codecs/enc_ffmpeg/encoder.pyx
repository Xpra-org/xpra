# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import weakref
from xpra.log import Logger
log = Logger("encoder", "ffmpeg")

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import get_subsampling_divs, video_spec
from xpra.codecs.libav_common.av_log cimport override_logger, restore_logger #@UnresolvedImport
from xpra.codecs.libav_common.av_log import suspend_nonfatal_logging, resume_nonfatal_logging
from xpra.util import AtomicInteger, bytestostr, csv, print_nested_dict

SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")


from libc.stdint cimport uint8_t, int64_t

cdef extern from "../../inline.h":
    pass

cdef extern from "string.h":
    void free(void * ptr) nogil

cdef extern from "../../buffers/memalign.h":
    void *xmemalign(size_t size) nogil

cdef extern from "../../buffers/buffers.h":
    int object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)
    int get_buffer_api_version()


cdef extern from "libavutil/mem.h":
    void av_free(void *ptr)
    void *av_malloc(size_t size)

cdef extern from "libavutil/error.h":
    int av_strerror(int errnum, char *errbuf, size_t errbuf_size)

cdef extern from "libavcodec/version.h":
    int LIBAVCODEC_VERSION_MAJOR
    int LIBAVCODEC_VERSION_MINOR
    int LIBAVCODEC_VERSION_MICRO

#why can't we define this inside the avcodec.h section? (beats me)
ctypedef unsigned int AVCodecID
ctypedef long AVPixelFormat
ctypedef int AVPictureType


cdef extern from "libavutil/avutil.h":
    int AV_PICTURE_TYPE_NONE
    int AV_PICTURE_TYPE_I
    int AV_PICTURE_TYPE_P
    int AV_PICTURE_TYPE_B
    int AV_PICTURE_TYPE_S
    int AV_PICTURE_TYPE_SI
    int AV_PICTURE_TYPE_SP
    int AV_PICTURE_TYPE_BI

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
    int CODEC_FLAG_UNALIGNED
    int CODEC_FLAG_QSCALE
    int CODEC_FLAG_4MV
    int CODEC_FLAG_OUTPUT_CORRUPT
    int CODEC_FLAG_QPEL
    int CODEC_FLAG_GMC
    int CODEC_FLAG_MV0
    int CODEC_FLAG_INPUT_PRESERVED
    int CODEC_FLAG_PASS1
    int CODEC_FLAG_PASS2
    int CODEC_FLAG_GRAY
    int CODEC_FLAG_EMU_EDGE
    int CODEC_FLAG_PSNR
    int CODEC_FLAG_TRUNCATED
    int CODEC_FLAG_NORMALIZE_AQP
    int CODEC_FLAG_INTERLACED_DCT
    int CODEC_FLAG_GLOBAL_HEADER

    int CODEC_FLAG2_FAST

    int CODEC_CAP_DRAW_HORIZ_BAND
    int CODEC_CAP_DR1
    int CODEC_CAP_TRUNCATED
    int CODEC_CAP_HWACCEL
    int CODEC_CAP_DELAY
    int CODEC_CAP_SMALL_LAST_FRAME
    int CODEC_CAP_HWACCEL_VDPAU
    int CODEC_CAP_SUBFRAMES
    int CODEC_CAP_EXPERIMENTAL
    int CODEC_CAP_CHANNEL_CONF
    int CODEC_CAP_NEG_LINESIZES
    int CODEC_CAP_FRAME_THREADS
    int CODEC_CAP_SLICE_THREADS
    int CODEC_CAP_PARAM_CHANGE
    int CODEC_CAP_AUTO_THREADS
    int CODEC_CAP_VARIABLE_FRAME_SIZE
    int CODEC_CAP_INTRA_ONLY
    int CODEC_CAP_LOSSLESS

    ctypedef struct AVFrame:
        uint8_t     **data
        int         *linesize
        int         width
        int         height
        int         format
        int         key_frame
        int64_t     pts
        int         coded_picture_number
        int         display_picture_number
        int         quality
        void        *opaque
        AVPictureType pict_type
    ctypedef struct AVCodec:
        int         capabilities
        const char  *name
        const char  *long_name
    ctypedef struct AVDictionary:
        pass
    int AV_PKT_FLAG_KEY
    int AV_PKT_FLAG_CORRUPT
    ctypedef struct AVPacket:
        int64_t pts
        int64_t dts
        uint8_t *data
        int     size
        int     stream_index
        int     flags
        int64_t duration
        int64_t pos

    ctypedef struct AVRational:
        int num
        int den

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
        int max_b_frames
        int has_b_frames
        int gop_size
        int delay
        AVRational framerate
        AVRational time_base
        unsigned int codec_tag
        int64_t bit_rate

    AVCodecID AV_CODEC_ID_H264
    AVCodecID AV_CODEC_ID_H265
    AVCodecID AV_CODEC_ID_VP8
    AVCodecID AV_CODEC_ID_VP9
    AVCodecID AV_CODEC_ID_MPEG4

    #init and free:
    void avcodec_register_all()
    AVCodec *avcodec_find_encoder(AVCodecID id)
    AVCodecContext *avcodec_alloc_context3(const AVCodec *codec)
    int avcodec_open2(AVCodecContext *avctx, const AVCodec *codec, AVDictionary **options)
    int avcodec_send_frame(AVCodecContext *avctx,const AVFrame *frame) nogil
    int avcodec_receive_packet(AVCodecContext *avctx, AVPacket *avpkt) nogil

    AVFrame* av_frame_alloc()
    void av_frame_free(AVFrame **frame)
    int avcodec_close(AVCodecContext *avctx)
    void av_init_packet(AVPacket *pkt) nogil
    void av_packet_unref(AVPacket *pkt) nogil

ctypedef int AVOptionType
cdef extern from "libavutil/opt.h":
    AVOptionType AV_OPT_TYPE_FLAGS
    AVOptionType AV_OPT_TYPE_INT
    AVOptionType AV_OPT_TYPE_INT64
    AVOptionType AV_OPT_TYPE_DOUBLE
    AVOptionType AV_OPT_TYPE_FLOAT
    AVOptionType AV_OPT_TYPE_STRING
    AVOptionType AV_OPT_TYPE_RATIONAL
    AVOptionType AV_OPT_TYPE_BINARY         #offset must point to a pointer immediately followed by an int for the length
    AVOptionType AV_OPT_TYPE_DICT
    AVOptionType AV_OPT_TYPE_CONST
    AVOptionType AV_OPT_TYPE_IMAGE_SIZE
    AVOptionType AV_OPT_TYPE_PIXEL_FMT
    AVOptionType AV_OPT_TYPE_SAMPLE_FMT
    AVOptionType AV_OPT_TYPE_VIDEO_RATE
    AVOptionType AV_OPT_TYPE_DURATION
    AVOptionType AV_OPT_TYPE_COLOR
    AVOptionType AV_OPT_TYPE_CHANNEL_LAYOUT
    AVOptionType AV_OPT_TYPE_BOOL

    int AV_OPT_SEARCH_CHILDREN
    int AV_OPT_SEARCH_FAKE_OBJ

    ctypedef struct AVOption:
        const char *name        #short English help text
        const char *help
        int offset              #The offset relative to the context structure where the option value is stored. It should be 0 for named constants.
        AVOptionType type
        int flags
        const char *unit

    const AVOption* av_opt_next(void *obj, const AVOption *prev)
    void *av_opt_child_next(void *obj, void *prev)
    int av_opt_set_int(void *obj, const char *name, int64_t val, int search_flags)
    int av_opt_get_int(void *obj, const char *name, int search_flags, int64_t *out_val)


cdef extern from "libavutil/log.h":
    ctypedef struct AVClass:
        const char  *class_name                 #The name of the class; usually it is the same name as the context structure type to which the AVClass is associated.
        const char  *(*item_name)(void *ctx)    #A pointer to a function which returns the name of a context instance ctx associated with the class.
        AVOption    *option                     #a pointer to the first option specified in the class if any or NULL
        int         version                     #LIBAVUTIL_VERSION with which this structure was created
        int         log_level_offset_offset     #Offset in the structure where log_level_offset is stored
        int         parent_log_context_offset   #Offset in the structure where a pointer to the parent context for logging is stored
        void        *(*child_next)(void *obj, void *prev)  #Return next AVOptions-enabled child or NULL
        AVClass     *(*child_class_next)(const AVClass *prev) #Return an AVClass corresponding to the next potential AVOptions-enabled child.
        #AVClassCategory category                #Category used for visualization (like color) This is only set if the category is equal for all objects using this class.
        #AVClassCategory (*get_category)(void *ctx)


AV_OPT_TYPES = {
                AV_OPT_TYPE_FLAGS       : "FLAGS",
                AV_OPT_TYPE_INT         : "INT",
                AV_OPT_TYPE_INT64       : "INT64",
                AV_OPT_TYPE_DOUBLE      : "DOUBLE",
                AV_OPT_TYPE_FLOAT       : "FLOAT",
                AV_OPT_TYPE_STRING      : "STRING",
                AV_OPT_TYPE_RATIONAL    : "RATIONAL",
                AV_OPT_TYPE_BINARY      : "BINARY",
                AV_OPT_TYPE_DICT        : "DICT",
                AV_OPT_TYPE_CONST       : "CONST",
                AV_OPT_TYPE_IMAGE_SIZE  : "IMAGE_SIZE",
                AV_OPT_TYPE_PIXEL_FMT   : "PIXEL_FMT",
                AV_OPT_TYPE_SAMPLE_FMT  : "SAMPLE_FMT",
                AV_OPT_TYPE_VIDEO_RATE  : "VIDEO_RATE",
                AV_OPT_TYPE_DURATION    : "DURATION",
                AV_OPT_TYPE_COLOR       : "COLOR",
                AV_OPT_TYPE_CHANNEL_LAYOUT : "CHANNEL_LAYOUT",
                AV_OPT_TYPE_BOOL        : "BOOL",
                }


PKT_FLAGS = {
             AV_PKT_FLAG_KEY        : "KEY",
             AV_PKT_FLAG_CORRUPT    : "CORRUPT",
             }

CODEC_FLAGS = {
               CODEC_FLAG_UNALIGNED         : "UNALIGNED",
               CODEC_FLAG_QSCALE            : "QSCALE",
               CODEC_FLAG_4MV               : "4MV",
               CODEC_FLAG_OUTPUT_CORRUPT    : "OUTPUT_CORRUPT",
               CODEC_FLAG_QPEL              : "QPEL",
               CODEC_FLAG_GMC               : "GMC",
               CODEC_FLAG_MV0               : "MV0",
               CODEC_FLAG_INPUT_PRESERVED   : "INPUT_PRESERVED",
               CODEC_FLAG_PASS1             : "PASS1",
               CODEC_FLAG_PASS2             : "PASS2",
               CODEC_FLAG_GRAY              : "GRAY",
               CODEC_FLAG_EMU_EDGE          : "EMU_EDGE",
               CODEC_FLAG_PSNR              : "PSNR",
               CODEC_FLAG_TRUNCATED         : "TRUNCATED",
               CODEC_FLAG_NORMALIZE_AQP     : "NORMALIZE_AQP",
               CODEC_FLAG_INTERLACED_DCT    : "INTERLACED_DCT",
               CODEC_FLAG_GLOBAL_HEADER     : "GLOBAL_HEADER",
               }

CODEC_FLAGS2 = {
                CODEC_FLAG2_FAST : "FAST",
                }

CAPS = {
        CODEC_CAP_DRAW_HORIZ_BAND       : "DRAW_HORIZ_BAND",
        CODEC_CAP_DR1                   : "DR1",
        CODEC_CAP_TRUNCATED             : "TRUNCATED",
        CODEC_CAP_HWACCEL               : "HWACCEL",
        CODEC_CAP_DELAY                 : "DELAY",
        CODEC_CAP_SMALL_LAST_FRAME      : "SMALL_LAST_FRAME",
        CODEC_CAP_HWACCEL_VDPAU         : "HWACCEL_VDPAU",
        CODEC_CAP_SUBFRAMES             : "SUBFRAMES",
        CODEC_CAP_EXPERIMENTAL          : "EXPERIMENTAL",
        CODEC_CAP_CHANNEL_CONF          : "CHANNEL_CONF",
        CODEC_CAP_NEG_LINESIZES         : "NEG_LINESIZES",
        CODEC_CAP_FRAME_THREADS         : "FRAME_THREADS",
        CODEC_CAP_SLICE_THREADS         : "SLICE_THREADS",
        CODEC_CAP_PARAM_CHANGE          : "PARAM_CHANGE",
        CODEC_CAP_AUTO_THREADS          : "AUTO_THREADS",
        CODEC_CAP_VARIABLE_FRAME_SIZE   : "VARIABLE_FRAME_SIZE",
        CODEC_CAP_INTRA_ONLY            : "INTRA_ONLY",
        CODEC_CAP_LOSSLESS              : "LOSSLESS",
        }
log("CODEC_CAP:")
print_nested_dict(dict((hex(abs(k)),v) for k,v in CAPS.items()), print_fn=log.debug)

PICTURE_TYPE = {
                AV_PICTURE_TYPE_NONE    : "NONE",
                AV_PICTURE_TYPE_I       : "I",
                AV_PICTURE_TYPE_P       : "P",
                AV_PICTURE_TYPE_B       : "B",
                AV_PICTURE_TYPE_S       : "S",
                AV_PICTURE_TYPE_SI      : "SI",
                AV_PICTURE_TYPE_SP      : "SP",
                AV_PICTURE_TYPE_BI      : "BI",
                }
log("AV_PICTURE:")
print_nested_dict(PICTURE_TYPE, print_fn=log.debug)

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
log("AV_PIX_FMT:")
print_nested_dict(ENUM_TO_FORMAT, print_fn=log.debug)

def flagscsv(flag_dict, value=0):
    return csv([v for k,v in flag_dict.items() if k&value])

def get_version():
    return (LIBAVCODEC_VERSION_MAJOR, LIBAVCODEC_VERSION_MINOR, LIBAVCODEC_VERSION_MICRO)

avcodec_register_all()
CODECS = []
if avcodec_find_encoder(AV_CODEC_ID_H264)!=NULL:
    CODECS.append("h264")
#if avcodec_find_encoder(AV_CODEC_ID_VP8)!=NULL:
#    CODECS.append("vp8")
#if avcodec_find_encoder(AV_CODEC_ID_VP9)!=NULL:
#    CODECS.append("vp9")
#if avcodec_find_encoder(AV_CODEC_ID_H265)!=NULL:
#    CODECS.append("h265")
if avcodec_find_encoder(AV_CODEC_ID_MPEG4)!=NULL:
    CODECS.append("mpeg4")
log("enc_ffmpeg CODECS=%s", csv(CODECS))

cdef av_error_str(int errnum):
    cdef char[128] err_str
    cdef int i = 0
    if av_strerror(errnum, err_str, 128)==0:
        while i<128 and err_str[i]!=0:
            i += 1
        return bytestostr(err_str[:i])
    return "error %s" % errnum

DEF EAGAIN = -11


def init_module():
    log("enc_ffmpeg.init_module()")
    override_logger()

def cleanup_module():
    log("enc_ffmpeg.cleanup_module()")
    restore_logger()

def get_type():
    return "ffmpeg"

generation = AtomicInteger()
def get_info():
    global generation
    f = {}
    for e in get_encodings():
        f[e] = get_input_colorspaces(e)
    return  {
             "version"      : get_version(),
             "encodings"    : get_encodings(),
             "buffer_api"   : get_buffer_api_version(),
             "formats"      : f,
             "generation"   : generation.get(),
             }

def get_encodings():
    global CODECS
    return CODECS

def get_input_colorspaces(encoding):
    return ["YUV420P"]

def get_output_colorspaces(encoding, csc):
    if encoding not in CODECS:
        return ""
    return ["YUV420P"]


MAX_WIDTH, MAX_HEIGHT = 4096, 4096
def get_spec(encoding, colorspace):
    assert encoding in get_encodings(), "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in get_input_colorspaces(encoding), "invalid colorspace: %s (must be one of %s)" % (colorspace, get_input_colorspaces(encoding))
    return video_spec(encoding=encoding, output_colorspaces=get_output_colorspaces(encoding, colorspace), has_lossless_mode=False,
                            codec_class=Encoder, codec_type=get_type(),
                            quality=40, speed=40,
                            setup_cost=90, width_mask=0xFFFE, height_mask=0xFFFE, max_w=MAX_WIDTH, max_h=MAX_HEIGHT)


cdef class Encoder(object):
    """
        This wraps the AVCodecContext and its configuration,
    """
    cdef AVCodecID codec_id
    cdef AVCodec *codec
    cdef AVCodecContext *codec_ctx
    cdef AVPixelFormat pix_fmt
    cdef object src_format
    cdef AVFrame *av_frame
    #this is the actual number of images we have returned
    cdef unsigned long frames
    cdef unsigned int width
    cdef unsigned int height
    cdef object encoding
    cdef object file

    cdef object __weakref__

    def init_context(self, unsigned int width, unsigned int height, src_format, dst_formats, encoding, int quality, int speed, scaling, options):    #@DuplicatedSignature
        cdef int r
        global CODECS, generation
        assert encoding in CODECS
        assert src_format in get_input_colorspaces(encoding), "invalid colorspace: %s" % src_format
        self.encoding = encoding
        self.width = width
        self.height = height
        self.src_format = src_format
        self.pix_fmt = FORMAT_TO_ENUM.get(src_format, AV_PIX_FMT_NONE)
        if self.pix_fmt==AV_PIX_FMT_NONE:
            raise Exception("invalid pixel format: %s", src_format)

        avcodec_register_all()
        if self.encoding=="h264":
            self.codec_id = AV_CODEC_ID_H264
        elif self.encoding=="h265":
            self.codec_id = AV_CODEC_ID_H265
        elif self.encoding=="vp8":
            self.codec_id = AV_CODEC_ID_VP8
        elif self.encoding=="vp9":
            self.codec_id = AV_CODEC_ID_VP9
        elif self.encoding=="mpeg4":
            self.codec_id = AV_CODEC_ID_MPEG4
        else:
            raise Exception("invalid codec; %s" % self.encoding)
        self.codec = avcodec_find_encoder(self.codec_id)
        if self.codec==NULL:
            raise Exception("codec %s not found!" % self.encoding)
        log("%s: \"%s\", codec flags: %s", self.codec.name, self.codec.long_name, flagscsv(CAPS, self.codec.capabilities))

        cdef int b_frames = 0   #int(options.get("b-frames"))
        try:
            self.init_encoder(b_frames)
        except Exception as e:
            log("init_encoder(%i) failed", b_frames, exc_info=True)
            self.clean()
            raise
        else:
            log("enc_ffmpeg.Encoder.init_context(%s, %s, %s) self=%s", self.width, self.height, self.src_format, self.get_info())

    def init_encoder(self, int b_frames):
        cdef unsigned long gen = generation.increase()

        self.codec_ctx = avcodec_alloc_context3(self.codec)
        if self.codec_ctx==NULL:
            raise Exception("failed to allocate codec context!")

        #we need a framerate.. make one up:
        self.codec_ctx.framerate.num = 1
        self.codec_ctx.framerate.den = 25
        self.codec_ctx.time_base.num = 1
        self.codec_ctx.time_base.den = 25
        self.codec_ctx.refcounted_frames = 1
        self.codec_ctx.max_b_frames = b_frames*1
        self.codec_ctx.has_b_frames = b_frames
        self.codec_ctx.delay = 0
        self.codec_ctx.gop_size = 1
        self.codec_ctx.width = self.width
        self.codec_ctx.height = self.height
        self.codec_ctx.bit_rate = 500000
        self.codec_ctx.pix_fmt = self.pix_fmt
        self.codec_ctx.thread_safe_callbacks = 1
        self.codec_ctx.thread_type = 2      #FF_THREAD_SLICE: allow more than one thread per frame
        self.codec_ctx.thread_count = 0     #auto
        self.codec_ctx.flags2 |= CODEC_FLAG2_FAST   #may cause "no deblock across slices" - which should be fine
        #av_opt_set(c->priv_data, "preset", "slow", 0)
        log("init_encoder() codec flags: %s", flagscsv(CODEC_FLAGS, self.codec_ctx.flags))
        log("init_encoder() codec flags2: %s", flagscsv(CODEC_FLAGS2, self.codec_ctx.flags2))

        r = avcodec_open2(self.codec_ctx, self.codec, NULL)   #NULL, NULL)
        if r!=0:
            raise Exception("could not open %s encoder context: %s" % (self.encoding, av_error_str(r)))

        self.av_frame = av_frame_alloc()
        if self.av_frame==NULL:
            raise Exception("could not allocate an AVFrame for encoding")
        self.frames = 0

        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+"-"+str(gen)+".%s" % self.encoding
            self.file = open(filename, 'wb')
            log.info("saving stream to %s", filename)


    def clean(self):
        try:
            self.clean_encoder()
        except:
            log.error("cleanup failed", exc_info=True)
        self.codec = NULL
        self.pix_fmt = 0
        self.src_format = ""
        self.av_frame = NULL                        #should be redundant
        self.frames = 0
        self.width = 0
        self.height = 0
        self.encoding = ""
        f = self.file
        if f:
            self.file = None
            f.close()

    def clean_encoder(self):
        cdef int r
        log("%s.clean_encoder()", self)
        if self.av_frame!=NULL:
            log("clean_encoder() freeing AVFrame: %#x", <unsigned long> self.av_frame)
            av_frame_free(&self.av_frame)
        log("clean_encoder() freeing AVCodecContext: %#x", <unsigned long> self.codec_ctx)
        if self.codec_ctx!=NULL:
            r = avcodec_close(self.codec_ctx)
            if r!=0:
                log.error("Error: failed to close encoder context %#x", <unsigned long> self.codec_ctx)
                log.error(" %s", av_error_str(r))
            av_free(self.codec_ctx)
            self.codec_ctx = NULL
        log("clean_encoder() done")

    def __repr__(self):                      #@DuplicatedSignature
        if self.is_closed():
            return "enc_ffmpeg.Encoder(*closed*)"
        return "enc_ffmpeg.Encoder(%s)" % self.get_info()

    def get_info(self):                      #@DuplicatedSignature
        info = {
                "version"   : get_version(),
                "encoding"  : self.encoding,
                "formats"   : get_input_colorspaces(self.encoding),
                "type"      : self.get_type(),
                "frames"    : self.frames,
                "width"     : self.width,
                "height"    : self.height,
                }
        if self.codec:
            info["codec"] = self.codec.name[:]
            info["description"] = self.codec.long_name[:]
        if self.src_format:
            info["src_format"] = self.src_format
        if not self.is_closed():
            info["encoder_width"] = self.codec_ctx.width
            info["encoder_height"] = self.codec_ctx.height
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

    def get_src_format(self):
        return self.src_format

    def get_encoding(self):
        return self.encoding

    def get_type(self):                             #@DuplicatedSignature
        return "ffmpeg"

    def get_delayed_frames(self):
        return 0

    def log_av_error(self, image, err_no, options={}):
        msg = av_error_str(err_no)
        self.log_error(image, msg, options, "error %i" % err_no)

    def log_error(self, image, err, options={}, error_type="error"):
        log.error("Error: ffmpeg %s encoding %s:", error_type, self.encoding)
        log.error(" '%s'", err)
        log.error(" on image %s", image)
        log.error(" frame number %i", self.frames)
        if options:
            log.error(" options=%s", options)
        log.error(" encoder state:")
        for k,v in self.get_info().items():
            log.error("  %s = %s", k, v)

    def compress_image(self, image, int quality=-1, int speed=-1, options={}):
        cdef unsigned char * padded_buf = NULL
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int ret
        cdef AVPacket avpkt
        cdef AVFrame *frame
        assert self.codec_ctx!=NULL, "no codec context! (not initialized or already closed)"
        assert self.codec!=NULL

        if image:
            pixels = image.get_pixels()
            istrides = image.get_rowstride()
            assert len(pixels)==3, "image pixels does not have 3 planes! (found %s)" % len(pixels)
            assert len(istrides)==3, "image strides does not have 3 values! (found %s)" % len(istrides)
            #populate the avframe:
            for i in range(4):
                if i<3:
                    assert object_as_buffer(pixels[i], <const void**> &buf, &buf_len)==0, "unable to convert %s to a buffer (plane=%s)" % (type(pixels[i]), i)
                    #log("plane %s: %i bytes (%ix%i stride=%i)", ["Y", "U", "V"][i], buf_len, self.width, self.height, istrides[i])
                    self.av_frame.data[i] = <uint8_t *> buf
                    self.av_frame.linesize[i] = istrides[i]
                else:
                    self.av_frame.data[i] = NULL
            self.av_frame.width = self.width
            self.av_frame.height = self.height
            self.av_frame.format = self.pix_fmt
            self.av_frame.pts = self.frames+1
            self.av_frame.coded_picture_number = self.frames+1
            self.av_frame.display_picture_number = self.frames+1
            #if self.frames==0:
            #    self.av_frame.pict_type = AV_PICTURE_TYPE_I
            #else:
            #    self.av_frame.pict_type = AV_PICTURE_TYPE_P
            #self.av_frame.quality = 1
            frame = self.av_frame
        else:
            assert options.get("flush")
            frame = NULL

        with nogil:
            ret = avcodec_send_frame(self.codec_ctx, frame)
        if ret!=0:
            self.log_av_error(image, ret, options)
            raise Exception(av_error_str(ret))

        buf_len = 1024+self.width*self.height
        av_init_packet(&avpkt)
        avpkt.data = <uint8_t *> xmemalign(buf_len)
        avpkt.size = buf_len
        assert ret==0
        bufs = []
        client_options = {}
        while ret==0:
            with nogil:
                ret = avcodec_receive_packet(self.codec_ctx, &avpkt)
            if ret==EAGAIN:
                client_options["delayed"] = 1
                log("ffmpeg EAGAIN: delayed picture")
                break
            if ret!=0 and bufs:
                log("avcodec_receive_packet returned error %s for image %s, returning existing buffer", av_error_str(ret), image)
                break
            if ret!=0 and not image:
                log("avcodec_receive_packet returned error %s for flush request", av_error_str(ret))
                break
            if ret<0:
                free(avpkt.data)
                self.log_av_error(image, ret, options)
                raise Exception(av_error_str(ret))
            if ret>0:
                free(avpkt.data)
                self.log_av_error(image, ret, options, "no stream")
                raise Exception("no stream")
            log("avcodec_receive_packet returned %#x bytes of data, flags: %s", avpkt.size, flagscsv(PKT_FLAGS, avpkt.flags))
            if avpkt.flags & AV_PKT_FLAG_CORRUPT:
                free(avpkt.data)
                self.log_error(image, "packet", options, "av packet is corrupt")
                raise Exception("av packet is corrupt")
            packet_data = avpkt.data[:avpkt.size]
            bufs.append(packet_data)
        av_packet_unref(&avpkt)
        free(avpkt.data)
        self.frames += 1
        data = b"".join(bufs)
        log("compress_image(%s) %5i bytes (%i buffers) for %4s frame %-3i, client options: %s", image, len(data), len(bufs), self.encoding, self.frames, client_options)
        if data and self.file:
            self.file.write(data)
        return data, client_options

    def flush(self, delayed):
        v = self.compress_image(None, options={"flush" : True})
        #ffmpeg context cannot be re-used after a flush..
        self.clean()
        return v


def selftest(full=False):
    global CODECS
    from xpra.codecs.codec_checks import testencoder
    from xpra.codecs.enc_ffmpeg import encoder
    try:
        suspend_nonfatal_logging()
        CODECS = testencoder(encoder, full)
    finally:
        resume_nonfatal_logging()
