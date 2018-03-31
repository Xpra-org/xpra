# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import absolute_import

import os

from xpra.log import Logger
log = Logger("encoder", "webp")

from xpra.buffers.membuf cimport memalign, object_as_buffer
from xpra.os_util import bytestostr

from xpra.util import envbool, envint
cdef int LOG_CONFIG = envbool("XPRA_WEBP_LOG_CONFIG", False)
cdef int WEBP_THREADING = envbool("XPRA_WEBP_THREADING", True)
cdef int LOSSLESS_THRESHOLD = envint("XPRA_WEBP_LOSSLESS_THRESHOLD", 75)
cdef int SUBSAMPLING_THRESHOLD = envint("XPRA_WEBP_SUBSAMPLING_THRESHOLD", 40)
assert SUBSAMPLING_THRESHOLD<=LOSSLESS_THRESHOLD, "lossless threshold must be higher than subsampling threshold"
assert LOSSLESS_THRESHOLD>=0 and LOSSLESS_THRESHOLD<=100, "invalid lossless threshold: %i" % LOSSLESS_THRESHOLD

cdef inline int MIN(int a, int b):
    if a<=b:
        return a
    return b
cdef inline int MAX(int a, int b):
    if a>=b:
        return a
    return b


from libc.stdint cimport uint8_t, uint32_t, uintptr_t

cdef extern from "string.h":
    void * memset ( void * ptr, int value, size_t num )

cdef extern from *:
    ctypedef unsigned long size_t

cdef extern from "stdlib.h":
    void free(void *ptr)


DEF WEBP_MAX_DIMENSION = 16383

