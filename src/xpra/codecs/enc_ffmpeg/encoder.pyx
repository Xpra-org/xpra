# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import errno
import weakref
from xpra.log import Logger
log = Logger("encoder", "ffmpeg")

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.codec_constants import get_subsampling_divs, video_spec
from xpra.codecs.libav_common.av_log cimport override_logger, restore_logger #@UnresolvedImport
from xpra.codecs.libav_common.av_log import suspend_nonfatal_logging, resume_nonfatal_logging
from xpra.util import AtomicInteger, csv, print_nested_dict, envint, envbool
from xpra.os_util import bytestostr, strtobytes

SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")

THREAD_TYPE = envint("XPRA_FFMPEG_THREAD_TYPE", 2)
THREAD_COUNT= envint("XPRA_FFMPEG_THREAD_COUNT")
AUDIO = envbool("XPRA_FFMPEG_MPEG4_AUDIO", False)


from libc.stdint cimport uint8_t, int64_t, uint32_t

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
ctypedef long AVSampleFormat
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

cdef extern from "libavutil/dict.h":
    int av_dict_set(AVDictionary **pm, const char *key, const char *value, int flags)
    int av_dict_set_int(AVDictionary **pm, const char *key, int64_t value, int flags)
    void av_dict_free(AVDictionary **m)

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

cdef extern from "libavutil/samplefmt.h":
    AVSampleFormat AV_SAMPLE_FMT_S16
    AVSampleFormat AV_SAMPLE_FMT_FLTP


cdef extern from "libavformat/avio.h":
    ctypedef int AVIODataMarkerType
    int AVIO_FLAG_WRITE

    ctypedef struct AVIOContext:
        const AVClass *av_class
        unsigned char *buffer       #Start of the buffer
        int buffer_size             #Maximum buffer size
        unsigned char *buf_ptr      #Current position in the buffer
        unsigned char *buf_end      #End of the data, may be less than
                                    #buffer+buffer_size if the read function returned
                                    #less data than requested, e.g. for streams where
                                    #no more data has been received yet.
        int64_t     pos             #position in the file of the current buffer
        int         must_flush      #true if the next seek should flush
        int         error           #contains the error code or 0 if no error happened
        int         seekable
        int64_t     maxsize
        int         direct
        int64_t     bytes_read

    AVIOContext *avio_alloc_context(unsigned char *buffer, int buffer_size, int write_flag,
                  void *opaque,
                  int (*read_packet)(void *opaque, uint8_t *buf, int buf_size),
                  int (*write_packet)(void *opaque, uint8_t *buf, int buf_size),
                  int64_t (*seek)(void *opaque, int64_t offset, int whence))


cdef extern from "libavcodec/avcodec.h":
    int FF_THREAD_SLICE     #allow more than one thread per frame
    int FF_THREAD_FRAME     #Decode more than one frame at once

    int FF_PROFILE_H264_CONSTRAINED
    int FF_PROFILE_H264_INTRA
    int FF_PROFILE_H264_BASELINE
    int FF_PROFILE_H264_CONSTRAINED_BASELINE
    int FF_PROFILE_H264_MAIN
    int FF_PROFILE_H264_EXTENDED
    int FF_PROFILE_H264_HIGH
    int FF_PROFILE_H264_HIGH_10
    int FF_PROFILE_H264_HIGH_10_INTRA
    int FF_PROFILE_H264_MULTIVIEW_HIGH
    int FF_PROFILE_H264_HIGH_422
    int FF_PROFILE_H264_HIGH_422_INTRA
    int FF_PROFILE_H264_STEREO_HIGH
    int FF_PROFILE_H264_HIGH_444
    int FF_PROFILE_H264_HIGH_444_PREDICTIVE
    int FF_PROFILE_H264_HIGH_444_INTRA
    int FF_PROFILE_H264_CAVLC_444

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
        const AVClass *av_class
        int width
        int height
        AVPixelFormat pix_fmt
        int thread_safe_callbacks
        int thread_count
        int thread_type
        int flags
        int flags2
        #int refcounted_frames
        int max_b_frames
        int has_b_frames
        int gop_size
        int delay
        AVRational framerate
        AVRational time_base
        unsigned int codec_tag
        int64_t bit_rate
        AVSampleFormat sample_fmt
        int sample_rate
        int channels
        int profile
        int level

    ctypedef struct AVFormatContext:
        const AVClass   *av_class
        AVOutputFormat  *oformat
        void            *priv_data
        AVIOContext     *pb
        int             ctx_flags
        unsigned int    nb_streams
        AVStream        **streams
        int64_t         start_time
        int64_t         duration
        int             bit_rate
        unsigned int    packet_size
        int             max_delay
        int             flags
        unsigned int    probesize
        int             max_analyze_duration
        AVCodecID       video_codec_id
        AVCodecID       audio_codec_id
        AVCodecID       subtitle_codec_id
        unsigned int    max_index_size
        unsigned int    max_picture_buffer
        unsigned int    nb_chapters
        AVDictionary    *metadata
        int64_t         start_time_realtime
        int             strict_std_compliance
        int flush_packets

    ctypedef int AVFieldOrder
    ctypedef int AVColorRange
    ctypedef int AVColorPrimaries
    ctypedef int AVColorTransferCharacteristic
    ctypedef int AVColorSpace
    ctypedef int AVChromaLocation
    ctypedef struct AVCodecParameters:
        AVCodecID       codec_id
        uint32_t        codec_tag
        int64_t         bit_rate
        int             bits_per_coded_sample
        int             bits_per_raw_sample
        int             profile
        int             level
        int             width
        int             height
        AVFieldOrder    field_order
        AVColorRange    color_range
        AVColorPrimaries    color_primaries
        AVColorTransferCharacteristic color_trc
        AVColorSpace        color_space
        AVChromaLocation    chroma_location
        int             sample_rate
        int             frame_size

    AVCodecID AV_CODEC_ID_H264
    AVCodecID AV_CODEC_ID_H265
    AVCodecID AV_CODEC_ID_VP8
    AVCodecID AV_CODEC_ID_VP9
    AVCodecID AV_CODEC_ID_MPEG4

    AVCodecID AV_CODEC_ID_AAC

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
    int av_opt_set_dict(void *obj, AVDictionary **options)


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


