# This file is part of Xpra.
# Copyright (C) 2012-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False, wraparound=False, cdivision=True, language_level=3

import errno
import weakref
from xpra.log import Logger
log = Logger("decoder", "avcodec")

from xpra.os_util import bytestostr
from xpra.util import csv
from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.codecs.libav_common.av_log cimport override_logger, restore_logger, av_error_str #@UnresolvedImport pylint: disable=syntax-error
from xpra.codecs.libav_common.av_log import suspend_nonfatal_logging, resume_nonfatal_logging
from xpra.buffers.membuf cimport memalign, object_as_buffer, memory_as_pybuffer

from libc.stdint cimport uintptr_t, uint8_t
from libc.stdlib cimport free
from libc.string cimport memset, memcpy


cdef extern from "register_compat.h":
    void register_all()

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
    #grep AV_PIX_FMT_ /usr/include/xpra/libavutil/pixfmt.h | grep -e "^\s*AV_PIX_FMT"  | sed 's+,+ +g' | awk '{print "    AVPixelFormat "$1}'
    AVPixelFormat AV_PIX_FMT_NONE
    AVPixelFormat AV_PIX_FMT_YUV420P
    AVPixelFormat AV_PIX_FMT_YUYV422
    AVPixelFormat AV_PIX_FMT_RGB24
    AVPixelFormat AV_PIX_FMT_BGR24
    AVPixelFormat AV_PIX_FMT_YUV422P
    AVPixelFormat AV_PIX_FMT_YUV444P
    AVPixelFormat AV_PIX_FMT_YUV410P
    AVPixelFormat AV_PIX_FMT_YUV411P
    AVPixelFormat AV_PIX_FMT_GRAY8
    AVPixelFormat AV_PIX_FMT_MONOWHITE
    AVPixelFormat AV_PIX_FMT_MONOBLACK
    AVPixelFormat AV_PIX_FMT_PAL8
    AVPixelFormat AV_PIX_FMT_YUVJ420P
    AVPixelFormat AV_PIX_FMT_YUVJ422P
    AVPixelFormat AV_PIX_FMT_YUVJ444P
    AVPixelFormat AV_PIX_FMT_UYVY422
    AVPixelFormat AV_PIX_FMT_UYYVYY411
    AVPixelFormat AV_PIX_FMT_BGR8
    AVPixelFormat AV_PIX_FMT_BGR4
    AVPixelFormat AV_PIX_FMT_BGR4_BYTE
    AVPixelFormat AV_PIX_FMT_RGB8
    AVPixelFormat AV_PIX_FMT_RGB4
    AVPixelFormat AV_PIX_FMT_RGB4_BYTE
    AVPixelFormat AV_PIX_FMT_NV12
    AVPixelFormat AV_PIX_FMT_NV21
    AVPixelFormat AV_PIX_FMT_ARGB
    AVPixelFormat AV_PIX_FMT_RGBA
    AVPixelFormat AV_PIX_FMT_ABGR
    AVPixelFormat AV_PIX_FMT_BGRA
    AVPixelFormat AV_PIX_FMT_GRAY16BE
    AVPixelFormat AV_PIX_FMT_GRAY16LE
    AVPixelFormat AV_PIX_FMT_YUV440P
    AVPixelFormat AV_PIX_FMT_YUVJ440P
    AVPixelFormat AV_PIX_FMT_YUVA420P
    AVPixelFormat AV_PIX_FMT_RGB48BE
    AVPixelFormat AV_PIX_FMT_RGB48LE
    AVPixelFormat AV_PIX_FMT_RGB565BE
    AVPixelFormat AV_PIX_FMT_RGB565LE
    AVPixelFormat AV_PIX_FMT_RGB555BE
    AVPixelFormat AV_PIX_FMT_RGB555LE
    AVPixelFormat AV_PIX_FMT_BGR565BE
    AVPixelFormat AV_PIX_FMT_BGR565LE
    AVPixelFormat AV_PIX_FMT_BGR555BE
    AVPixelFormat AV_PIX_FMT_BGR555LE
    AVPixelFormat AV_PIX_FMT_VAAPI_MOCO
    AVPixelFormat AV_PIX_FMT_VAAPI_IDCT
    AVPixelFormat AV_PIX_FMT_VAAPI_VLD
    AVPixelFormat AV_PIX_FMT_VAAPI
    AVPixelFormat AV_PIX_FMT_YUV420P16LE
    AVPixelFormat AV_PIX_FMT_YUV420P16BE
    AVPixelFormat AV_PIX_FMT_YUV422P16LE
    AVPixelFormat AV_PIX_FMT_YUV422P16BE
    AVPixelFormat AV_PIX_FMT_YUV444P16LE
    AVPixelFormat AV_PIX_FMT_YUV444P16BE
    AVPixelFormat AV_PIX_FMT_DXVA2_VLD
    AVPixelFormat AV_PIX_FMT_RGB444LE
    AVPixelFormat AV_PIX_FMT_RGB444BE
    AVPixelFormat AV_PIX_FMT_BGR444LE
    AVPixelFormat AV_PIX_FMT_BGR444BE
    AVPixelFormat AV_PIX_FMT_YA8
    AVPixelFormat AV_PIX_FMT_Y400A
    AVPixelFormat AV_PIX_FMT_BGR48BE
    AVPixelFormat AV_PIX_FMT_BGR48LE
    AVPixelFormat AV_PIX_FMT_YUV420P9BE
    AVPixelFormat AV_PIX_FMT_YUV420P9LE
    AVPixelFormat AV_PIX_FMT_YUV420P10BE
    AVPixelFormat AV_PIX_FMT_YUV420P10LE
    AVPixelFormat AV_PIX_FMT_YUV422P10BE
    AVPixelFormat AV_PIX_FMT_YUV422P10LE
    AVPixelFormat AV_PIX_FMT_YUV444P9BE
    AVPixelFormat AV_PIX_FMT_YUV444P9LE
    AVPixelFormat AV_PIX_FMT_YUV444P10BE
    AVPixelFormat AV_PIX_FMT_YUV444P10LE
    AVPixelFormat AV_PIX_FMT_YUV422P9BE
    AVPixelFormat AV_PIX_FMT_YUV422P9LE
    AVPixelFormat AV_PIX_FMT_GBRP
    AVPixelFormat AV_PIX_FMT_GBR24P
    AVPixelFormat AV_PIX_FMT_GBRP9BE
    AVPixelFormat AV_PIX_FMT_GBRP9LE
    AVPixelFormat AV_PIX_FMT_GBRP10BE
    AVPixelFormat AV_PIX_FMT_GBRP10LE
    AVPixelFormat AV_PIX_FMT_GBRP16BE
    AVPixelFormat AV_PIX_FMT_GBRP16LE
    AVPixelFormat AV_PIX_FMT_YUVA422P
    AVPixelFormat AV_PIX_FMT_YUVA444P
    AVPixelFormat AV_PIX_FMT_YUVA420P9BE
    AVPixelFormat AV_PIX_FMT_YUVA420P9LE
    AVPixelFormat AV_PIX_FMT_YUVA422P9BE
    AVPixelFormat AV_PIX_FMT_YUVA422P9LE
    AVPixelFormat AV_PIX_FMT_YUVA444P9BE
    AVPixelFormat AV_PIX_FMT_YUVA444P9LE
    AVPixelFormat AV_PIX_FMT_YUVA420P10BE
    AVPixelFormat AV_PIX_FMT_YUVA420P10LE
    AVPixelFormat AV_PIX_FMT_YUVA422P10BE
    AVPixelFormat AV_PIX_FMT_YUVA422P10LE
    AVPixelFormat AV_PIX_FMT_YUVA444P10BE
    AVPixelFormat AV_PIX_FMT_YUVA444P10LE
    AVPixelFormat AV_PIX_FMT_YUVA420P16BE
    AVPixelFormat AV_PIX_FMT_YUVA420P16LE
    AVPixelFormat AV_PIX_FMT_YUVA422P16BE
    AVPixelFormat AV_PIX_FMT_YUVA422P16LE
    AVPixelFormat AV_PIX_FMT_YUVA444P16BE
    AVPixelFormat AV_PIX_FMT_YUVA444P16LE
    AVPixelFormat AV_PIX_FMT_VDPAU
    AVPixelFormat AV_PIX_FMT_XYZ12LE
    AVPixelFormat AV_PIX_FMT_XYZ12BE
    AVPixelFormat AV_PIX_FMT_NV16
    AVPixelFormat AV_PIX_FMT_NV20LE
    AVPixelFormat AV_PIX_FMT_NV20BE
    AVPixelFormat AV_PIX_FMT_RGBA64BE
    AVPixelFormat AV_PIX_FMT_RGBA64LE
    AVPixelFormat AV_PIX_FMT_BGRA64BE
    AVPixelFormat AV_PIX_FMT_BGRA64LE
    AVPixelFormat AV_PIX_FMT_YVYU422
    AVPixelFormat AV_PIX_FMT_YA16BE
    AVPixelFormat AV_PIX_FMT_YA16LE
    AVPixelFormat AV_PIX_FMT_GBRAP
    AVPixelFormat AV_PIX_FMT_GBRAP16BE
    AVPixelFormat AV_PIX_FMT_GBRAP16LE
    AVPixelFormat AV_PIX_FMT_QSV
    AVPixelFormat AV_PIX_FMT_MMAL
    AVPixelFormat AV_PIX_FMT_D3D11VA_VLD
    AVPixelFormat AV_PIX_FMT_CUDA
    AVPixelFormat AV_PIX_FMT_0RGB
    AVPixelFormat AV_PIX_FMT_RGB0
    AVPixelFormat AV_PIX_FMT_0BGR
    AVPixelFormat AV_PIX_FMT_BGR0
    AVPixelFormat AV_PIX_FMT_YUV420P12BE
    AVPixelFormat AV_PIX_FMT_YUV420P12LE
    AVPixelFormat AV_PIX_FMT_YUV420P14BE
    AVPixelFormat AV_PIX_FMT_YUV420P14LE
    AVPixelFormat AV_PIX_FMT_YUV422P12BE
    AVPixelFormat AV_PIX_FMT_YUV422P12LE
    AVPixelFormat AV_PIX_FMT_YUV422P14BE
    AVPixelFormat AV_PIX_FMT_YUV422P14LE
    AVPixelFormat AV_PIX_FMT_YUV444P12BE
    AVPixelFormat AV_PIX_FMT_YUV444P12LE
    AVPixelFormat AV_PIX_FMT_YUV444P14BE
    AVPixelFormat AV_PIX_FMT_YUV444P14LE
    AVPixelFormat AV_PIX_FMT_GBRP12BE
    AVPixelFormat AV_PIX_FMT_GBRP12LE
    AVPixelFormat AV_PIX_FMT_GBRP14BE
    AVPixelFormat AV_PIX_FMT_GBRP14LE
    AVPixelFormat AV_PIX_FMT_YUVJ411P
    AVPixelFormat AV_PIX_FMT_BAYER_BGGR8
    AVPixelFormat AV_PIX_FMT_BAYER_RGGB8
    AVPixelFormat AV_PIX_FMT_BAYER_GBRG8
    AVPixelFormat AV_PIX_FMT_BAYER_GRBG8
    AVPixelFormat AV_PIX_FMT_BAYER_BGGR16LE
    AVPixelFormat AV_PIX_FMT_BAYER_BGGR16BE
    AVPixelFormat AV_PIX_FMT_BAYER_RGGB16LE
    AVPixelFormat AV_PIX_FMT_BAYER_RGGB16BE
    AVPixelFormat AV_PIX_FMT_BAYER_GBRG16LE
    AVPixelFormat AV_PIX_FMT_BAYER_GBRG16BE
    AVPixelFormat AV_PIX_FMT_BAYER_GRBG16LE
    AVPixelFormat AV_PIX_FMT_BAYER_GRBG16BE
    AVPixelFormat AV_PIX_FMT_XVMC
    AVPixelFormat AV_PIX_FMT_YUV440P10LE
    AVPixelFormat AV_PIX_FMT_YUV440P10BE
    AVPixelFormat AV_PIX_FMT_YUV440P12LE
    AVPixelFormat AV_PIX_FMT_YUV440P12BE
    AVPixelFormat AV_PIX_FMT_AYUV64LE
    AVPixelFormat AV_PIX_FMT_AYUV64BE
    AVPixelFormat AV_PIX_FMT_VIDEOTOOLBOX
    AVPixelFormat AV_PIX_FMT_P010LE
    AVPixelFormat AV_PIX_FMT_P010BE
    AVPixelFormat AV_PIX_FMT_GBRAP12BE
    AVPixelFormat AV_PIX_FMT_GBRAP12LE
    AVPixelFormat AV_PIX_FMT_GBRAP10BE
    AVPixelFormat AV_PIX_FMT_GBRAP10LE
    AVPixelFormat AV_PIX_FMT_MEDIACODEC
    AVPixelFormat AV_PIX_FMT_GRAY12BE
    AVPixelFormat AV_PIX_FMT_GRAY12LE
    AVPixelFormat AV_PIX_FMT_GRAY10BE
    AVPixelFormat AV_PIX_FMT_GRAY10LE
    AVPixelFormat AV_PIX_FMT_P016LE
    AVPixelFormat AV_PIX_FMT_P016BE
    AVPixelFormat AV_PIX_FMT_D3D11
    AVPixelFormat AV_PIX_FMT_GRAY9BE
    AVPixelFormat AV_PIX_FMT_GRAY9LE
    AVPixelFormat AV_PIX_FMT_GBRPF32BE
    AVPixelFormat AV_PIX_FMT_GBRPF32LE
    AVPixelFormat AV_PIX_FMT_GBRAPF32BE
    AVPixelFormat AV_PIX_FMT_GBRAPF32LE
    AVPixelFormat AV_PIX_FMT_DRM_PRIME
    #The following enums are not available in Ubuntu 18.04:
    #AVPixelFormat AV_PIX_FMT_OPENCL
    #AVPixelFormat AV_PIX_FMT_GRAY14BE
    #AVPixelFormat AV_PIX_FMT_GRAY14LE
    #AVPixelFormat AV_PIX_FMT_GRAYF32BE
    #AVPixelFormat AV_PIX_FMT_GRAYF32LE
    #The following enums are not available in Debian Buster:
    #AVPixelFormat AV_PIX_FMT_YUVA422P12BE
    #AVPixelFormat AV_PIX_FMT_YUVA422P12LE
    #AVPixelFormat AV_PIX_FMT_YUVA444P12BE
    #AVPixelFormat AV_PIX_FMT_YUVA444P12LE
    #AVPixelFormat AV_PIX_FMT_NV24
    #AVPixelFormat AV_PIX_FMT_NV42
    #AVPixelFormat AV_PIX_FMT_VULKAN
    #AVPixelFormat AV_PIX_FMT_Y210BE
    #AVPixelFormat AV_PIX_FMT_Y210LE
    #AVPixelFormat AV_PIX_FMT_NB