cdef extern from "webp/encode.h":

    int WebPGetEncoderVersion()

    ctypedef int WebPImageHint
    # WebPImageHint:
    WebPImageHint WEBP_HINT_DEFAULT     #default preset
    WebPImageHint WEBP_HINT_PICTURE     #digital picture, like portrait, inner shot
    WebPImageHint WEBP_HINT_PHOTO       #outdoor photograph, with natural lighting
    WebPImageHint WEBP_HINT_GRAPH       #Discrete tone image (graph, map-tile etc).

    ctypedef int WebPPreset
    WebPPreset WEBP_PRESET_DEFAULT      #default preset.
    WebPPreset WEBP_PRESET_PICTURE      #digital picture, like portrait, inner shot
    WebPPreset WEBP_PRESET_PHOTO        #outdoor photograph, with natural lighting
    WebPPreset WEBP_PRESET_DRAWING      #hand or line drawing, with high-contrast details
    WebPPreset WEBP_PRESET_ICON         #small-sized colorful images
    WebPPreset WEBP_PRESET_TEXT         #text-like

    ctypedef int WebPEncCSP
    #chroma sampling
    WebPEncCSP WEBP_YUV420              #4:2:0
    WebPEncCSP WEBP_YUV422              #4:2:2
    WebPEncCSP WEBP_YUV444              #4:4:4
    WebPEncCSP WEBP_YUV400              #grayscale
    WebPEncCSP WEBP_CSP_UV_MASK         #bit-mask to get the UV sampling factors
    WebPEncCSP WEBP_YUV420A
    WebPEncCSP WEBP_YUV422A
    WebPEncCSP WEBP_YUV444A
    WebPEncCSP WEBP_YUV400A             #grayscale + alpha
    WebPEncCSP WEBP_CSP_ALPHA_BIT       #bit that is set if alpha is present

    ctypedef int WebPEncodingError
    WebPEncodingError VP8_ENC_OK
    WebPEncodingError VP8_ENC_ERROR_OUT_OF_MEMORY
    WebPEncodingError VP8_ENC_ERROR_BITSTREAM_OUT_OF_MEMORY
    WebPEncodingError VP8_ENC_ERROR_NULL_PARAMETER
    WebPEncodingError VP8_ENC_ERROR_INVALID_CONFIGURATION
    WebPEncodingError VP8_ENC_ERROR_BAD_DIMENSION
    WebPEncodingError VP8_ENC_ERROR_PARTITION0_OVERFLOW
    WebPEncodingError VP8_ENC_ERROR_PARTITION_OVERFLOW
    WebPEncodingError VP8_ENC_ERROR_BAD_WRITE
    WebPEncodingError VP8_ENC_ERROR_FILE_TOO_BIG
    WebPEncodingError VP8_ENC_ERROR_USER_ABORT
    WebPEncodingError VP8_ENC_ERROR_LAST

    ctypedef struct WebPConfig:
        int lossless                    #Lossless encoding (0=lossy(default), 1=lossless).
        float quality                   #between 0 (smallest file) and 100 (biggest)
        int method                      #quality/speed trade-off (0=fast, 6=slower-better)

        WebPImageHint image_hint        #Hint for image type (lossless only for now).

        #Parameters related to lossy compression only:
        int target_size                 #if non-zero, set the desired target size in bytes.
                                        #Takes precedence over the 'compression' parameter.
        float target_PSNR               #if non-zero, specifies the minimal distortion to
                                        #try to achieve. Takes precedence over target_size.
        int segments                    #maximum number of segments to use, in [1..4]
        int sns_strength                #Spatial Noise Shaping. 0=off, 100=maximum.
        int filter_strength             #range: [0 = off .. 100 = strongest]
        int filter_sharpness            #range: [0 = off .. 7 = least sharp]
        int filter_type                 #filtering type: 0 = simple, 1 = strong (only used
                                        #if filter_strength > 0 or autofilter > 0)
        int autofilter                  #Auto adjust filter's strength [0 = off, 1 = on]
        int alpha_compression           #Algorithm for encoding the alpha plane (0 = none,
                                        #1 compressed with WebP lossless). Default is 1.
        int alpha_filtering             #Predictive filtering method for alpha plane.
                                        #0: none, 1: fast, 2: best. Default if 1.
        int alpha_quality               #Between 0 (smallest size) and 100 (lossless).
                                        #Default is 100.
        int _pass "pass"                #number of entropy-analysis passes (in [1..10]).

        int show_compressed             #if true, export the compressed picture back.
                                        #In-loop filtering is not applied.
        int preprocessing               #preprocessing filter (0=none, 1=segment-smooth)
        int partitions                  #log2(number of token partitions) in [0..3]. Default
                                        #is set to 0 for easier progressive decoding.
        int partition_limit             #quality degradation allowed to fit the 512k limit
                                        #on prediction modes coding (0: no degradation,
                                        #100: maximum possible degradation).
        int emulate_jpeg_size           #If true, compression parameters will be remapped
                                        #to better match the expected output size from
                                        #JPEG compression. Generally, the output size will
                                        #be similar but the degradation will be lower.
        int thread_level                #If non-zero, try and use multi-threaded encoding.
        int low_memory                  #If set, reduce memory usage (but increase CPU use).

        int near_lossless               #Near lossless encoding [0 = max loss .. 100 = off
                                        #(default)
        int exact                       #if non-zero, preserve the exact RGB values under
                                        #transparent area. Otherwise, discard this invisible
                                        #RGB information for better compression. The default
                                        #value is 0.
        uint32_t pad[3]                 #padding for later use

    ctypedef struct WebPMemoryWriter:
        uint8_t* mem                    #final buffer (of size 'max_size', larger than 'size').
        size_t   size                   #final size
        size_t   max_size               #total capacity
        uint32_t pad[1]

    ctypedef void *WebPWriterFunction
    ctypedef void *WebPProgressHook
    ctypedef void *WebPAuxStats

    ctypedef struct WebPPicture:
        #   INPUT
        # Main flag for encoder selecting between ARGB or YUV input.
        # It is recommended to use ARGB input (*argb, argb_stride) for lossless
        # compression, and YUV input (*y, *u, *v, etc.) for lossy compression
        # since these are the respective native colorspace for these formats.
        int use_argb

        # YUV input (mostly used for input to lossy compression)
        WebPEncCSP colorspace           #colorspace: should be YUV420 for now (=Y'CbCr).
        int width, height               #dimensions (less or equal to WEBP_MAX_DIMENSION)
        uint8_t *y
        uint8_t *u
        uint8_t *v
        int y_stride, uv_stride         #luma/chroma strides.
        uint8_t* a                      #pointer to the alpha plane
        int a_stride                    #stride of the alpha plane
        uint32_t pad1[2]                #padding for later use

        # ARGB input (mostly used for input to lossless compression)
        uint32_t* argb                  #Pointer to argb (32 bit) plane.
        int argb_stride                 #This is stride in pixels units, not bytes.
        uint32_t pad2[3]                #padding for later use

        #   OUTPUT
        # Byte-emission hook, to store compressed bytes as they are ready.
        WebPWriterFunction writer       #can be NULL
        void* custom_ptr                #can be used by the writer.

        # map for extra information (only for lossy compression mode)
        int extra_info_type             #1: intra type, 2: segment, 3: quant
                                        #4: intra-16 prediction mode,
                                        #5: chroma prediction mode,
                                        #6: bit cost, 7: distortion
        uint8_t* extra_info             #if not NULL, points to an array of size
                                        # ((width + 15) / 16) * ((height + 15) / 16) that
                                        #will be filled with a macroblock map, depending
                                        #on extra_info_type.

        #   STATS AND REPORTS
        # Pointer to side statistics (updated only if not NULL)
        WebPAuxStats* stats

        # Error code for the latest error encountered during encoding
        WebPEncodingError error_code

        #If not NULL, report progress during encoding.
        WebPProgressHook progress_hook

        void* user_data                 #this field is free to be set to any value and
                                        #used during callbacks (like progress-report e.g.).

        uint32_t pad3[3]                #padding for later use

        # Unused for now: original samples (for non-YUV420 modes)
        uint8_t *u0
        uint8_t *v0
        int uv0_stride

        uint32_t pad4[7]                #padding for later use

        # PRIVATE FIELDS
        void* memory_                   #row chunk of memory for yuva planes
        void* memory_argb_              #and for argb too.
        void* pad5[2]                   #padding for later use

    void WebPMemoryWriterInit(WebPMemoryWriter* writer)
    int WebPMemoryWrite(const uint8_t* data, size_t data_size, const WebPPicture* picture)

    int WebPConfigInit(WebPConfig* config)
    int WebPConfigPreset(WebPConfig* config, WebPPreset preset, float quality)
    int WebPValidateConfig(const WebPConfig* config)
    int WebPPictureInit(WebPPicture* picture)
    void WebPPictureFree(WebPPicture* picture)

    # Colorspace conversion function to import RGB samples.
    # Previous buffer will be free'd, if any.
    # *rgb buffer should have a size of at least height * rgb_stride.
    # Returns false in case of memory error.
    int WebPPictureImportRGB(WebPPicture* picture, const uint8_t* rgb, int rgb_stride)
    # Same, but for RGBA buffer.
    int WebPPictureImportRGBA(WebPPicture* picture, const uint8_t* rgba, int rgba_stride)
    # Same, but for RGBA buffer. Imports the RGB direct from the 32-bit format
    # input buffer ignoring the alpha channel. Avoids needing to copy the data
    # to a temporary 24-bit RGB buffer to import the RGB only.
    int WebPPictureImportRGBX(WebPPicture* picture, const uint8_t* rgbx, int rgbx_stride)

    # Variants of the above, but taking BGR(A|X) input.
    int WebPPictureImportBGR(WebPPicture* picture, const uint8_t* bgr, int bgr_stride)
    int WebPPictureImportBGRA(WebPPicture* picture, const uint8_t* bgra, int bgra_stride)
    int WebPPictureImportBGRX(WebPPicture* picture, const uint8_t* bgrx, int bgrx_stride)

    # Converts picture->argb data to the YUVA format specified by 'colorspace'.
    # Upon return, picture->use_argb is set to false. The presence of real
    # non-opaque transparent values is detected, and 'colorspace' will be
    # adjusted accordingly. Note that this method is lossy.
    # Returns false in case of error.
    int WebPPictureARGBToYUVA(WebPPicture* picture, WebPEncCSP colorspace)

    # Converts picture->yuv to picture->argb and sets picture->use_argb to true.
    # The input format must be YUV_420 or YUV_420A.
    # Note that the use of this method is discouraged if one has access to the
    # raw ARGB samples, since using YUV420 is comparatively lossy. Also, the
    # conversion from YUV420 to ARGB incurs a small loss too.
    # Returns false in case of error.
    int WebPPictureYUVAToARGB(WebPPicture* picture)

    # Helper function: given a width x height plane of YUV(A) samples
    # (with stride 'stride'), clean-up the YUV samples under fully transparent
    # area, to help compressibility (no guarantee, though).
    void WebPCleanupTransparentArea(WebPPicture* picture)

    # Scan the picture 'picture' for the presence of non fully opaque alpha values.
    # Returns true in such case. Otherwise returns false (indicating that the
    # alpha plane can be ignored altogether e.g.).
    int WebPPictureHasTransparency(const WebPPicture* picture)

    # Main encoding call, after config and picture have been initialized.
    # 'picture' must be less than 16384x16384 in dimension (cf WEBP_MAX_DIMENSION),
    # and the 'config' object must be a valid one.
    # Returns false in case of error, true otherwise.
    # In case of error, picture->error_code is updated accordingly.
    # 'picture' can hold the source samples in both YUV(A) or ARGB input, depending
    # on the value of 'picture->use_argb'. It is highly recommended to use
    # the former for lossy encoding, and the latter for lossless encoding
    # (when config.lossless is true). Automatic conversion from one format to
    # another is provided but they both incur some loss.
    int WebPEncode(const WebPConfig* config, WebPPicture* picture)


