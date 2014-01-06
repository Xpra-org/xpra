# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.codecs.codec_constants import codec_spec, get_subsampling_divs
from xpra.codecs.image_wrapper import ImageWrapper

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_VPX_DEBUG")
error = log.error

VPX_THREADS = os.environ.get("XPRA_VPX_THREADS", "2")

DEF ENABLE_VP8 = True
DEF ENABLE_VP9 = False


from libc.stdint cimport int64_t


cdef extern from "string.h":
    void * memcpy(void * destination, void * source, size_t num) nogil
    void * memset(void * ptr, int value, size_t num) nogil
    void free(void * ptr) nogil

cdef extern from "../memalign/memalign.h":
    void *xmemalign(size_t size)

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef object PyObject
    int PyObject_AsReadBuffer(object obj, void ** buffer, Py_ssize_t * buffer_len) except -1
    object PyBuffer_FromMemory(void *ptr, Py_ssize_t size)

ctypedef unsigned char uint8_t
ctypedef long vpx_img_fmt_t
ctypedef void vpx_codec_iface_t

cdef extern from "vpx/vpx_codec.h":
    ctypedef const void *vpx_codec_iter_t
    ctypedef long vpx_codec_flags_t
    ctypedef int vpx_codec_err_t
    ctypedef struct vpx_codec_ctx_t:
        pass
    const char *vpx_codec_error(vpx_codec_ctx_t  *ctx)
    vpx_codec_err_t vpx_codec_destroy(vpx_codec_ctx_t *ctx)
    const char *vpx_codec_version_str()

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
    IF ENABLE_VP8 == True:
        const vpx_codec_iface_t *vpx_codec_vp8_dx()
    IF ENABLE_VP9 == True:
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


def get_version():
    return vpx_codec_version_str()

def get_type(self):
    return  "vpx"


CODECS = []
IF ENABLE_VP8 == True:
    CODECS.append("vp8")
IF ENABLE_VP9 == True:
    CODECS.append("vp9")

cdef const vpx_codec_iface_t  *make_codec_dx(encoding):
    IF ENABLE_VP8 == True:
        if encoding=="vp8":
            return vpx_codec_vp8_dx()
    IF ENABLE_VP9 == True:
        if encoding=="vp9":
            return vpx_codec_vp9_dx()
    raise Exception("unsupported encoding: %s" % encoding)

def get_encodings():
    return CODECS

#https://groups.google.com/a/webmproject.org/forum/?fromgroups#!msg/webm-discuss/f5Rmi-Cu63k/IXIzwVoXt_wJ
#"RGB is not supported.  You need to convert your source to YUV, and then compress that."
COLORSPACES = ["YUV420P"]
def get_colorspaces():
    return COLORSPACES

def get_spec(colorspace):
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES)
    #quality: we only handle YUV420P but this is already accounted for by get_colorspaces() based score calculations
    #setup cost is reasonable (usually about 5ms)
    return codec_spec(Decoder, codec_type="vpx", setup_cost=40)

cdef vpx_img_fmt_t get_vpx_colorspace(colorspace):
    assert colorspace in COLORSPACES
    return VPX_IMG_FMT_I420


class VPXImageWrapper(ImageWrapper):

    def __init__(self, *args, **kwargs):
        ImageWrapper.__init__(self, *args, **kwargs)
        self.buffers = []

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
    cdef int width
    cdef int height
    cdef int max_threads
    cdef vpx_img_fmt_t pixfmt
    cdef char* dst_format
    cdef object encoding

    def init_context(self, encoding, width, height, colorspace):
        assert encoding in CODECS
        assert colorspace=="YUV420P"
        cdef int flags = 0
        cdef const vpx_codec_iface_t *codec_iface = make_codec_dx(encoding)
        self.encoding = encoding
        self.dst_format = "YUV420P"
        self.pixfmt = get_vpx_colorspace(self.dst_format)
        self.width = width
        self.height = height
        try:
            self.max_threads = int(VPX_THREADS)
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
            raise Exception("failed to instantiate vpx decoder: %s" % vpx_codec_error(self.context))
        debug("vpx_codec_dec_init_ver for %s succeeded", encoding)

    def __str__(self):
        return "vpx.Decoder(%s)" % self.encoding

    def get_info(self):
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

    def decompress_image(self, input, options):
        cdef vpx_image_t *img
        cdef vpx_codec_iter_t iter = NULL
        cdef const uint8_t *frame = input
        cdef const unsigned char * buf = NULL
        cdef Py_ssize_t buf_len = 0
        cdef vpx_codec_err_t ret
        cdef int i = 0
        cdef object image
        cdef object plane
        cdef void *padded_buf
        cdef Py_ssize_t plane_len = 0
        assert self.context!=NULL
        assert PyObject_AsReadBuffer(input, <const void**> &buf, &buf_len)==0

        with nogil:
            ret = vpx_codec_decode(self.context, buf, buf_len, NULL, 0)
        if ret!=VPX_CODEC_OK:
            log.warn("error during vpx_codec_decode: %s" % vpx_codec_error(self.context))
            return None
        with nogil:
            img = vpx_codec_get_frame(self.context, &iter)
        if img==NULL:
            log.warn("error during vpx_codec_get_frame: %s" % vpx_codec_error(self.context))
            return None
        strides = []
        pixels = []
        divs = get_subsampling_divs(self.get_colorspace())
        image = VPXImageWrapper(0, 0, self.width, self.height, pixels, self.get_colorspace(), 24, strides, 3)
        for i in (0, 1, 2):
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

            plane = PyBuffer_FromMemory(padded_buf, plane_len)
            pixels.append(plane)

            image.add_buffer(<unsigned long> padded_buf)
        debug("vpx returning decoded %s image %s with colorspace=%s", self.encoding, image, image.get_pixel_format())
        return image