cdef extern from "libavcodec/avcodec.h":
    int AV_CODEC_FLAG2_FAST

    ctypedef struct AVFrame:
        uint8_t **data
        int *linesize
        int format
        void *opaque
        int width
        int height
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
        #int refcounted_frames

    AVCodecID AV_CODEC_ID_H264
    AVCodecID AV_CODEC_ID_H265
    AVCodecID AV_CODEC_ID_VP8
    AVCodecID AV_CODEC_ID_VP9
    AVCodecID AV_CODEC_ID_MPEG4
    AVCodecID AV_CODEC_ID_MPEG1VIDEO
    AVCodecID AV_CODEC_ID_MPEG2VIDEO

    #init and free:
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


#grep AV_PIX_FMT_ /usr/include/xpra/libavutil/pixfmt.h | grep -e "^\s*AV_PIX_FMT"  | sed 's+,+ +g' | sed 's+AV_PIX_FMT_++g' | awk '{print "    AV_PIX_FMT_"$1" : \""$1"\","}'^C
FORMAT_TO_STR = {
    AV_PIX_FMT_NONE : "NONE",
    AV_PIX_FMT_YUV420P : "YUV420P",
    AV_PIX_FMT_YUYV422 : "YUYV422",
    AV_PIX_FMT_RGB24 : "RGB24",
    AV_PIX_FMT_BGR24 : "BGR24",
    AV_PIX_FMT_YUV422P : "YUV422P",
    AV_PIX_FMT_YUV444P : "YUV444P",
    AV_PIX_FMT_YUV410P : "YUV410P",
    AV_PIX_FMT_YUV411P : "YUV411P",
    AV_PIX_FMT_GRAY8 : "GRAY8",
    AV_PIX_FMT_MONOWHITE : "MONOWHITE",
    AV_PIX_FMT_MONOBLACK : "MONOBLACK",
    AV_PIX_FMT_PAL8 : "PAL8",
    AV_PIX_FMT_YUVJ420P : "YUVJ420P",
    AV_PIX_FMT_YUVJ422P : "YUVJ422P",
    AV_PIX_FMT_YUVJ444P : "YUVJ444P",
    AV_PIX_FMT_UYVY422 : "UYVY422",
    AV_PIX_FMT_UYYVYY411 : "UYYVYY411",
    AV_PIX_FMT_BGR8 : "BGR8",
    AV_PIX_FMT_BGR4 : "BGR4",
    AV_PIX_FMT_BGR4_BYTE : "BGR4_BYTE",
    AV_PIX_FMT_RGB8 : "RGB8",
    AV_PIX_FMT_RGB4 : "RGB4",
    AV_PIX_FMT_RGB4_BYTE : "RGB4_BYTE",
    AV_PIX_FMT_NV12 : "NV12",
    AV_PIX_FMT_NV21 : "NV21",
    AV_PIX_FMT_ARGB : "ARGB",
    AV_PIX_FMT_RGBA : "RGBA",
    AV_PIX_FMT_ABGR : "ABGR",
    AV_PIX_FMT_BGRA : "BGRA",
    AV_PIX_FMT_GRAY16BE : "GRAY16BE",
    AV_PIX_FMT_GRAY16LE : "GRAY16LE",
    AV_PIX_FMT_YUV440P : "YUV440P",
    AV_PIX_FMT_YUVJ440P : "YUVJ440P",
    AV_PIX_FMT_YUVA420P : "YUVA420P",
    AV_PIX_FMT_RGB48BE : "RGB48BE",
    AV_PIX_FMT_RGB48LE : "RGB48LE",
    AV_PIX_FMT_RGB565BE : "RGB565BE",
    AV_PIX_FMT_RGB565LE : "RGB565LE",
    AV_PIX_FMT_RGB555BE : "RGB555BE",
    AV_PIX_FMT_RGB555LE : "RGB555LE",
    AV_PIX_FMT_BGR565BE : "BGR565BE",
    AV_PIX_FMT_BGR565LE : "BGR565LE",
    AV_PIX_FMT_BGR555BE : "BGR555BE",
    AV_PIX_FMT_BGR555LE : "BGR555LE",
    AV_PIX_FMT_VAAPI_MOCO : "VAAPI_MOCO",
    AV_PIX_FMT_VAAPI_IDCT : "VAAPI_IDCT",
    AV_PIX_FMT_VAAPI_VLD : "VAAPI_VLD",
    AV_PIX_FMT_VAAPI : "VAAPI",
    AV_PIX_FMT_VAAPI : "VAAPI",
    AV_PIX_FMT_YUV420P16LE : "YUV420P16LE",
    AV_PIX_FMT_YUV420P16BE : "YUV420P16BE",
    AV_PIX_FMT_YUV422P16LE : "YUV422P16LE",
    AV_PIX_FMT_YUV422P16BE : "YUV422P16BE",
    AV_PIX_FMT_YUV444P16LE : "YUV444P16LE",
    AV_PIX_FMT_YUV444P16BE : "YUV444P16BE",
    AV_PIX_FMT_DXVA2_VLD : "DXVA2_VLD",
    AV_PIX_FMT_RGB444LE : "RGB444LE",
    AV_PIX_FMT_RGB444BE : "RGB444BE",
    AV_PIX_FMT_BGR444LE : "BGR444LE",
    AV_PIX_FMT_BGR444BE : "BGR444BE",
    AV_PIX_FMT_YA8 : "YA8",
    AV_PIX_FMT_Y400A : "Y400A",
    AV_PIX_FMT_BGR48BE : "BGR48BE",
    AV_PIX_FMT_BGR48LE : "BGR48LE",
    AV_PIX_FMT_YUV420P9BE : "YUV420P9BE",
    AV_PIX_FMT_YUV420P9LE : "YUV420P9LE",
    AV_PIX_FMT_YUV420P10BE : "YUV420P10BE",
    AV_PIX_FMT_YUV420P10LE : "YUV420P10LE",
    AV_PIX_FMT_YUV422P10BE : "YUV422P10BE",
    AV_PIX_FMT_YUV422P10LE : "YUV422P10LE",
    AV_PIX_FMT_YUV444P9BE : "YUV444P9BE",
    AV_PIX_FMT_YUV444P9LE : "YUV444P9LE",
    AV_PIX_FMT_YUV444P10BE : "YUV444P10BE",
    AV_PIX_FMT_YUV444P10LE : "YUV444P10LE",
    AV_PIX_FMT_YUV422P9BE : "YUV422P9BE",
    AV_PIX_FMT_YUV422P9LE : "YUV422P9LE",
    AV_PIX_FMT_GBRP : "GBRP",
    AV_PIX_FMT_GBR24P : "GBR24P",
    AV_PIX_FMT_GBRP9BE : "GBRP9BE",
    AV_PIX_FMT_GBRP9LE : "GBRP9LE",
    AV_PIX_FMT_GBRP10BE : "GBRP10BE",
    AV_PIX_FMT_GBRP10LE : "GBRP10LE",
    AV_PIX_FMT_GBRP16BE : "GBRP16BE",
    AV_PIX_FMT_GBRP16LE : "GBRP16LE",
    AV_PIX_FMT_YUVA422P : "YUVA422P",
    AV_PIX_FMT_YUVA444P : "YUVA444P",
    AV_PIX_FMT_YUVA420P9BE : "YUVA420P9BE",
    AV_PIX_FMT_YUVA420P9LE : "YUVA420P9LE",
    AV_PIX_FMT_YUVA422P9BE : "YUVA422P9BE",
    AV_PIX_FMT_YUVA422P9LE : "YUVA422P9LE",
    AV_PIX_FMT_YUVA444P9BE : "YUVA444P9BE",
    AV_PIX_FMT_YUVA444P9LE : "YUVA444P9LE",
    AV_PIX_FMT_YUVA420P10BE : "YUVA420P10BE",
    AV_PIX_FMT_YUVA420P10LE : "YUVA420P10LE",
    AV_PIX_FMT_YUVA422P10BE : "YUVA422P10BE",
    AV_PIX_FMT_YUVA422P10LE : "YUVA422P10LE",
    AV_PIX_FMT_YUVA444P10BE : "YUVA444P10BE",
    AV_PIX_FMT_YUVA444P10LE : "YUVA444P10LE",
    AV_PIX_FMT_YUVA420P16BE : "YUVA420P16BE",
    AV_PIX_FMT_YUVA420P16LE : "YUVA420P16LE",
    AV_PIX_FMT_YUVA422P16BE : "YUVA422P16BE",
    AV_PIX_FMT_YUVA422P16LE : "YUVA422P16LE",
    AV_PIX_FMT_YUVA444P16BE : "YUVA444P16BE",
    AV_PIX_FMT_YUVA444P16LE : "YUVA444P16LE",
    AV_PIX_FMT_VDPAU : "VDPAU",
    AV_PIX_FMT_XYZ12LE : "XYZ12LE",
    AV_PIX_FMT_XYZ12BE : "XYZ12BE",
    AV_PIX_FMT_NV16 : "NV16",
    AV_PIX_FMT_NV20LE : "NV20LE",
    AV_PIX_FMT_NV20BE : "NV20BE",
    AV_PIX_FMT_RGBA64BE : "RGBA64BE",
    AV_PIX_FMT_RGBA64LE : "RGBA64LE",
    AV_PIX_FMT_BGRA64BE : "BGRA64BE",
    AV_PIX_FMT_BGRA64LE : "BGRA64LE",
    AV_PIX_FMT_YVYU422 : "YVYU422",
    AV_PIX_FMT_YA16BE : "YA16BE",
    AV_PIX_FMT_YA16LE : "YA16LE",
    AV_PIX_FMT_GBRAP : "GBRAP",
    AV_PIX_FMT_GBRAP16BE : "GBRAP16BE",
    AV_PIX_FMT_GBRAP16LE : "GBRAP16LE",
    AV_PIX_FMT_QSV : "QSV",
    AV_PIX_FMT_MMAL : "MMAL",
    AV_PIX_FMT_D3D11VA_VLD : "D3D11VA_VLD",
    AV_PIX_FMT_CUDA : "CUDA",
    AV_PIX_FMT_0RGB : "0RGB",
    AV_PIX_FMT_RGB0 : "RGB0",
    AV_PIX_FMT_0BGR : "0BGR",
    AV_PIX_FMT_BGR0 : "BGR0",
    AV_PIX_FMT_YUV420P12BE : "YUV420P12BE",
    AV_PIX_FMT_YUV420P12LE : "YUV420P12LE",
    AV_PIX_FMT_YUV420P14BE : "YUV420P14BE",
    AV_PIX_FMT_YUV420P14LE : "YUV420P14LE",
    AV_PIX_FMT_YUV422P12BE : "YUV422P12BE",
    AV_PIX_FMT_YUV422P12LE : "YUV422P12LE",
    AV_PIX_FMT_YUV422P14BE : "YUV422P14BE",
    AV_PIX_FMT_YUV422P14LE : "YUV422P14LE",
    AV_PIX_FMT_YUV444P12BE : "YUV444P12BE",
    AV_PIX_FMT_YUV444P12LE : "YUV444P12LE",
    AV_PIX_FMT_YUV444P14BE : "YUV444P14BE",
    AV_PIX_FMT_YUV444P14LE : "YUV444P14LE",
    AV_PIX_FMT_GBRP12BE : "GBRP12BE",
    AV_PIX_FMT_GBRP12LE : "GBRP12LE",
    AV_PIX_FMT_GBRP14BE : "GBRP14BE",
    AV_PIX_FMT_GBRP14LE : "GBRP14LE",
    AV_PIX_FMT_YUVJ411P : "YUVJ411P",
    AV_PIX_FMT_BAYER_BGGR8 : "BAYER_BGGR8",
    AV_PIX_FMT_BAYER_RGGB8 : "BAYER_RGGB8",
    AV_PIX_FMT_BAYER_GBRG8 : "BAYER_GBRG8",
    AV_PIX_FMT_BAYER_GRBG8 : "BAYER_GRBG8",
    AV_PIX_FMT_BAYER_BGGR16LE : "BAYER_BGGR16LE",
    AV_PIX_FMT_BAYER_BGGR16BE : "BAYER_BGGR16BE",
    AV_PIX_FMT_BAYER_RGGB16LE : "BAYER_RGGB16LE",
    AV_PIX_FMT_BAYER_RGGB16BE : "BAYER_RGGB16BE",
    AV_PIX_FMT_BAYER_GBRG16LE : "BAYER_GBRG16LE",
    AV_PIX_FMT_BAYER_GBRG16BE : "BAYER_GBRG16BE",
    AV_PIX_FMT_BAYER_GRBG16LE : "BAYER_GRBG16LE",
    AV_PIX_FMT_BAYER_GRBG16BE : "BAYER_GRBG16BE",
    AV_PIX_FMT_XVMC : "XVMC",
    AV_PIX_FMT_YUV440P10LE : "YUV440P10LE",
    AV_PIX_FMT_YUV440P10BE : "YUV440P10BE",
    AV_PIX_FMT_YUV440P12LE : "YUV440P12LE",
    AV_PIX_FMT_YUV440P12BE : "YUV440P12BE",
    AV_PIX_FMT_AYUV64LE : "AYUV64LE",
    AV_PIX_FMT_AYUV64BE : "AYUV64BE",
    AV_PIX_FMT_VIDEOTOOLBOX : "VIDEOTOOLBOX",
    AV_PIX_FMT_P010LE : "P010LE",
    AV_PIX_FMT_P010BE : "P010BE",
    AV_PIX_FMT_GBRAP12BE : "GBRAP12BE",
    AV_PIX_FMT_GBRAP12LE : "GBRAP12LE",
    AV_PIX_FMT_GBRAP10BE : "GBRAP10BE",
    AV_PIX_FMT_GBRAP10LE : "GBRAP10LE",
    AV_PIX_FMT_MEDIACODEC : "MEDIACODEC",
    AV_PIX_FMT_GRAY12BE : "GRAY12BE",
    AV_PIX_FMT_GRAY12LE : "GRAY12LE",
    AV_PIX_FMT_GRAY10BE : "GRAY10BE",
    AV_PIX_FMT_GRAY10LE : "GRAY10LE",
    AV_PIX_FMT_P016LE : "P016LE",
    AV_PIX_FMT_P016BE : "P016BE",
    AV_PIX_FMT_D3D11 : "D3D11",
    AV_PIX_FMT_GRAY9BE : "GRAY9BE",
    AV_PIX_FMT_GRAY9LE : "GRAY9LE",
    AV_PIX_FMT_GBRPF32BE : "GBRPF32BE",
    AV_PIX_FMT_GBRPF32LE : "GBRPF32LE",
    AV_PIX_FMT_GBRAPF32BE : "GBRAPF32BE",
    AV_PIX_FMT_GBRAPF32LE : "GBRAPF32LE",
    AV_PIX_FMT_DRM_PRIME : "DRM_PRIME",
    #AV_PIX_FMT_OPENCL : "OPENCL",
    #AV_PIX_FMT_GRAY14BE : "GRAY14BE",
    #AV_PIX_FMT_GRAY14LE : "GRAY14LE",
    #AV_PIX_FMT_GRAYF32BE : "GRAYF32BE",
    #AV_PIX_FMT_GRAYF32LE : "GRAYF32LE",
    #AV_PIX_FMT_YUVA422P12BE : "YUVA422P12BE",
    #AV_PIX_FMT_YUVA422P12LE : "YUVA422P12LE",
    #AV_PIX_FMT_YUVA444P12BE : "YUVA444P12BE",
    #AV_PIX_FMT_YUVA444P12LE : "YUVA444P12LE",
    #AV_PIX_FMT_NV24 : "NV24",
    #AV_PIX_FMT_NV42 : "NV42",
    #AV_PIX_FMT_VULKAN : "VULKAN",
    #AV_PIX_FMT_Y210BE : "Y210BE",
    #AV_PIX_FMT_Y210LE : "Y210LE",
    #AV_PIX_FMT_NB : "NB",
    }