ERROR_TO_NAME = {
#VP8_ENC_OK
                VP8_ENC_ERROR_OUT_OF_MEMORY             : "memory error allocating objects",
                VP8_ENC_ERROR_BITSTREAM_OUT_OF_MEMORY   : "memory error while flushing bits",
                VP8_ENC_ERROR_NULL_PARAMETER            : "a pointer parameter is NULL",
                VP8_ENC_ERROR_INVALID_CONFIGURATION     : "configuration is invalid",
                VP8_ENC_ERROR_BAD_DIMENSION             : "picture has invalid width/height",
                VP8_ENC_ERROR_PARTITION0_OVERFLOW       : "partition is bigger than 512k",
                VP8_ENC_ERROR_PARTITION_OVERFLOW        : "partition is bigger than 16M",
                VP8_ENC_ERROR_BAD_WRITE                 : "error while flushing bytes",
                VP8_ENC_ERROR_FILE_TOO_BIG              : "file is bigger than 4G",
                VP8_ENC_ERROR_USER_ABORT                : "abort request by user",
                }

PRESETS = {
           WEBP_PRESET_DEFAULT      : "default",
           WEBP_PRESET_PICTURE      : "picture",
           WEBP_PRESET_PHOTO        : "photo",
           WEBP_PRESET_DRAWING      : "drawing",
           WEBP_PRESET_ICON         : "icon",
           WEBP_PRESET_TEXT         : "text",
           }
