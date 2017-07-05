# This file is part of Xpra.
# Copyright (C) 2012-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False

import os, sys
from xpra.codecs.codec_constants import get_subsampling_divs
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.os_util import bytestostr
from xpra.util import envint

from xpra.log import Logger
log = Logger("decoder", "vpx")

#sensible default:
cpus = 2
try:
    cpus = os.cpu_count()
except:
    try:
        import multiprocessing
        cpus = multiprocessing.cpu_count()
    except:
        pass
cdef int VPX_THREADS = envint("XPRA_VPX_THREADS", max(1, cpus-1))

cdef inline int roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)

include "constants.pxi"

from libc.stdint cimport int64_t

cdef extern from "string.h":
    void *memcpy(void * destination, void * source, size_t num) nogil
    void *memset(void * ptr, int value, size_t num) nogil
    void free(void * ptr) nogil

ctypedef unsigned char uint8_t
ctypedef long vpx_img_fmt_t
ctypedef void vpx_codec_iface_t


cdef extern from "../../buffers/memalign.h":
    void *xmemalign(size_t size)

cdef extern from "../../buffers/buffers.h":
    object memory_as_pybuffer(void* ptr, Py_ssize_t buf_len, int readonly)
    int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)
    int get_buffer_api_version()

cdef extern from "vpx/vpx_codec.h":
    ctypedef const void *vpx_codec_iter_t
    ctypedef long vpx_codec_flags_t
    ctypedef int vpx_codec_err_t
    ctypedef struct vpx_codec_ctx_t:
        pass
    const char *vpx_codec_error(vpx_codec_ctx_t  *ctx)
    vpx_codec_err_t vpx_codec_destroy(vpx_codec_ctx_t *ctx)
    const char *vpx_codec_version_str()
    const char *vpx_codec_build_config()

cdef extern from "vpx/vpx_image.h":
    cdef int VPX_IMG_FMT_I420
    ctypedef struct vpx_image_t:
        unsigned int w
        unsigned int h
        unsigned int d_w
        unsigned int d_h
        vpx_img_fmt_t fmt
        unsigned char *planes[4]
        int stride[4]
        int bps
        unsigned int x_chroma_shift
        unsigned int y_chroma_shift

cdef extern from "vpx/vp8dx.h":
    IF ENABLE_VP8:
        const vpx_codec_iface_t *vpx_codec_vp8_dx()
    IF ENABLE_VP9:
        const vpx_codec_iface_t *vpx_codec_vp9_dx()

cdef extern from "vpx/vpx_decoder.h":
    ctypedef struct vpx_codec_enc_cfg_t:
        unsigned int rc_target_bitrate
        unsigned int g_lag_in_frames
        unsigned int rc_dropframe_thresh
        unsigned int rc_resize_allowed
        unsigned int g_w
        unsigned int g_h
        unsigned int g_error_resilient
    ctypedef struct vpx_codec_dec_cfg_t:
        unsigned int threads
        unsigned int w
        unsigned int h
    cdef int VPX_CODEC_OK
    cdef int VPX_DECODER_ABI_VERSION

    vpx_codec_err_t vpx_codec_dec_init_ver(vpx_codec_ctx_t *ctx, vpx_codec_iface_t *iface,
                                            vpx_codec_dec_cfg_t *cfg, vpx_codec_flags_t flags, int ver)

    vpx_codec_err_t vpx_codec_decode(vpx_codec_ctx_t *ctx, const uint8_t *data,
                                     unsigned int data_sz, void *user_priv, long deadline) nogil

    vpx_image_t *vpx_codec_get_frame(vpx_codec_ctx_t *ctx, vpx_codec_iter_t *iter) nogil


#https://groups.google.com/a/webmproject.org/forum/?fromgroups#!msg/webm-discuss/f5Rmi-Cu63k/IXIzwVoXt_wJ
#"RGB is not supported.  You need to convert your source to YUV, and then compress that."
COLORSPACES = {}
CODECS = []
IF ENABLE_VP8:
    CODECS.append("vp8")
    COLORSPACES["vp8"] = ["YUV420P"]