cdef extern from "libavformat/avformat.h":
    int AVFMTCTX_NOHEADER           #signal that no header is present

    int AVFMT_FLAG_GENPTS           #Generate missing pts even if it requires parsing future frames
    int AVFMT_FLAG_IGNIDX           #Ignore index
    int AVFMT_FLAG_NONBLOCK         #Do not block when reading packets from input
    int AVFMT_FLAG_IGNDTS           #Ignore DTS on frames that contain both DTS & PTS
    int AVFMT_FLAG_NOFILLIN         #Do not infer any values from other values, just return what is stored in the container
    int AVFMT_FLAG_NOPARSE          #Do not use AVParsers, you also must set AVFMT_FLAG_NOFILLIN as the fillin code works on frames and no parsing -> no frames. Also seeking to frames can not work if parsing to find frame boundaries has been disabled
    int AVFMT_FLAG_NOBUFFER         #Do not buffer frames when possible
    int AVFMT_FLAG_CUSTOM_IO        #The caller has supplied a custom AVIOContext, don't avio_close() it
    int AVFMT_FLAG_DISCARD_CORRUPT  #Discard frames marked corrupted
    int AVFMT_FLAG_FLUSH_PACKETS    #Flush the AVIOContext every packet
    int AVFMT_FLAG_BITEXACT
    int AVFMT_FLAG_MP4A_LATM        #Enable RTP MP4A-LATM payload
    int AVFMT_FLAG_SORT_DTS         #try to interleave outputted packets by dts (using this flag can slow demuxing down)
    int AVFMT_FLAG_PRIV_OPT         #Enable use of private options by delaying codec open (this could be made default once all code is converted)
    int AVFMT_FLAG_KEEP_SIDE_DATA   #Don't merge side data but keep it separate.
    int AVFMT_FLAG_FAST_SEEK        #Enable fast, but inaccurate seeks for some formats

    int AVFMT_NOFILE                #Demuxer will use avio_open, no opened file should be provided by the caller
    int AVFMT_NEEDNUMBER            #Needs '%d' in filename
    int AVFMT_SHOW_IDS              #Show format stream IDs numbers
    int AVFMT_RAWPICTURE            #Format wants AVPicture structure for raw picture data. @deprecated Not used anymore
    int AVFMT_GLOBALHEADER          #Format wants global header
    int AVFMT_NOTIMESTAMPS          #Format does not need / have any timestamps
    int AVFMT_GENERIC_INDEX         #Use generic index building code
    int AVFMT_TS_DISCONT            #Format allows timestamp discontinuities. Note, muxers always require valid (monotone) timestamps
    int AVFMT_VARIABLE_FPS          #Format allows variable fps
    int AVFMT_NODIMENSIONS          #Format does not need width/height
    int AVFMT_NOSTREAMS             #Format does not require any streams
    int AVFMT_NOBINSEARCH           #Format does not allow to fall back on binary search via read_timestamp
    int AVFMT_NOGENSEARCH           #Format does not allow to fall back on generic search
    int AVFMT_NO_BYTE_SEEK          #Format does not allow seeking by bytes
    int AVFMT_ALLOW_FLUSH           #Format allows flushing. If not set, the muxer will not receive a NULL packet in the write_packet function
    int AVFMT_TS_NONSTRICT          #Format does not require strictly increasing timestamps, but they must still be monotonic
    int AVFMT_TS_NEGATIVE           #Format allows muxing negative timestamps.
    int AVFMT_SEEK_TO_PTS           #Seeking is based on PTS

    ctypedef struct AVStream:
        int         index           #stream index in AVFormatContext
        int         id
        AVCodecContext *codec
        AVRational  time_base
        int64_t     start_time
        int64_t     duration
        int64_t     nb_frames       #number of frames in this stream if known or 0
        #AVDiscard   discard         #Selects which packets can be discarded at will and do not need to be demuxed.
        AVRational  avg_frame_rate
        AVCodecParameters *codecpar

    ctypedef struct AVOutputFormat:
        const char  *name
        const char  *long_name
        const char  *mime_type
        const char  *extensions
        AVCodecID   audio_codec
        AVCodecID   video_codec
        AVCodecID   subtitle_codec
        int         flags       #AVFMT_NOFILE, AVFMT_NEEDNUMBER, AVFMT_GLOBALHEADER, AVFMT_NOTIMESTAMPS, AVFMT_VARIABLE_FPS, AVFMT_NODIMENSIONS, AVFMT_NOSTREAMS, AVFMT_ALLOW_FLUSH, AVFMT_TS_NONSTRICT, AVFMT_TS_NEGATIVE More...
        int         (*query_codec)(AVCodecID id, int std_compliance)

    void av_register_all()
    AVOutputFormat *av_oformat_next(const AVOutputFormat *f)
    int avformat_alloc_output_context2(AVFormatContext **ctx, AVOutputFormat *oformat, const char *format_name, const char *filename)
    void avformat_free_context(AVFormatContext *s)

    int avcodec_parameters_from_context(AVCodecParameters *par, const AVCodecContext *codec)
    AVStream *avformat_new_stream(AVFormatContext *s, const AVCodec *c)
    int avformat_write_header(AVFormatContext *s, AVDictionary **options)
    int av_write_trailer(AVFormatContext *s)
    int av_write_frame(AVFormatContext *s, AVPacket *pkt)