PRESET_NAME_TO_CONSTANT = {}
for k,v in PRESETS.items():
    PRESET_NAME_TO_CONSTANT[v] = k

CONTENT_TYPE_PRESET = {
    "picture"   : WEBP_PRESET_PICTURE,
    "text"      : WEBP_PRESET_TEXT,
    "browser"   : WEBP_PRESET_TEXT,
    }

IMAGE_HINT = {
              WEBP_HINT_DEFAULT     : "default",
              WEBP_HINT_PICTURE     : "picture",
              WEBP_HINT_PHOTO       : "photo",
              WEBP_HINT_GRAPH       : "graph",
              }
HINT_NAME_TO_CONSTANT = {}
for k,v in IMAGE_HINT.items():
    HINT_NAME_TO_CONSTANT[v] = k

CONTENT_TYPE_HINT = {
    "picture"   : WEBP_HINT_PICTURE,
    }

cdef WebPImageHint DEFAULT_IMAGE_HINT = HINT_NAME_TO_CONSTANT.get(os.environ.get("XPRA_WEBP_IMAGE_HINT", "graph").lower(), WEBP_HINT_GRAPH)
cdef WebPPreset DEFAULT_PRESET = PRESET_NAME_TO_CONSTANT.get(os.environ.get("XPRA_WEBP_PRESET", "text").lower(), WEBP_PRESET_TEXT)
cdef WebPPreset PRESET_SMALL = PRESET_NAME_TO_CONSTANT.get(os.environ.get("XPRA_WEBP_PRESET_SMALL", "icon").lower(), WEBP_PRESET_ICON)


def get_encodings():
    return ["webp"]

def get_version():
    cdef int version = WebPGetEncoderVersion()
    log("WebPGetEncoderVersion()=%#x", version)
    return (version >> 16) & 0xff, (version >> 8) & 0xff, version & 0xff