IF ENABLE_VP9:
    CODECS.append("vp9")
    vp9_cs = ["YUV420P"]
    #this is the ABI version with libvpx 1.4.0:
    if VPX_DECODER_ABI_VERSION>=9:
        vp9_cs.append("YUV444P")
    else:
        if sys.platform.startswith("darwin"):
            pass        #cannot build libvpx 1.4 on osx... so skip warning
        else:
            log.warn("Warning: libvpx ABI version %s is too old:", VPX_DECODER_ABI_VERSION)
            log.warn(" disabling YUV444P support with VP9")
    COLORSPACES["vp9"] = vp9_cs


def init_module():
    log("vpx.decoder.init_module() info=%s", get_info())
    log("supported codecs: %s", CODECS)
    log("supported colorspaces: %s", COLORSPACES)

def cleanup_module():
    log("vpx.decoder.cleanup_module()")

def get_abi_version():
    return VPX_DECODER_ABI_VERSION

def get_version():
    v = vpx_codec_version_str()
    return v.decode("latin1")

def get_type():
    return "vpx"

def get_encodings():
    return CODECS

def get_input_colorspaces(encoding):
    assert encoding in CODECS
    return COLORSPACES.get(encoding)

def get_output_colorspace(encoding, csc):
    #same as input
    assert encoding in CODECS
    colorspaces = COLORSPACES.get(encoding)
    assert csc in colorspaces, "invalid colorspace '%s' for encoding '%s' (must be one of %s)" % (csc, encoding, colorspaces)
    return csc


def get_info():
    global CODECS
    info = {"version"       : get_version(),
            "encodings"     : CODECS,
            "buffer_api"    : get_buffer_api_version(),
            "abi_version"   : get_abi_version(),
            "build_config"  : vpx_codec_build_config()}
    for k,v in COLORSPACES.items():
        info["%s.colorspaces" % k] = v
    return info


cdef const vpx_codec_iface_t  *make_codec_dx(encoding):
    IF ENABLE_VP8:
        if encoding=="vp8":
            return vpx_codec_vp8_dx()
    IF ENABLE_VP9:
        if encoding=="vp9":
            return vpx_codec_vp9_dx()
    raise Exception("unsupported encoding: %s" % encoding)

cdef vpx_img_fmt_t get_vpx_colorspace(colorspace):
    return VPX_IMG_FMT_I420


class VPXImageWrapper(ImageWrapper):

    def __init__(self, *args, **kwargs):
        ImageWrapper.__init__(self, *args, **kwargs)
        self.buffers = []

    def _cn(self):                          #@DuplicatedSignature
        return "VPXImageWrapper"

    def add_buffer(self, ptr):
        self.buffers.append(ptr)

    def clone_pixel_data(self):
        ImageWrapper.clone_pixel_data(self)
        self.free_buffers()

    def free(self):
        ImageWrapper.free(self)
        self.free_buffers()

    def free_buffers(self):
        cdef void *ptr
        if self.buffers:
            for x in self.buffers:
                #cython magic:
                ptr = <void *> (<unsigned long> x)
                free(ptr)
            self.buffers = []


