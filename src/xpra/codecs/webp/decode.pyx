# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("encoder", "webp")

from xpra.buffers.membuf cimport memalign, memory_as_pybuffer
from xpra.os_util import bytestostr


from libc.stdint cimport uint8_t, uint32_t

cdef extern from *:
    ctypedef unsigned long size_t

cdef extern from "stdlib.h":
    void free(void *ptr)


cdef extern from "webp/decode.h":

    int WebPGetDecoderVersion()

    ctypedef int VP8StatusCode
    VP8StatusCode VP8_STATUS_OK
    VP8StatusCode VP8_STATUS_OUT_OF_MEMORY
    VP8StatusCode VP8_STATUS_INVALID_PARAM
    VP8StatusCode VP8_STATUS_BITSTREAM_ERROR
    VP8StatusCode VP8_STATUS_UNSUPPORTED_FEATURE
    VP8StatusCode VP8_STATUS_SUSPENDED
    VP8StatusCode VP8_STATUS_USER_ABORT
    VP8StatusCode VP8_STATUS_NOT_ENOUGH_DATA

    ctypedef int WEBP_CSP_MODE
    WEBP_CSP_MODE MODE_RGB
    WEBP_CSP_MODE MODE_RGBA
    WEBP_CSP_MODE MODE_BGR
    WEBP_CSP_MODE MODE_BGRA
    WEBP_CSP_MODE MODE_ARGB
    WEBP_CSP_MODE MODE_RGBA_4444
    WEBP_CSP_MODE MODE_RGB_565
    #RGB-premultiplied transparent modes (alpha value is preserved)
    WEBP_CSP_MODE MODE_rgbA
    WEBP_CSP_MODE MODE_bgrA
    WEBP_CSP_MODE MODE_Argb
    WEBP_CSP_MODE MODE_rgbA_4444
    #YUV modes must come after RGB ones.
    WEBP_CSP_MODE MODE_YUV
    WEBP_CSP_MODE MODE_YUVA                       #yuv 4:2:0


    ctypedef struct WebPDecoderOptions:
        int bypass_filtering            #if true, skip the in-loop filtering
        int no_fancy_upsampling         #if true, use faster pointwise upsampler
        int use_cropping                #if true, cropping is applied _first_
        int crop_left
        int crop_top                    #top-left position for cropping.
                                        #Will be snapped to even values.
        int crop_width
        int crop_height                 #dimension of the cropping area
        int use_scaling                 #if true, scaling is applied _afterward_
        int scaled_width, scaled_height #final resolution
        int use_threads                 #if true, use multi-threaded decoding

        int force_rotation              #forced rotation (to be applied _last_)
        int no_enhancement              #if true, discard enhancement layer
        uint32_t pad[6]                 #padding for later use

    ctypedef struct WebPBitstreamFeatures:
        int width                       #Width in pixels, as read from the bitstream.
        int height                      #Height in pixels, as read from the bitstream.
        int has_alpha                   #True if the bitstream contains an alpha channel.
        int has_animation               #True if the bitstream is an animation.
        #Unused for now:
        int bitstream_version           #should be 0 for now. TODO(later)
        int no_incremental_decoding     #if true, using incremental decoding is not recommended.
        int rotate                      #TODO(later)
        int uv_sampling                 #should be 0 for now. TODO(later)
        uint32_t pad[2]                 #padding for later use

    ctypedef struct WebPRGBABuffer:     #view as RGBA
        uint8_t* rgba                   #pointer to RGBA samples
        int stride                      #stride in bytes from one scanline to the next.
        size_t size                     #total size of the *rgba buffer.

    ctypedef struct WebPYUVABuffer:     #view as YUVA
        uint8_t* y                      #pointer to luma
        uint8_t* u                      #pointer to chroma U
        uint8_t* v                      #pointer to chroma V
        uint8_t* a                      #pointer to alpha samples
        int y_stride                    #luma stride
        int u_stride, v_stride          #chroma strides
        int a_stride                    #alpha stride
        size_t y_size                   #luma plane size
        size_t u_size, v_size           #chroma planes size
        size_t a_size                   #alpha-plane size

    ctypedef struct u:
        WebPRGBABuffer RGBA
        WebPYUVABuffer YUVA

    ctypedef struct WebPDecBuffer:
        WEBP_CSP_MODE colorspace        #Colorspace.
        int width, height               #Dimensions.
        int is_external_memory          #If true, 'internal_memory' pointer is not used.
        u u
        uint32_t       pad[4]           #padding for later use
        uint8_t* private_memory         #Internally allocated memory (only when
                                        #is_external_memory is false). Should not be used
                                        #externally, but accessed via the buffer union.

    ctypedef struct WebPDecoderConfig:
        WebPBitstreamFeatures input     #Immutable bitstream features (optional)
        WebPDecBuffer output            #Output buffer (can point to external mem)
        WebPDecoderOptions options      #Decoding options


    VP8StatusCode WebPGetFeatures(const uint8_t* data, size_t data_size,
                                  WebPBitstreamFeatures* features)

    int WebPInitDecoderConfig(WebPDecoderConfig* config)
    VP8StatusCode WebPDecode(const uint8_t* data, size_t data_size,
                                      WebPDecoderConfig* config)