def get_info():
    return  {
            "version"       : get_version(),
            "encodings"     : get_encodings(),
            "threading"     : bool(WEBP_THREADING),
            "image-hint"    : DEFAULT_IMAGE_HINT,
            "image-hints"   : IMAGE_HINT.values(),
            "preset"        : DEFAULT_PRESET,
            "preset-small"  : PRESET_SMALL,
            "presets"       : PRESETS.values(),
            }

def webp_check(int ret):
    if ret==0:
        return
    err = ERROR_TO_NAME.get(ret, ret)
    raise Exception("error: %s" % err)

cdef float fclamp(int v):
    if v<0:
        v = 0
    elif v>100:
        v = 100
    return <float> v


cdef get_config_info(WebPConfig *config):
    return {
        "lossless"          : config.lossless,
        "method"            : config.method,
        "image_hint"        : IMAGE_HINT.get(config.image_hint, config.image_hint),
        "target_size"       : config.target_size,
        "target_PSNR"       : config.target_PSNR,
        "segments"          : config.segments,
        "sns_strength"      : config.sns_strength,
        "filter_strength"   : config.filter_strength,
        "filter_sharpness"  : config.filter_sharpness,
        "filter_type"       : config.filter_type,
        "autofilter"        : config.autofilter,
        "alpha_compression" : config.alpha_compression,
        "alpha_filtering"   : config.alpha_filtering,
        "alpha_quality"     : config.alpha_quality,
        "pass"              : config._pass,
        "show_compressed"   : config.show_compressed,
        "preprocessing"     : config.preprocessing,
        "partitions"        : config.partitions,
        "partition_limit"   : config.partition_limit,
        "emulate_jpeg_size" : config.emulate_jpeg_size,
        "thread_level"      : config.thread_level,
        "low_memory"        : config.low_memory,
        }