cdef class Decoder:

    cdef vpx_codec_ctx_t *context
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned int max_threads
    cdef vpx_img_fmt_t pixfmt
    cdef object dst_format
    cdef object encoding

    cdef object __weakref__

    def init_context(self, encoding, width, height, colorspace):
        assert encoding in CODECS
        assert colorspace in get_input_colorspaces(encoding)
        cdef int flags = 0
        cdef const vpx_codec_iface_t *codec_iface = make_codec_dx(encoding)
        self.encoding = encoding
        self.dst_format = bytestostr(colorspace)
        self.pixfmt = get_vpx_colorspace(self.dst_format)
        self.width = width
        self.height = height
        try:
            #no point having too many threads if the height is small, also avoids a warning:
            self.max_threads = max(0, min(int(VPX_THREADS), roundup(height, 32)//32*2))
        except:
            self.max_threads = 1
        self.context = <vpx_codec_ctx_t *> xmemalign(sizeof(vpx_codec_ctx_t))
        assert self.context!=NULL
        memset(self.context, 0, sizeof(vpx_codec_ctx_t))
        cdef vpx_codec_dec_cfg_t dec_cfg
        dec_cfg.w = width
        dec_cfg.h = height
        dec_cfg.threads = self.max_threads
        if vpx_codec_dec_init_ver(self.context, codec_iface, &dec_cfg,
                              flags, VPX_DECODER_ABI_VERSION)!=VPX_CODEC_OK:
            raise Exception("failed to instantiate %s decoder with ABI version %s: %s" % (encoding, VPX_DECODER_ABI_VERSION, bytestostr(vpx_codec_error(self.context))))
        log("vpx_codec_dec_init_ver for %s succeeded with ABI version %s", encoding, VPX_DECODER_ABI_VERSION)

    def __repr__(self):
        return "vpx.Decoder(%s)" % self.encoding

    def get_info(self):                 #@DuplicatedSignature
        return {"type"      : self.get_type(),
                "width"     : self.get_width(),
                "height"    : self.get_height(),
                "encoding"  : self.encoding,
                "colorspace": self.get_colorspace(),
                "max_threads" : self.max_threads,
                }

    def get_colorspace(self):
        return self.dst_format

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def is_closed(self):
        return self.context==NULL

    def get_encoding(self):
        return self.encoding

    def get_type(self):                 #@DuplicatedSignature
        return  "vpx"

    def __dealloc__(self):
        self.clean()

    def clean(self):
        if self.context!=NULL:
            vpx_codec_destroy(self.context)
            self.context = NULL
        self.width = 0
        self.height = 0
        self.max_threads = 0
        self.pixfmt = 0
        self.dst_format = ""
        self.encoding = ""


    def decompress_image(self, input, options):
        cdef vpx_image_t *img
        cdef vpx_codec_iter_t iter = NULL
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef vpx_codec_err_t ret
        cdef int i = 0
        cdef object image
        cdef void *padded_buf
        cdef Py_ssize_t plane_len = 0
        cdef uint8_t dx, dy
        cdef unsigned int height
        cdef int stride
        assert self.context!=NULL

        assert object_as_buffer(input, <const void**> &buf, &buf_len)==0

        with nogil:
            ret = vpx_codec_decode(self.context, buf, buf_len, NULL, 0)
        if ret!=VPX_CODEC_OK:
            log.warn("error during vpx_codec_decode: %s", bytestostr(vpx_codec_error(self.context)))
            return None
        with nogil:
            img = vpx_codec_get_frame(self.context, &iter)
        if img==NULL:
            log.warn("error during vpx_codec_get_frame: %s", bytestostr(vpx_codec_error(self.context)))
            return None
        strides = []
        pixels = []
        divs = get_subsampling_divs(self.get_colorspace())
        image = VPXImageWrapper(0, 0, self.width, self.height, pixels, self.get_colorspace(), 24, strides, 3)
        for i in range(3):
            _, dy = divs[i]
            if dy==1:
                height = self.height
            elif dy==2:
                height = (self.height+1)>>1
            else:
                raise Exception("invalid height divisor %s" % dy)
            stride = img.stride[i]
            strides.append(stride)

            plane_len = height * stride
            #add one extra line of padding:
            padded_buf = xmemalign(plane_len + stride)
            memcpy(padded_buf, <void *>img.planes[i], plane_len)
            memset(<void *>((<char *>padded_buf)+plane_len), 0, stride)

            pixels.append(memory_as_pybuffer(padded_buf, plane_len, True))

            image.add_buffer(<unsigned long> padded_buf)
        log("vpx returning decoded %s image %s with colorspace=%s", self.encoding, image, image.get_pixel_format())
        return image


def selftest(full=False):
    global CODECS
    from xpra.codecs.codec_checks import testdecoder
    from xpra.codecs.vpx import decoder
    CODECS = testdecoder(decoder, full)