H264_PROFILE_NAMES = {
    FF_PROFILE_H264_CONSTRAINED             : "constrained",
    FF_PROFILE_H264_INTRA                   : "intra",
    FF_PROFILE_H264_BASELINE                : "baseline",
    FF_PROFILE_H264_CONSTRAINED_BASELINE    : "constrained baseline",
    FF_PROFILE_H264_MAIN                    : "main",
    FF_PROFILE_H264_EXTENDED                : "extended",
    FF_PROFILE_H264_HIGH                    : "high",
    FF_PROFILE_H264_HIGH_10                 : "high10",
    FF_PROFILE_H264_HIGH_10_INTRA           : "high10 intra",
    FF_PROFILE_H264_MULTIVIEW_HIGH          : "multiview high",
    FF_PROFILE_H264_HIGH_422                : "high422",
    FF_PROFILE_H264_HIGH_422_INTRA          : "high422 intra",
    FF_PROFILE_H264_STEREO_HIGH             : "stereo high",
    FF_PROFILE_H264_HIGH_444                : "high444",
    FF_PROFILE_H264_HIGH_444_PREDICTIVE     : "high444 predictive",
    FF_PROFILE_H264_HIGH_444_INTRA          : "high444 intra",
    FF_PROFILE_H264_CAVLC_444               : "cavlc 444",
    }
H264_PROFILES = dict((v,k) for k,v in H264_PROFILE_NAMES.items())

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