#given one of our format names,
#describing the pixel data fed to the encoder,
#what ffmpeg AV_PIX_FMT we expect to find in the output:
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
            "GBRP9LE"   : AV_PIX_FMT_GBRP9LE,
            "GBRP10"    : AV_PIX_FMT_GBRP10LE,
            "YUV444P10" : AV_PIX_FMT_YUV444P10LE,
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
    AV_PIX_FMT_GBRP10LE : 6,
    AV_PIX_FMT_YUV444P10LE  : 2,
    }

#given an ffmpeg pixel format,
#what is our format name for it:
COLORSPACES = list(FORMAT_TO_ENUM.keys())+["r210", "YUV444P10"]
ENUM_TO_FORMAT = {}
for pix_fmt, av_enum in FORMAT_TO_ENUM.items():
    ENUM_TO_FORMAT[av_enum] = pix_fmt
FORMAT_TO_ENUM["r210"] = AV_PIX_FMT_GBRP10LE


def get_version():
    return (LIBAVCODEC_VERSION_MAJOR, LIBAVCODEC_VERSION_MINOR, LIBAVCODEC_VERSION_MICRO)

v = get_version()
if v<(3,):
    raise ImportError("ffmpeg version %s is too old" % v)

register_all()
CODECS = []
if avcodec_find_decoder(AV_CODEC_ID_H264)!=NULL:
    CODECS.append("h264")
