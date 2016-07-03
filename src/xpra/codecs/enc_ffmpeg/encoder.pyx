# This file is part of Xpra.
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
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


from libc.stdint cimport uint8_t, int64_t, uint8_t

cdef extern from "string.h":
    void free(void * ptr) nogil

cdef extern from "../../buffers/buffers.h":
    int object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)
    int get_buffer_api_version()

cdef extern from "../../inline.h":
    pass

cdef extern from "../../buffers/memalign.h":
    void *xmemalign(size_t size) nogil


cdef extern from "libavutil/mem.h":
    void av_free(void *ptr)

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
        uint8_t **data
        int *linesize
        int width
        int height
        int format
        int key_frame
        int64_t pts
        int coded_picture_number
        int display_picture_number
        int quality
        void *opaque
        AVPictureType pict_type
    ctypedef struct AVCodec:
        int capabilities
        const char *name
        const char *long_name
    ctypedef struct AVDictionary:
        pass
    ctypedef struct AVPacket:
        uint8_t *data
        int      size

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

    ctypedef struct AVFormatContext:
        pass

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

    int av_write_frame(AVFormatContext *s, AVPacket *pkt)
    AVFrame* av_frame_alloc()
    void av_frame_free(AVFrame **frame)
    int avcodec_close(AVCodecContext *avctx)
    void av_frame_unref(AVFrame *frame) nogil
    void av_init_packet(AVPacket *pkt) nogil
    void av_packet_unref(AVPacket *pkt) nogil


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
#if avcodec_find_encoder(AV_CODEC_ID_MPEG4)!=NULL:
#    CODECS.append("mpeg4")
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


cdef class Encoder:
    """
        This wraps the AVCodecContext and its configuration,
    """
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
        self.codec = avcodec_find_encoder(CodecID)
        if self.codec==NULL:
            raise Exception("codec %s not found!" % self.encoding)
        log("%s: \"%s\", codec flags: %s", self.codec.name, self.codec.long_name, csv(v for k,v in CAPS.items() if (self.codec.capabilities & k)))

        #from here on, we have to call clean_encoder():
        self.codec_ctx = avcodec_alloc_context3(self.codec)
        if self.codec_ctx==NULL:
            self.clean_encoder()
            raise Exception("failed to allocate codec context!")

        cdef int b_frames = int(options.get("b-frames"))
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
        self.codec_ctx.width = width
        self.codec_ctx.height = height
        self.codec_ctx.pix_fmt = self.pix_fmt
        self.codec_ctx.thread_safe_callbacks = 1
        self.codec_ctx.thread_type = 2      #FF_THREAD_SLICE: allow more than one thread per frame
        self.codec_ctx.thread_count = 0     #auto
        self.codec_ctx.flags2 |= CODEC_FLAG2_FAST   #may cause "no deblock across slices" - which should be fine
        #av_opt_set(c->priv_data, "preset", "slow", 0)
        cdef int r = avcodec_open2(self.codec_ctx, self.codec, NULL)
        if r<0:
            self.clean_encoder()
            raise Exception("could not open %s encoder context: %s" % (self.encoding, av_error_str(r)))
        self.av_frame = av_frame_alloc()
        if self.av_frame==NULL:
            self.clean_encoder()
            raise Exception("could not allocate an AVFrame for encoding")
        self.frames = 0
        log("enc_ffmpeg.Encoder.init_context(%s, %s, %s) self=%s", width, height, src_format, self.get_info())
        gen = generation.increase()
        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+"ffmpeg-"+self.encoding+"-"+str(gen)+".%s" % encoding
            self.file = open(filename, 'wb')
            log.info("saving %s stream to %s", encoding, filename)

    def clean(self):
        self.clean_encoder()
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
        cdef int r, i
        log("%s.clean_encoder()", self)

        if self.av_frame!=NULL:
            log("clean_encoder() freeing AVFrame: %#x", <unsigned long> self.av_frame)
            av_frame_free(&self.av_frame)
            #redundant: self.frame = NULL

        cdef unsigned long ctx_key          #@DuplicatedSignature
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
            if self.frames==0:
                self.av_frame.pict_type = AV_PICTURE_TYPE_I
            else:
                self.av_frame.pict_type = AV_PICTURE_TYPE_P
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
                self.log_error(image, ret, options, "no stream")
                raise Exception("no stream")
            log("avcodec_receive_packet returned %#x bytes of data", avpkt.size)
            packet_data = avpkt.data[:avpkt.size]
            bufs.append(packet_data)
            if self.file and packet_data:
                self.file.write(packet_data)
                self.file.flush()
        av_packet_unref(&avpkt)
        free(avpkt.data)
        self.frames += 1
        data = b"".join(bufs)
        log("compress_image(%s) %5i bytes (%i buffers) for %4s frame %-3i, client options: %s", image, len(data), len(bufs), self.encoding, self.frames, client_options)
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