def compress(image, int quality=50, int speed=50, supports_alpha=False, content_type=""):
    pixel_format = image.get_pixel_format()
    if pixel_format not in ("RGBX", "RGBA", "BGRX", "BGRA"):
        raise Exception("unsupported pixel format %s" % pixel_format)
    cdef unsigned int width = image.get_width()
    cdef unsigned int height = image.get_height()
    cdef unsigned int stride = image.get_rowstride()
    cdef unsigned int Bpp = len(pixel_format)
    if width>WEBP_MAX_DIMENSION or height>WEBP_MAX_DIMENSION:
        raise Exception("this image is too big for webp: %ix%i" % (width, height))
    pixels = image.get_pixels()

    cdef uint8_t *pic_buf
    cdef Py_ssize_t pic_buf_len = 0
    cdef WebPConfig config
    cdef WebPPreset preset = DEFAULT_PRESET
    #only use icon for small squarish rectangles
    if width*height<=2304 and abs(width-height)<=16:
        preset = PRESET_SMALL
    preset = CONTENT_TYPE_PRESET.get(content_type, preset)
    cdef WebPImageHint image_hint = CONTENT_TYPE_HINT.get(content_type, DEFAULT_IMAGE_HINT)

    cdef int ret = object_as_buffer(pixels, <const void**> &pic_buf, &pic_buf_len)
    assert ret==0, "failed to get buffer from pixel object: %s (returned %s)" % (type(pixels), ret)
    log("webp.compress(%s, %i, %i, %s, %s) buf=%#x", image, width, height, supports_alpha, content_type, <uintptr_t> pic_buf)
    cdef int size = stride * height
    assert pic_buf_len>=size, "pixel buffer is too small: expected at least %s bytes but got %s" % (size, pic_buf_len)

    cdef int i
    cdef int alpha_int = int(supports_alpha and pixel_format.find("A")>=0)
    cdef int use_argb = int(quality>=SUBSAMPLING_THRESHOLD)
    if alpha_int==0 and Bpp==4:
        #ensure webp will not decide to encode the alpha channel
        #(this is stupid: we should be able to pass a flag instead)
        i = 3
        while i<size:
            pic_buf[i] = 0xff
            i += 4

    ret = WebPConfigInit(&config)
    if not ret:
        raise Exception("failed to initialize webp config")

    ret = WebPConfigPreset(&config, preset, fclamp(quality))
    if not ret:
        raise Exception("failed to set webp preset")

    #tune it:
    config.lossless = quality>=LOSSLESS_THRESHOLD
    if config.lossless:
        #not much to gain from setting a high quality here,
        #the latency will be higher for a negligible compression gain: 
        config.quality = fclamp(50-speed//2)
    else:
        #normalize quality: webp quality is much higher than jpeg's
        #so we can go lower,
        #[0,10,...,90,100] maps to:
        #[0, 3, 7, 13, 20, 29, 40, 52, 66, 82, 100]
        config.quality = fclamp(((quality+10)**2//121))
    #"method" takes values from 0 to 6,
    #but anything higher than 1 is dreadfully slow,
    #so only use method=1 when speed is already very low
    config.method = int(speed<10)
    config.alpha_compression = alpha_int
    config.alpha_filtering = MAX(0, MIN(2, speed/50)) * alpha_int
    config.alpha_quality = quality * alpha_int
    if config.lossless:
        config.autofilter = 1
    else:
        config.segments = 1
        config.sns_strength = 0
        config.filter_strength = 0
        config.filter_sharpness = 7-quality//15
        config.filter_type = 0
        config.autofilter = 0
    config._pass = MAX(1, MIN(10, (100-speed)//10))
    config.preprocessing = int(speed<50)
    config.image_hint = image_hint
    config.thread_level = WEBP_THREADING
    config.partitions = 3
    config.partition_limit = MAX(0, MIN(100, 100-quality))

    log("webp.compress config: lossless=%-5s, quality=%3i, method=%i, alpha=%3i,%3i,%3i, preset=%-8s, image hint=%s", config.lossless, config.quality, config.method,
                    config.alpha_compression, config.alpha_filtering, config.alpha_quality, PRESETS.get(preset, preset), IMAGE_HINT.get(image_hint, image_hint))
    ret = WebPValidateConfig(&config)
    if not ret:
        info = get_config_info(&config)
        raise Exception("invalid webp configuration: %s" % info)

    cdef WebPPicture pic
    ret = WebPPictureInit(&pic)
    if not ret:
        raise Exception("failed to initialise webp picture")

    client_options = {
        #no need to expose speed
        #(not used for anything downstream)
        #"speed"       : speed,
        "rgb_format"  : pixel_format,
        }

    memset(&pic, 0, sizeof(WebPPicture))
    pic.width = width
    pic.height = height
    pic.use_argb = 1
    pic.argb = <uint32_t*> pic_buf
    pic.argb_stride = stride//Bpp
    if not use_argb:
        if WebPPictureARGBToYUVA(&pic, WEBP_YUV420A):
            client_options["subsampling"] = "YUV420P"
            #redundant (changed by WebPPictureARGBToYUVA):
            #pic.use_argb = 0
        else:
            raise Exception("failed to convert picture to YUV")

    #TODO: custom writer that over-allocates memory
    cdef WebPMemoryWriter memory_writer
    WebPMemoryWriterInit(&memory_writer)
    pic.writer = <WebPWriterFunction> WebPMemoryWrite
    pic.custom_ptr = <void*> &memory_writer
    ret = WebPEncode(&config, &pic)
    if not ret:
        raise Exception("WebPEncode failed: %s, config=%s" % (ERROR_TO_NAME.get(pic.error_code, pic.error_code), get_config_info(&config)))

    cdata = memory_writer.mem[:memory_writer.size]
    free(memory_writer.mem)
    WebPPictureFree(&pic)
    if config.lossless:
        client_options["quality"] = 100
    elif quality>=0 and quality<=100:
        client_options["quality"] = quality
    if alpha_int:
        client_options["has_alpha"] = True
    log("webp.compress ratio=%i%%, client-options=%s", 100*memory_writer.size//size, client_options)
    if LOG_CONFIG>0:
        log("webp.compress used config: %s", get_config_info(&config))
    return cdata, client_options


def selftest(full=False):
    #fake empty buffer:
    from xpra.codecs.codec_checks import make_test_image
    w, h = 24, 16
    pixels = bytearray(b"\0" * w*h*4)
    for has_alpha in (True, False):
        img = make_test_image("BGR%s" % ["X", "A"][has_alpha], w, h)
        for q in (10, 50, 90):
            r = compress(img, quality=q, speed=50, supports_alpha=has_alpha)
            assert len(r)>0
        #import binascii
        #print("compressed data(%s)=%s" % (has_alpha, binascii.hexlify(r)))