ERROR_TO_NAME = {
#VP8_STATUS_OK
            VP8_STATUS_OUT_OF_MEMORY        : "out of memory",
            VP8_STATUS_INVALID_PARAM        : "invalid parameter",
            VP8_STATUS_BITSTREAM_ERROR      : "bitstream error",
            VP8_STATUS_UNSUPPORTED_FEATURE  : "unsupported feature",
            VP8_STATUS_SUSPENDED            : "suspended",
            VP8_STATUS_USER_ABORT           : "user abort",
            VP8_STATUS_NOT_ENOUGH_DATA      : "not enough data",
        }

def get_version():
    cdef int version = WebPGetDecoderVersion()
    log("WebPGetDecoderVersion()=%#x", version)
    return (version >> 16) & 0xff, (version >> 8) & 0xff, version & 0xff

def get_info():
    return  {
            "version"      : get_version(),
            "encodings"    : get_encodings(),
            }

def webp_check(int ret):
    if ret==0:
        return
    err = ERROR_TO_NAME.get(ret, ret)
    raise Exception("error: %s" % err)

def get_encodings():
    return ["webp"]


cdef class WebpBufferWrapper:
    """
        Opaque object wrapping the buffer,
        calling free will free the underlying memory.
    """

    cdef unsigned long buffer_ptr
    cdef size_t size

    def __cinit__(self, unsigned long buffer_ptr, size_t size):
        self.buffer_ptr = buffer_ptr
        self.size = size

    def __del__(self):
        assert self.buffer_ptr==0, "WebpBufferWrapper out of scope before being freed!"

    def get_pixels(self):
        assert self.buffer_ptr>0, "WebpBufferWrapper has already been freed!"
        return memory_as_pybuffer(<void *> self.buffer_ptr, self.size, True)

    def free(self):                             #@DuplicatedSignature
        if self.buffer_ptr!=0:
            free(<void *>self.buffer_ptr)
            self.buffer_ptr = 0


def decompress(data, has_alpha, rgb_format=None):
    """
        This returns a WebpBufferWrapper, you MUST call free() on it
        once the pixel buffer can be freed.
    """
    cdef WebPDecoderConfig config
    config.options.use_threads = 1
    WebPInitDecoderConfig(&config)
    webp_check(WebPGetFeatures(data, len(data), &config.input))
    log("webp decompress found features: width=%s, height=%s, has_alpha=%s, input rgb_format=%s", config.input.width, config.input.height, config.input.has_alpha, rgb_format)

    cdef int stride = 4 * config.input.width
    if has_alpha:
        if len(rgb_format or "")!=4:
            #use default if the format given is not valid:
            rgb_format = "BGRA"
        config.output.colorspace = MODE_bgrA
    else:
        if len(rgb_format or "")!=3:
            #use default if the format given is not valid:
            rgb_format = "RGB"
        config.output.colorspace = MODE_RGB
    cdef size_t size = stride * config.input.height
    #allocate the buffer:
    cdef uint8_t *buffer = <uint8_t*> memalign(size + stride)      #add one line of padding
    cdef WebpBufferWrapper b = WebpBufferWrapper(<unsigned long> buffer, size)
    config.output.u.RGBA.rgba   = buffer
    config.output.u.RGBA.stride = stride
    config.output.u.RGBA.size   = size
    config.output.is_external_memory = 1

    webp_check(WebPDecode(data, len(data), &config))

    return b, config.input.width, config.input.height, stride, has_alpha and config.input.has_alpha, rgb_format


def selftest(full=False):
    w, h = 24, 16       #hard coded size of test data
    for has_alpha, hexdata in ((True, "52494646c001000057454250565038580a000000100000001700000f0000414c504881010000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000056503820180000003401009d012a1800100000004c00000f040000fef81f8000"),
                             (False, "52494646c001000057454250565038580a000000100000001700000f0000414c50488101000010ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000056503820180000003401009d012a1800100000004c00000f040000fef81f8000")):
        import binascii
        bdata = binascii.unhexlify(hexdata)
        b, iw, ih, stride, ia, rgb = decompress(bdata, has_alpha)
        assert iw==w and ih==h and ia==has_alpha
        assert len(b.get_pixels())>0
        #print("compressed data(%s)=%s" % (has_alpha, binascii.hexlify(r)))