if avcodec_find_decoder(AV_CODEC_ID_VP8)!=NULL:
    CODECS.append("vp8")
if avcodec_find_decoder(AV_CODEC_ID_H265)!=NULL:
    CODECS.append("h265")
if avcodec_find_decoder(AV_CODEC_ID_MPEG4)!=NULL:
    CODECS.append("mpeg4")
if avcodec_find_decoder(AV_CODEC_ID_MPEG1VIDEO)!=NULL:
    CODECS.append("mpeg1")
if avcodec_find_decoder(AV_CODEC_ID_MPEG2VIDEO)!=NULL:
    CODECS.append("mpeg2")
if avcodec_find_decoder(AV_CODEC_ID_VP9)!=NULL:
    CODECS.append("vp9")
CODECS = tuple(CODECS)
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
    return  {
        "version"      : get_version(),
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
    elif encoding in ("vp8", "mpeg4", "mpeg1", "mpeg2"):
        return ("YUV420P",)
    assert encoding=="vp9"
    return ("YUV420P", "YUV444P", "YUV444P10")

def get_output_colorspace(encoding, csc):
    if encoding not in CODECS:
        return ""
    if encoding=="h264":
        if csc in ("RGB", "XRGB", "BGRX", "ARGB", "BGRA"):
            #h264 from plain RGB data is returned as "GBRP"!
            return "GBRP"
        if csc=="GBRP10":
            return "GBRP10"
        if csc=="YUV444P10":
            return "YUV444P10"
    elif encoding in ("vp8", "mpeg4", "mpeg1", "mpeg2"):
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
            av_frame_free(&self.frame)
            self.frame = NULL   #should be redundant
            self.avctx = NULL


class AVImageWrapper(ImageWrapper):
    """
        Wrapper which allows us to call xpra_free on the decoder
        when the image is freed, or once we have made a copy of the pixels.
    """

    def _cn(self):
        return "AVImageWrapper-%s" % self.av_frame

    def free(self):
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
        assert encoding in CODECS
        self.encoding = encoding
        self.width = width
        self.height = height
        assert colorspace in COLORSPACES, "invalid colorspace: %s" % colorspace
        self.colorspace = str(colorspace)
        self.pix_fmt = FORMAT_TO_ENUM.get(colorspace, AV_PIX_FMT_NONE)
        if self.pix_fmt==AV_PIX_FMT_NONE:
            log.error("invalid pixel format: %s", colorspace)
            return  False
        self.actual_pix_fmt = self.pix_fmt

        register_all()

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
        elif self.encoding=="mpeg1":
            CodecID = AV_CODEC_ID_MPEG1VIDEO
        elif self.encoding=="mpeg2":
            CodecID = AV_CODEC_ID_MPEG2VIDEO
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

        #self.codec_ctx.refcounted_frames = 1
        self.codec_ctx.width = width
        self.codec_ctx.height = height
        self.codec_ctx.pix_fmt = self.pix_fmt
        #self.codec_ctx.get_buffer2 = avcodec_get_buffer2
        #self.codec_ctx.release_buffer = avcodec_release_buffer
        self.codec_ctx.thread_safe_callbacks = 1
        self.codec_ctx.thread_type = 2      #FF_THREAD_SLICE: allow more than one thread per frame
        self.codec_ctx.thread_count = 0     #auto
        self.codec_ctx.flags2 |= AV_CODEC_FLAG2_FAST    #may cause "no deblock across slices" - which should be fine
        cdef int r = avcodec_open2(self.codec_ctx, self.codec, NULL)
        if r<0:
            log.error("could not open codec: %s", av_error_str(r))
            self.clean_decoder()
            return  False
        self.frames = 0
        #to keep track of images not freed yet:
        self.weakref_images = weakref.WeakSet()
        #register this decoder in the global dictionary:
        log("dec_avcodec.Decoder.init_context(%s, %s, %s) self=%s", width, height, colorspace, self.get_info())
        return True

    def clean(self):
        self.clean_decoder()
        self.codec = NULL
        self.pix_fmt = 0
        self.actual_pix_fmt = 0
        self.colorspace = ""
        self.weakref_images = weakref.WeakSet()
        self.frames = 0
        self.width = 0
        self.height = 0
        self.encoding = ""


    def clean_decoder(self):
        cdef int r
        log("%s.clean_decoder()", self)
        #we may have images handed out, ensure we don't reference any memory
        #that needs to be freed using avcodec_release_buffer(..)
        #as this requires the context to still be valid!
        #copying the pixels should ensure we free the AVFrameWrapper associated with it:
        if self.weakref_images:
            images = tuple(self.weakref_images)
            self.weakref_images = weakref.WeakSet()
            log("clean_decoder() cloning pixels for images still in use: %s", images)
            for img in images:
                if not img.freed:
                    img.clone_pixel_data()
        log("clean_decoder() freeing AVCodecContext: %#x", <uintptr_t> self.codec_ctx)
        if self.codec_ctx!=NULL:
            r = avcodec_close(self.codec_ctx)
            if r!=0:
                log.error("Error: failed to close decoder context %#x:", <uintptr_t> self.codec_ctx)
                log.error(" %s", av_error_str(r))
            av_free(self.codec_ctx)
            self.codec_ctx = NULL
        log("clean_decoder() done")

    def __repr__(self):
        if self.is_closed():
            return "dec_avcodec.Decoder(*closed*)"
        return "dec_avcodec.Decoder(%s)" % self.get_info()

    def get_info(self) -> dict:
        info = {
            "version"   : get_version(),
            "encoding"  : self.encoding,
            "formats"   : get_input_colorspaces(self.encoding),
            "type"      : self.get_type(),
            "frames"    : int(self.frames),
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

    def __dealloc__(self):
        self.clean()

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_encoding(self):
        return self.encoding

    def get_type(self):
        return "avcodec"

    def log_av_error(self, int buf_len, err_no, options=None):
        msg = av_error_str(err_no)
        self.log_error(buf_len, msg, options, "error %i" % err_no)

    def log_error(self, int buf_len, err, options=None, error_type="error"):
        log.error("Error: avcodec %s decoding %i bytes of %s data:", error_type, buf_len, self.encoding)
        log.error(" '%s'", err)
        log.error(" frame %i", self.frames)
        def pv(v):
            if isinstance(v, (list, tuple)):
                return csv(v)
            return bytestostr(v)
        if options:
            log.error(" frame options:")
            for k,v in options.items():
                log.error("   %20s = %s", bytestostr(k), pv(v))
        log.error(" decoder state:")
        for k,v in self.get_info().items():
            log.error("   %20s = %s", k, pv(v))

    def decompress_image(self, input, options=None):
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef int size
        cdef int nplanes
        cdef AVPacket avpkt
        assert self.codec_ctx!=NULL, "no codec context! (not initialized or already closed)"
        assert self.codec!=NULL

        cdef AVFrame *av_frame = av_frame_alloc()
        log("av_frame_alloc()=%#x", <uintptr_t> av_frame)
        if av_frame==NULL:
            log.error("could not allocate an AVFrame for decoding")
            self.clean_decoder()
            return None

        #copy the whole input buffer into a padded C buffer:
        assert object_as_buffer(input, <const void**> &buf, &buf_len)==0
        cdef unsigned char * padded_buf = <unsigned char *> memalign(buf_len+128)
        assert padded_buf!=NULL, "failed to allocate %i bytes of memory" % (buf_len+128)
        memcpy(padded_buf, buf, buf_len)
        memset(padded_buf+buf_len, 0, 128)

        #note: plain RGB output, will redefine those:
        out = []
        strides = []
        outsize = 0

        #ensure we can detect if the frame buffer got allocated:
        clear_frame(av_frame)
        #now safe to run without gil:
        cdef int ret = 0
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
            ret = avcodec_receive_frame(self.codec_ctx, av_frame)
        free(padded_buf)
        if ret==-errno.EAGAIN:
            if options:
                d = options.intget("delayed", 0)
                if d>0:
                    log("avcodec_receive_frame %i delayed pictures", d)
                    return None
            self.log_error(buf_len, "no picture", options)
            return None
        if ret!=0:
            av_frame_unref(av_frame)
            av_frame_free(&av_frame)
            log("%s.decompress_image(%s:%s, %s) avcodec_decode_video2 failure: %s", self, type(input), buf_len, options, av_error_str(ret))
            self.log_av_error(buf_len, ret, options)
            return None

        log("avcodec_decode_video2 returned %i", ret)
        if self.actual_pix_fmt!=av_frame.format:
            if av_frame.format==-1:
                self.log_error(buf_len, "unknown format returned")
                return None
            self.actual_pix_fmt = av_frame.format
            if self.actual_pix_fmt not in ENUM_TO_FORMAT:
                av_frame_unref(av_frame)
                av_frame_free(&av_frame)
                log.error("unknown output pixel format: %s, expected %s for '%s'",
                          FORMAT_TO_STR.get(self.actual_pix_fmt, self.actual_pix_fmt),
                          FORMAT_TO_STR.get(self.pix_fmt, self.pix_fmt),
                          self.colorspace)
                return None
            log("avcodec actual output pixel format is %s (%s), expected %s (%s)", self.actual_pix_fmt, self.get_actual_colorspace(), self.pix_fmt, self.colorspace)

        cs = self.get_actual_colorspace()
        log("actual_colorspace(%s)=%s, frame size: %4ix%-4i",
                 self.actual_pix_fmt, cs, av_frame.width, av_frame.height)
        if cs.find("P")>0:  #ie: GBRP, YUV420P, GBRP10 etc
            divs = get_subsampling_divs(cs)
            nplanes = 3
            for i in range(3):
                _, dy = divs[i]
                if dy==1:
                    height = self.codec_ctx.height
                elif dy==2:
                    height = (self.codec_ctx.height+1)>>1
                else:
                    av_frame_unref(av_frame)
                    av_frame_free(&av_frame)
                    raise Exception("invalid height divisor %s" % dy)
                stride = av_frame.linesize[i]
                size = height * stride
                outsize += size

                out.append(memory_as_pybuffer(<void *>av_frame.data[i], size, True))
                strides.append(stride)
                log("decompress_image() read back '%s' plane: %s bytes", cs[i:i+1], size)
        else:
            #RGB mode: "out" is a single buffer
            strides = av_frame.linesize[0]+av_frame.linesize[1]+av_frame.linesize[2]
            outsize = self.codec_ctx.height * strides
            out = memory_as_pybuffer(<void *>av_frame.data[0], outsize, True)
            nplanes = 0
            log("decompress_image() read back '%s' buffer: %s bytes", cs, outsize)

        if outsize==0:
            av_frame_unref(av_frame)
            av_frame_free(&av_frame)
            raise Exception("output size is zero!")
        if self.codec_ctx.width<self.width or self.codec_ctx.height<self.height:
            raise Exception("%s context dimension %ix%i is smaller than the codec's expected size of %ix%i for frame %i" % (self.encoding, self.codec_ctx.width, self.codec_ctx.height, self.width, self.height, self.frames+1))

        bpp = BYTES_PER_PIXEL.get(self.actual_pix_fmt, 0)
        cdef AVFrameWrapper framewrapper = AVFrameWrapper()
        framewrapper.set_context(self.codec_ctx, av_frame)
        cdef object img = AVImageWrapper(0, 0, self.width, self.height, out, cs, 24, strides, bpp, nplanes, thread_safe=False)
        img.av_frame = framewrapper
        self.frames += 1
        self.weakref_images.add(img)
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
    try:
        suspend_nonfatal_logging()
        CODECS = testdecoder(decoder, full)
    finally:
        resume_nonfatal_logging()