AVFMTCTX = {
            AVFMTCTX_NOHEADER       : "NOHEADER",
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

FMT_FLAGS = {
             AVFMT_FLAG_GENPTS          : "GENPTS",
             AVFMT_FLAG_IGNIDX          : "IGNIDX",
             AVFMT_FLAG_NONBLOCK        : "NONBLOCK",
             AVFMT_FLAG_IGNDTS          : "IGNDTS",
             AVFMT_FLAG_NOFILLIN        : "NOFILLIN",
             AVFMT_FLAG_NOPARSE         : "NOPARSE",
             AVFMT_FLAG_NOBUFFER        : "NOBUFFER",
             AVFMT_FLAG_CUSTOM_IO       : "CUSTOM_IO",
             AVFMT_FLAG_DISCARD_CORRUPT : "DISCARD_CORRUPT",
             AVFMT_FLAG_FLUSH_PACKETS   : "FLUSH_PACKETS",
             AVFMT_FLAG_BITEXACT        : "BITEXACT",
             AVFMT_FLAG_MP4A_LATM       : "MP4A_LATM",
             AVFMT_FLAG_SORT_DTS        : "SORT_DTS",
             AVFMT_FLAG_PRIV_OPT        : "PRIV_OPT",
             AVFMT_FLAG_KEEP_SIDE_DATA  : "KEEP_SIDE_DATA",
             AVFMT_FLAG_FAST_SEEK       : "FAST_SEEK",
             }

AVFMT = {
         AVFMT_NOFILE           : "NOFILE",
         AVFMT_NEEDNUMBER       : "NEEDNUMBER",
         AVFMT_SHOW_IDS         : "SHOW_IDS",
         AVFMT_RAWPICTURE       : "RAWPICTURE",
         AVFMT_GLOBALHEADER     : "GLOBALHEADER",
         AVFMT_NOTIMESTAMPS     : "NOTIMESTAMPS",
         AVFMT_GENERIC_INDEX    : "GENERIC_INDEX",
         AVFMT_TS_DISCONT       : "TS_DISCONT",
         AVFMT_VARIABLE_FPS     : "VARIABLE_FPS",
         AVFMT_NODIMENSIONS     : "NODIMENSIONS",
         AVFMT_NOSTREAMS        : "NOSTREAMS",
         AVFMT_NOBINSEARCH      : "NOBINSEARCH",
         AVFMT_NOGENSEARCH      : "NOGENSEARCH",
         AVFMT_NO_BYTE_SEEK     : "NO_BYTE_SEEK",
         AVFMT_ALLOW_FLUSH      : "ALLOW_FLUSH",
         AVFMT_TS_NONSTRICT     : "TS_NONSTRICT",
         AVFMT_TS_NEGATIVE      : "TS_NEGATIVE",
         AVFMT_SEEK_TO_PTS      : "SEEK_TO_PTS",
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


def get_muxer_formats():
    av_register_all()
    cdef AVOutputFormat *fmt = NULL
    formats = {}
    while True:
        fmt = av_oformat_next(fmt)
        if fmt==NULL:
            break
        name = fmt.name
        long_name = fmt.long_name
        formats[name] = long_name
    return formats
log("AV Output Formats:")
print_nested_dict(get_muxer_formats(), print_fn=log.debug)

cdef AVOutputFormat* get_av_output_format(name):
    cdef AVOutputFormat *fmt = NULL
    while True:
        fmt = av_oformat_next(fmt)
        if fmt==NULL:
            break
        if name==fmt.name:
            return fmt
    return NULL


def get_version():
    return (LIBAVCODEC_VERSION_MAJOR, LIBAVCODEC_VERSION_MINOR, LIBAVCODEC_VERSION_MICRO)

avcodec_register_all()
CODECS = []
if avcodec_find_encoder(AV_CODEC_ID_H264)!=NULL:
    CODECS.append("h264+mp4")
if avcodec_find_encoder(AV_CODEC_ID_VP8)!=NULL:
    CODECS.append("vp8+webm")
#if avcodec_find_encoder(AV_CODEC_ID_VP9)!=NULL:
#    CODECS.append("vp9+webm")
#if avcodec_find_encoder(AV_CODEC_ID_H265)!=NULL:
#    CODECS.append("h265")
if avcodec_find_encoder(AV_CODEC_ID_MPEG4)!=NULL:
    CODECS.append("mpeg4+mp4")
log("enc_ffmpeg CODECS=%s", csv(CODECS))

cdef av_error_str(int errnum):
    cdef char[128] err_str
    cdef int i = 0
    if av_strerror(errnum, err_str, 128)==0:
        while i<128 and err_str[i]!=0:
            i += 1
        return bytestostr(err_str[:i])
    return "error %s" % errnum

DEF DEFAULT_BUF_LEN = 64*1024


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
             "muxers"       : get_muxer_formats(),
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


GEN_TO_ENCODER = weakref.WeakValueDictionary()


cdef list_options(void *obj, const AVClass *av_class):
    if av_class==NULL:
        return
    cdef const AVOption *option = <const AVOption*> av_class.option
    options = []
    while option!=NULL:
        oname = option.name
        options.append(oname)
        option = av_opt_next(obj, option)
    log("%s options: %s", av_class.class_name, csv(options))
    cdef void *child = NULL
    cdef const AVClass *child_class = NULL
    while True:
        child = av_opt_child_next(obj, child)
        if child==NULL:
            return
        child_class = (<AVClass**> child)[0]
        list_options(child, child_class)


cdef int write_packet(void *opaque, uint8_t *buf, int buf_size):
    global GEN_TO_ENCODER
    encoder = GEN_TO_ENCODER.get(<unsigned long> opaque)
    #log.warn("write_packet(%#x, %#x, %#x) encoder=%s", <unsigned long> opaque, <unsigned long> buf, buf_size, type(encoder))
    if not encoder:
        log.error("Error: write_packet called for unregistered encoder %i!", <unsigned long> opaque)
        return -1
    return encoder.write_packet(<unsigned long> buf, buf_size)

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
    #muxer:
    cdef AVFormatContext *muxer_ctx
    cdef unsigned char *buffer
    cdef object buffers
    cdef int64_t offset
    cdef object muxer_format
    cdef object file
    #video:
    cdef AVCodec *video_codec
    cdef AVStream *video_stream
    cdef AVCodecContext *video_ctx
    cdef AVPixelFormat pix_fmt
    cdef object src_format
    cdef AVFrame *av_frame
    cdef unsigned long frames
    cdef unsigned int width
    cdef unsigned int height
    cdef object encoding
    cdef object profile
    #audio:
    cdef AVCodec *audio_codec
    cdef AVStream *audio_stream
    cdef AVCodecContext *audio_ctx

    cdef object __weakref__

    def init_context(self, unsigned int width, unsigned int height, src_format, dst_formats, encoding, int quality, int speed, scaling, options):    #@DuplicatedSignature
        cdef int r
        global CODECS, generation
        assert encoding in CODECS
        assert src_format in get_input_colorspaces(encoding), "invalid colorspace: %s" % src_format
        self.encoding = encoding
        self.muxer_format = encoding.split("+")[1]  #ie: "mp4"   #"mov", "f4v"
        assert self.muxer_format in ("mp4", "webm")
        self.width = width
        self.height = height
        self.src_format = src_format
        self.pix_fmt = FORMAT_TO_ENUM.get(src_format, AV_PIX_FMT_NONE)
        if self.pix_fmt==AV_PIX_FMT_NONE:
            raise Exception("invalid pixel format: %s", src_format)
        self.buffers = []

        codec = self.encoding.split("+")[0]
        avcodec_register_all()
        cdef AVCodecID video_codec_id
        if codec=="h264":
            video_codec_id = AV_CODEC_ID_H264
        elif codec=="h265":
            video_codec_id = AV_CODEC_ID_H265
        elif codec=="vp8":
            video_codec_id = AV_CODEC_ID_VP8
        elif codec=="vp9":
            video_codec_id = AV_CODEC_ID_VP9
        elif codec=="mpeg4":
            video_codec_id = AV_CODEC_ID_MPEG4
        else:
            raise Exception("invalid codec; %s" % self.encoding)
        self.video_codec = avcodec_find_encoder(video_codec_id)
        if self.video_codec==NULL:
            raise Exception("codec %s not found!" % self.encoding)
        log("%s: \"%s\", codec flags: %s", self.video_codec.name, self.video_codec.long_name, flagscsv(CAPS, self.video_codec.capabilities))

        #ie: client side as: "encoding.h264+mpeg4.YUV420P.profile" : "main"
        profile = options.get("%s.%s.profile" % (self.encoding, src_format), "main")
        try:
            self.init_encoder(profile)
        except Exception as e:
            log("init_encoder(%s) failed", profile, exc_info=True)
            self.clean()
            raise
        else:
            log("enc_ffmpeg.Encoder.init_context(%s, %s, %s) self=%s", self.width, self.height, self.src_format, self.get_info())

    def init_encoder(self, profile):
        cdef AVDictionary *opts = NULL
        cdef AVDictionary *muxer_opts = NULL
        global GEN_TO_ENCODER
        cdef AVOutputFormat *oformat = get_av_output_format(strtobytes(self.muxer_format))
        if oformat==NULL:
            raise Exception("libavformat does not support %s" % self.muxer_format)
        log("init_encoder() AVOutputFormat(%s)=%#x, flags=%s", self.muxer_format, <unsigned long> oformat, flagscsv(AVFMT, oformat.flags))
        if oformat.flags & AVFMT_ALLOW_FLUSH==0:
            raise Exception("AVOutputFormat(%s) does not support flushing!" % self.muxer_format)
        r = avformat_alloc_output_context2(&self.muxer_ctx, oformat, strtobytes(self.muxer_format), NULL)
        if r!=0:
            msg = av_error_str(r)
            raise Exception("libavformat cannot allocate context: %s" % msg)
        log("init_encoder() avformat_alloc_output_context2 returned %i for %s, format context=%#x, flags=%s, ctx_flags=%s", r, self.muxer_format, <unsigned long> self.muxer_ctx,
            flagscsv(FMT_FLAGS, self.muxer_ctx.flags), flagscsv(AVFMTCTX, self.muxer_ctx.ctx_flags))
        list_options(self.muxer_ctx, self.muxer_ctx.av_class)

        cdef int64_t v = 0
        movflags = b""
        if self.muxer_format=="mp4":
            #movflags = "empty_moov+omit_tfhd_offset+frag_keyframe+default_base_moof"
            movflags = b"empty_moov+frag_keyframe+default_base_moof+faststart"
        elif self.muxer_format=="webm":
            movflags = b"dash+live"
        if movflags:
            r = av_dict_set(&muxer_opts, b"movflags", movflags, 0)
            if r!=0:
                msg = av_error_str(r)
                raise Exception("failed to set %s muxer 'movflags' options '%s': %s" % (self.muxer_format, movflags, msg))

        cdef unsigned long gen = generation.increase()
        GEN_TO_ENCODER[gen] = self
        self.buffer = <unsigned char*> av_malloc(DEFAULT_BUF_LEN)
        if self.buffer==NULL:
            raise Exception("failed to allocate %iKB of memory" % (DEFAULT_BUF_LEN//1024))
        self.muxer_ctx.pb = avio_alloc_context(self.buffer, DEFAULT_BUF_LEN, 1, <void *> gen, NULL, write_packet, NULL)
        if self.muxer_ctx.pb==NULL:
            raise Exception("libavformat failed to allocate io context")
        log("init_encoder() saving %s stream to bitstream buffer %#x", self.encoding, <unsigned long> self.buffer)
        self.muxer_ctx.flush_packets = 1
        self.muxer_ctx.bit_rate = 250000
        self.muxer_ctx.start_time = 0
        #self.muxer_ctx.duration = 999999
        self.muxer_ctx.start_time_realtime = int(time.time()*1000)
        self.muxer_ctx.strict_std_compliance = 1

        self.video_stream = avformat_new_stream(self.muxer_ctx, NULL)    #self.video_codec
        self.video_stream.id = 0
        log("init_encoder() video: avformat_new_stream=%#x, nb streams=%i", <unsigned long> self.video_stream, self.muxer_ctx.nb_streams)

        self.video_ctx = avcodec_alloc_context3(self.video_codec)
        if self.video_ctx==NULL:
            raise Exception("failed to allocate video codec context!")
        list_options(self.video_ctx, self.video_ctx.av_class)

        cdef int b_frames = 0
        #we need a framerate.. make one up:
        self.video_ctx.framerate.num = 1
        self.video_ctx.framerate.den = 25
        self.video_ctx.time_base.num = 1
        self.video_ctx.time_base.den = 25
        #self.video_ctx.refcounted_frames = 1
        self.video_ctx.max_b_frames = b_frames*1
        self.video_ctx.has_b_frames = b_frames
        self.video_ctx.delay = 0
        self.video_ctx.gop_size = 1
        self.video_ctx.width = self.width
        self.video_ctx.height = self.height
        self.video_ctx.bit_rate = 2500000
        self.video_ctx.pix_fmt = self.pix_fmt
        self.video_ctx.thread_safe_callbacks = 1
        self.video_ctx.thread_type = THREAD_TYPE
        self.video_ctx.thread_count = THREAD_COUNT     #0=auto
        #if oformat.flags & AVFMT_GLOBALHEADER:
        self.video_ctx.flags |= CODEC_FLAG_GLOBAL_HEADER
        self.video_ctx.flags2 |= CODEC_FLAG2_FAST   #may cause "no deblock across slices" - which should be fine
        if self.encoding.startswith("h264") and profile:
            r = av_dict_set(&opts, b"vprofile", strtobytes(profile), 0)
            log("av_dict_set vprofile=%s returned %i", profile, r)
            if r==0:
                self.profile = profile
            r = av_dict_set(&opts, "tune", "zerolatency", 0)
            log("av_dict_set tune=zerolatency returned %i", r)
            r = av_dict_set(&opts, "preset","ultrafast", 0)
            log("av_dict_set preset=ultrafast returned %i", r)
        elif self.encoding.startswith("vp"):
            for k,v in {
                        "lag-in-frames"     : 0,
                        "realtime"          : 1,
                        "rc_lookahead"      : 0,
                        "error_resilient"   : 0,
                        }.items():
                r = av_dict_set_int(&opts, strtobytes(k), v, 0)
                if r!=0:
                    log.error("Error: failed to set video context option '%s' to %i:", k, v)
                    log.error(" %s", av_error_str(r))
        log("init_encoder() thread-type=%i, thread-count=%i", THREAD_TYPE, THREAD_COUNT)
        log("init_encoder() codec flags: %s", flagscsv(CODEC_FLAGS, self.video_ctx.flags))
        log("init_encoder() codec flags2: %s", flagscsv(CODEC_FLAGS2, self.video_ctx.flags2))

        r = avcodec_open2(self.video_ctx, self.video_codec, &opts)
        av_dict_free(&opts)
        if r!=0:
            raise Exception("could not open %s encoder context: %s" % (self.encoding, av_error_str(r)))

        r = avcodec_parameters_from_context(self.video_stream.codecpar, self.video_ctx)
        if r<0:
            raise Exception("could not copy video context parameters %#x: %s" % (<unsigned long> self.video_stream.codecpar, av_error_str(r)))

        if AUDIO:
            self.audio_codec = avcodec_find_encoder(AV_CODEC_ID_AAC)
            if self.audio_codec==NULL:
                raise Exception("cannot find audio codec!")
            log("init_encoder() audio_codec=%#x", <unsigned long> self.audio_codec)
            self.audio_stream = avformat_new_stream(self.muxer_ctx, NULL)
            self.audio_stream.id = 1
            log("init_encoder() audio: avformat_new_stream=%#x, nb streams=%i", <unsigned long> self.audio_stream, self.muxer_ctx.nb_streams)
            self.audio_ctx = avcodec_alloc_context3(self.audio_codec)
            log("init_encoder() audio_context=%#x", <unsigned long> self.audio_ctx)
            self.audio_ctx.sample_fmt = AV_SAMPLE_FMT_FLTP
            self.audio_ctx.time_base.den = 25
            self.audio_ctx.time_base.num = 1
            self.audio_ctx.bit_rate = 64000
            self.audio_ctx.sample_rate = 44100
            self.audio_ctx.channels = 2
            #if audio_codec.capabilities & CODEC_CAP_VARIABLE_FRAME_SIZE:
            #    pass
            #cdef AVDictionary *opts = NULL
            #av_dict_set(&opts, "strict", "experimental", 0)
            #r = avcodec_open2(audio_ctx, audio_codec, &opts)
            #av_dict_free(&opts)
            r = avcodec_open2(self.audio_ctx, self.audio_codec, NULL)
            if r!=0:
                raise Exception("could not open %s encoder context: %s" % (self.encoding, av_error_str(r)))
            if r!=0:
                raise Exception("could not open %s encoder context: %s" % ("aac", av_error_str(r)))
            r = avcodec_parameters_from_context(self.audio_stream.codecpar, self.audio_ctx)
            if r<0:
                raise Exception("could not copy audio context parameters %#x: %s" % (<unsigned long> self.audio_stream.codecpar, av_error_str(r)))

        log("init_encoder() writing %s header", self.muxer_format)
        r = avformat_write_header(self.muxer_ctx, &muxer_opts)
        av_dict_free(&muxer_opts)
        if r!=0:
            msg = av_error_str(r)
            raise Exception("libavformat failed to write header: %s" % msg)

        self.av_frame = av_frame_alloc()
        if self.av_frame==NULL:
            raise Exception("could not allocate an AVFrame for encoding")
        self.frames = 0

        if SAVE_TO_FILE is not None:
            filename = SAVE_TO_FILE+"-"+self.encoding+"-"+str(gen)+".%s" % self.muxer_format
            self.file = open(filename, 'wb')
            log.info("saving %s stream to %s", self.encoding, filename)


    def clean(self):
        try:
            self.clean_encoder()
        except:
            log.error("cleanup failed", exc_info=True)
        self.video_codec = NULL
        self.audio_codec = NULL
        self.pix_fmt = 0
        self.src_format = ""
        self.av_frame = NULL                        #should be redundant
        self.frames = 0
        self.width = 0
        self.height = 0
        self.encoding = ""
        self.buffers = []
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
        if self.muxer_ctx!=NULL:
            if self.frames>0:
                log("clean_encoder() writing trailer to stream")
                av_write_trailer(self.muxer_ctx)
                if self.muxer_ctx.pb!=NULL:
                    av_free(self.muxer_ctx.pb)
                    self.muxer_ctx.pb = NULL
            log("clean_encoder() freeing av format context %#x", <unsigned long> self.muxer_ctx)
            avformat_free_context(self.muxer_ctx)
            self.muxer_ctx = NULL
            log("clean_encoder() freeing bitstream buffer %#x", <unsigned long> self.buffer)
            if self.buffer!=NULL:
                av_free(self.buffer)
                self.buffer = NULL
        cdef unsigned long ctx_key          #@DuplicatedSignature
        log("clean_encoder() freeing AVCodecContext: %#x", <unsigned long> self.video_ctx)
        if self.video_ctx!=NULL:
            r = avcodec_close(self.video_ctx)
            if r!=0:
                log.error("Error: failed to close video encoder context %#x", <unsigned long> self.video_ctx)
                log.error(" %s", av_error_str(r))
            av_free(self.video_ctx)
            self.video_ctx = NULL
        if self.audio_ctx!=NULL:
            r = avcodec_close(self.audio_ctx)
            if r!=0:
                log.error("Error: failed to close audio encoder context %#x", <unsigned long> self.audio_ctx)
                log.error(" %s", av_error_str(r))
            av_free(self.audio_ctx)
            self.audio_ctx = NULL
        log("clean_encoder() done")

    def __repr__(self):                      #@DuplicatedSignature
        if self.is_closed():
            return "enc_ffmpeg.Encoder(*closed*)"
        return "enc_ffmpeg.Encoder(%s)" % self.get_info()

    def get_info(self):                      #@DuplicatedSignature
        info = {
                "version"   : get_version(),
                "encoding"  : self.encoding,
                "muxer"     : self.muxer_format,
                "formats"   : get_input_colorspaces(self.encoding),
                "type"      : self.get_type(),
                "frames"    : self.frames,
                "width"     : self.width,
                "height"    : self.height,
                }
        if self.video_codec:
            info["video-codec"] = self.video_codec.name[:]
            info["video-description"] = self.video_codec.long_name[:]
        if self.audio_codec:
            info["audio-codec"] = self.audio_codec.name[:]
            info["audio-description"] = self.audio_codec.long_name[:]
        if self.src_format:
            info["src_format"] = self.src_format
        if not self.is_closed():
            info["encoder_width"] = self.video_ctx.width
            info["encoder_height"] = self.video_ctx.height
        else:
            info["closed"] = True
        return info

    def is_closed(self):
        return self.video_ctx==NULL

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
        assert self.video_ctx!=NULL, "no codec context! (not initialized or already closed)"
        assert self.video_codec!=NULL, "no video codec!"

        if image:
            assert image.get_pixel_format()==self.src_format, "invalid input format %s, expected %s" % (image.get_pixel_format, self.src_format)
            assert image.get_width()==self.width and image.get_height()==self.height

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
            self.av_frame.pict_type = AV_PICTURE_TYPE_I
            #self.av_frame.key_frame = 1
            #else:
            #    self.av_frame.pict_type = AV_PICTURE_TYPE_P
            #self.av_frame.quality = 1
            frame = self.av_frame
        else:
            assert options.get("flush")
            frame = NULL

        with nogil:
            ret = avcodec_send_frame(self.video_ctx, frame)
        if ret!=0:
            self.log_av_error(image, ret, options)
            raise Exception(av_error_str(ret))

        buf_len = 1024+self.width*self.height
        av_init_packet(&avpkt)
        avpkt.data = <uint8_t *> xmemalign(buf_len)
        avpkt.size = buf_len
        assert ret==0
        client_options = {}
        while ret==0:
            with nogil:
                ret = avcodec_receive_packet(self.video_ctx, &avpkt)
            if ret==-errno.EAGAIN:
                log("ffmpeg avcodec_receive_packet EAGAIN")
                break
            if ret!=0:
                if not image:
                    log("avcodec_receive_packet returned error '%s' for flush request", av_error_str(ret))
                else:
                    log("avcodec_receive_packet returned error '%s' for image %s, returning existing buffer", av_error_str(ret), image)
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

            avpkt.stream_index = self.video_stream.index
            r = av_write_frame(self.muxer_ctx, &avpkt)
            log("av_write_frame packet returned %i", r)
            if ret<0:
                free(avpkt.data)
                self.log_av_error(image, ret, options)
                raise Exception(av_error_str(ret))
            while True:
                r = av_write_frame(self.muxer_ctx, NULL)
                log("av_write_frame flush returned %i", r)
                if r==1:
                    break
                if ret<0:
                    free(avpkt.data)
                    self.log_av_error(image, ret, options)
                    raise Exception(av_error_str(ret))
        av_packet_unref(&avpkt)
        free(avpkt.data)
        if self.frames==0 and self.profile:
            client_options["profile"] = self.profile
            client_options["level"] = "3.0"
        client_options["frame"] = int(self.frames)
        if self.frames==0:
            log("%s client options for first frame: %s", self.encoding, client_options)
        self.frames += 1
        data = b"".join(self.buffers)
        log("compress_image(%s) %5i bytes (%i buffers) for %4s frame %-3i, client options: %s", image, len(data), len(self.buffers), self.encoding, self.frames, client_options)
        if self.buffers and self.file:
            for x in self.buffers:
                self.file.write(x)
            self.file.flush()
        self.buffers = []
        return data, client_options

    def flush(self, delayed):
        v = self.compress_image(None, options={"flush" : True})
        #ffmpeg context cannot be re-used after a flush..
        self.clean()
        return v

    def write_packet(self, unsigned long buf, int buf_size):
        log("write_packet(%#x, %#x)", <unsigned long> buf, buf_size)
        cdef uint8_t *cbuf = <uint8_t*> buf
        buffer = cbuf[:buf_size]
        self.buffers.append(buffer)
        return buf_size


def selftest(full=False):
    global CODECS
    from xpra.codecs.codec_checks import testencoder
    from xpra.codecs.enc_ffmpeg import encoder
    try:
        suspend_nonfatal_logging()
        CODECS = testencoder(encoder, full)
    finally:
        pass
        resume_nonfatal_logging()
