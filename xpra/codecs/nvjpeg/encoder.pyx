# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic, time

from libc.stdint cimport uintptr_t
from xpra.buffers.membuf cimport getbuf, MemBuf #pylint: disable=syntax-error

from pycuda import driver

from xpra.util import envbool, typedict
from xpra.os_util import bytestostr

from xpra.log import Logger
log = Logger("encoder", "nvjpeg")


cdef int SAVE_TO_FILE = envbool("XPRA_SAVE_TO_FILE")

DEF NVJPEG_MAX_COMPONENT = 4

cdef extern from "cuda_runtime_api.h":
    ctypedef int cudaError_t
    ctypedef void* cudaStream_t
    cudaError_t cudaStreamCreate(cudaStream_t* pStream)
    cudaError_t cudaStreamSynchronize(cudaStream_t stream)

cdef extern from "library_types.h":
    cdef enum libraryPropertyType_t:
        MAJOR_VERSION
        MINOR_VERSION
        PATCH_LEVEL

cdef extern from "nvjpeg.h":
    int NVJPEG_MAX_COMPONENT

    int NVJPEG_VER_MAJOR    #ie: 11
    int NVJPEG_VER_MINOR    #ie: 3
    int NVJPEG_VER_PATCH    #ie: 1
    int NVJPEG_VER_BUILD    #ie: 68

    ctypedef void* NV_ENC_INPUT_PTR
    ctypedef void* NV_ENC_OUTPUT_PTR
    ctypedef void* NV_ENC_REGISTERED_PTR

    ctypedef enum nvjpegStatus_t:
        NVJPEG_STATUS_SUCCESS
        NVJPEG_STATUS_NOT_INITIALIZED
        NVJPEG_STATUS_INVALID_PARAMETER
        NVJPEG_STATUS_BAD_JPEG
        NVJPEG_STATUS_JPEG_NOT_SUPPORTED
        NVJPEG_STATUS_ALLOCATOR_FAILURE
        NVJPEG_STATUS_EXECUTION_FAILED
        NVJPEG_STATUS_ARCH_MISMATCH
        NVJPEG_STATUS_INTERNAL_ERROR
        NVJPEG_STATUS_IMPLEMENTATION_NOT_SUPPORTED

    ctypedef enum nvjpegChromaSubsampling_t:
        NVJPEG_CSS_444
        NVJPEG_CSS_422
        NVJPEG_CSS_420
        NVJPEG_CSS_440
        NVJPEG_CSS_411
        NVJPEG_CSS_410
        NVJPEG_CSS_GRAY
        NVJPEG_CSS_UNKNOWN

    ctypedef enum nvjpegOutputFormat_t:
        NVJPEG_OUTPUT_UNCHANGED
        # return planar luma and chroma, assuming YCbCr colorspace
        NVJPEG_OUTPUT_YUV
        # return luma component only, if YCbCr colorspace
        # or try to convert to grayscale,
        # writes to 1-st channel of nvjpegImage_t
        NVJPEG_OUTPUT_Y
        # convert to planar RGB
        NVJPEG_OUTPUT_RGB
        # convert to planar BGR
        NVJPEG_OUTPUT_BGR
        # convert to interleaved RGB and write to 1-st channel of nvjpegImage_t
        NVJPEG_OUTPUT_RGBI
        # convert to interleaved BGR and write to 1-st channel of nvjpegImage_t
        NVJPEG_OUTPUT_BGRI
        # maximum allowed value
        NVJPEG_OUTPUT_FORMAT_MAX

    ctypedef enum nvjpegInputFormat_t:
        NVJPEG_INPUT_RGB    # Input is RGB - will be converted to YCbCr before encoding
        NVJPEG_INPUT_BGR    # Input is RGB - will be converted to YCbCr before encoding
        NVJPEG_INPUT_RGBI   # Input is interleaved RGB - will be converted to YCbCr before encoding
        NVJPEG_INPUT_BGRI   # Input is interleaved RGB - will be converted to YCbCr before encoding

    ctypedef enum nvjpegBackend_t:
        NVJPEG_BACKEND_DEFAULT
        NVJPEG_BACKEND_HYBRID       # uses CPU for Huffman decode
        NVJPEG_BACKEND_GPU_HYBRID   # uses GPU assisted Huffman decode. nvjpegDecodeBatched will use GPU decoding for baseline JPEG bitstreams with
                                    # interleaved scan when batch size is bigger than 100
        NVJPEG_BACKEND_HARDWARE     # supports baseline JPEG bitstream with single scan. 410 and 411 sub-samplings are not supported

    ctypedef enum nvjpegJpegEncoding_t:
        NVJPEG_ENCODING_UNKNOWN
        NVJPEG_ENCODING_BASELINE_DCT
        NVJPEG_ENCODING_EXTENDED_SEQUENTIAL_DCT_HUFFMAN
        NVJPEG_ENCODING_PROGRESSIVE_DCT_HUFFMAN


    ctypedef struct nvjpegImage_t:
        unsigned char * channel[NVJPEG_MAX_COMPONENT]
        size_t    pitch[NVJPEG_MAX_COMPONENT]

    ctypedef int (*tDevMalloc)(void**, size_t)
    ctypedef int (*tDevFree)(void*)

    ctypedef int (*tPinnedMalloc)(void**, size_t, unsigned int flags)
    ctypedef int (*tPinnedFree)(void*)

    ctypedef struct nvjpegDevAllocator_t:
        tDevMalloc dev_malloc;
        tDevFree dev_free;

    ctypedef struct nvjpegPinnedAllocator_t:
        tPinnedMalloc pinned_malloc
        tPinnedFree pinned_free

    ctypedef struct nvjpegHandle:
        pass
    ctypedef nvjpegHandle* nvjpegHandle_t

    nvjpegStatus_t nvjpegGetProperty(libraryPropertyType_t type, int *value)
    nvjpegStatus_t nvjpegGetCudartProperty(libraryPropertyType_t type, int *value)
    nvjpegStatus_t nvjpegCreate(nvjpegBackend_t backend, nvjpegDevAllocator_t *dev_allocator, nvjpegHandle_t *handle)
    nvjpegStatus_t nvjpegCreateSimple(nvjpegHandle_t *handle)
    nvjpegStatus_t nvjpegCreateEx(nvjpegBackend_t backend,
        nvjpegDevAllocator_t *dev_allocator,
        nvjpegPinnedAllocator_t *pinned_allocator,
        unsigned int flags,
        nvjpegHandle_t *handle)

    nvjpegStatus_t nvjpegDestroy(nvjpegHandle_t handle)
    nvjpegStatus_t nvjpegSetDeviceMemoryPadding(size_t padding, nvjpegHandle_t handle)
    nvjpegStatus_t nvjpegGetDeviceMemoryPadding(size_t *padding, nvjpegHandle_t handle)
    nvjpegStatus_t nvjpegSetPinnedMemoryPadding(size_t padding, nvjpegHandle_t handle)
    nvjpegStatus_t nvjpegGetPinnedMemoryPadding(size_t *padding, nvjpegHandle_t handle)

    nvjpegStatus_t nvjpegGetImageInfo(
        nvjpegHandle_t handle,
        const unsigned char *data,
        size_t length,
        int *nComponents,
        nvjpegChromaSubsampling_t *subsampling,
        int *widths,
        int *heights)

    #Encode:
    ctypedef struct nvjpegEncoderState:
        pass
    ctypedef nvjpegEncoderState* nvjpegEncoderState_t

    nvjpegStatus_t nvjpegEncoderStateCreate(
        nvjpegHandle_t handle,
        nvjpegEncoderState_t *encoder_state,
        cudaStream_t stream);
    nvjpegStatus_t nvjpegEncoderStateDestroy(nvjpegEncoderState_t encoder_state)
    ctypedef struct nvjpegEncoderParams:
        pass
    ctypedef nvjpegEncoderParams* nvjpegEncoderParams_t
    nvjpegStatus_t nvjpegEncoderParamsCreate(
        nvjpegHandle_t handle,
        nvjpegEncoderParams_t *encoder_params,
        cudaStream_t stream)
    nvjpegStatus_t nvjpegEncoderParamsDestroy(nvjpegEncoderParams_t encoder_params)
    nvjpegStatus_t nvjpegEncoderParamsSetQuality(
        nvjpegEncoderParams_t encoder_params,
        const int quality,
        cudaStream_t stream)
    nvjpegStatus_t nvjpegEncoderParamsSetEncoding(
        nvjpegEncoderParams_t encoder_params,
        nvjpegJpegEncoding_t etype,
        cudaStream_t stream)
    nvjpegStatus_t nvjpegEncoderParamsSetOptimizedHuffman(
        nvjpegEncoderParams_t encoder_params,
        const int optimized,
        cudaStream_t stream)
    nvjpegStatus_t nvjpegEncoderParamsSetSamplingFactors(
        nvjpegEncoderParams_t encoder_params,
        const nvjpegChromaSubsampling_t chroma_subsampling,
        cudaStream_t stream)
    nvjpegStatus_t nvjpegEncodeGetBufferSize(
        nvjpegHandle_t handle,
        const nvjpegEncoderParams_t encoder_params,
        int image_width,
        int image_height,
        size_t *max_stream_length)
    nvjpegStatus_t nvjpegEncodeYUV(
            nvjpegHandle_t handle,
            nvjpegEncoderState_t encoder_state,
            const nvjpegEncoderParams_t encoder_params,
            const nvjpegImage_t *source,
            nvjpegChromaSubsampling_t chroma_subsampling,
            int image_width,
            int image_height,
            cudaStream_t stream);
    nvjpegStatus_t nvjpegEncodeImage(
            nvjpegHandle_t handle,
            nvjpegEncoderState_t encoder_state,
            const nvjpegEncoderParams_t encoder_params,
            const nvjpegImage_t *source,
            nvjpegInputFormat_t input_format,
            int image_width,
            int image_height,
            cudaStream_t stream);
    nvjpegStatus_t nvjpegEncodeRetrieveBitstreamDevice(
            nvjpegHandle_t handle,
            nvjpegEncoderState_t encoder_state,
            unsigned char *data,
            size_t *length,
            cudaStream_t stream)
    nvjpegStatus_t nvjpegEncodeRetrieveBitstream(
            nvjpegHandle_t handle,
            nvjpegEncoderState_t encoder_state,
            unsigned char *data,
            size_t *length,
            cudaStream_t stream)

ERR_STRS = {
    NVJPEG_STATUS_SUCCESS                       : "SUCCESS",
    NVJPEG_STATUS_NOT_INITIALIZED               : "NOT_INITIALIZED",
    NVJPEG_STATUS_INVALID_PARAMETER             : "INVALID_PARAMETER",
    NVJPEG_STATUS_BAD_JPEG                      : "BAD_JPEG",
    NVJPEG_STATUS_JPEG_NOT_SUPPORTED            : "JPEG_NOT_SUPPORTED",
    NVJPEG_STATUS_ALLOCATOR_FAILURE             : "ALLOCATOR_FAILURE",
    NVJPEG_STATUS_EXECUTION_FAILED              : "EXECUTION_FAILED",
    NVJPEG_STATUS_ARCH_MISMATCH                 : "ARCH_MISMATCH",
    NVJPEG_STATUS_INTERNAL_ERROR                : "INTERNAL_ERROR",
    NVJPEG_STATUS_IMPLEMENTATION_NOT_SUPPORTED  : "IMPLEMENTATION_NOT_SUPPORTED",
    }

CSS_STR = {
    NVJPEG_CSS_444  : "444",
    NVJPEG_CSS_422  : "422",
    NVJPEG_CSS_420  : "420",
    NVJPEG_CSS_440  : "440",
    NVJPEG_CSS_411  : "411",
    NVJPEG_CSS_410  : "410",
    NVJPEG_CSS_GRAY : "gray",
    NVJPEG_CSS_UNKNOWN  : "unknown",
    }

ENCODING_STR = {
    NVJPEG_ENCODING_UNKNOWN                         : "unknown",
    NVJPEG_ENCODING_BASELINE_DCT                    : "baseline-dct",
    NVJPEG_ENCODING_EXTENDED_SEQUENTIAL_DCT_HUFFMAN : "extended-sequential-dct-huffman",
    NVJPEG_ENCODING_PROGRESSIVE_DCT_HUFFMAN         : "progressive-dct-huffman",
    }

NVJPEG_INPUT_STR = {
    NVJPEG_INPUT_RGB    : "RGB",
    NVJPEG_INPUT_BGR    : "BGR",
    NVJPEG_INPUT_RGBI   : "RGBI",
    NVJPEG_INPUT_BGRI   : "BGRI",
    }

FORMAT_VAL = {
    #not clear what these non-interleaved formats are,
    #so let's not try to use them:
    #"RGB"   : NVJPEG_INPUT_RGB,
    #"BGR"   : NVJPEG_INPUT_BGR,
    "BGR"  : NVJPEG_INPUT_BGRI,
    "RGB"  : NVJPEG_INPUT_RGBI,
    }


def get_version():
    cdef int major_version, minor_version, patch_level
    r = nvjpegGetProperty(MAJOR_VERSION, &major_version)
    errcheck(r, "nvjpegGetProperty MAJOR_VERSION")
    r = nvjpegGetProperty(MINOR_VERSION, &minor_version)
    errcheck(r, "nvjpegGetProperty MINOR_VERSION")
    r = nvjpegGetProperty(PATCH_LEVEL, &patch_level)
    errcheck(r, "nvjpegGetProperty PATCH_LEVEL")
    return "%s.%s.%s" % (major_version, minor_version, patch_level)

def get_type() -> str:
    return "nvjpeg"

def get_encodings():
    return ("jpeg", )

def get_info():
    return {"version"   : get_version()}

def init_module():
    log("nvjpeg.init_module() version=%s", get_version())

def cleanup_module():
    log("nvjpeg.cleanup_module()")

def get_input_colorspaces(encoding):
    assert encoding=="jpeg"
    return ("BGR", "RGB")

def get_output_colorspaces(encoding, input_colorspace):
    assert encoding in get_encodings()
    assert input_colorspace in get_input_colorspaces(encoding)
    return (input_colorspace, input_colorspace+"X")

def get_spec(encoding, colorspace):
    assert encoding=="jpeg"
    assert colorspace in get_input_colorspaces(encoding)
    from xpra.codecs.codec_constants import video_spec
    return video_spec("jpeg", input_colorspace=colorspace, output_colorspaces=(colorspace, colorspace+"X"), has_lossless_mode=False,
                      codec_class=Encoder, codec_type="jpeg",
                      setup_cost=0, cpu_cost=100, gpu_cost=0,
                      min_w=16, min_h=16, max_w=16*1024, max_h=16*1024,
                      can_scale=False,
                      score_boost=-50)


cdef class Encoder:
    cdef int width
    cdef int height
    cdef object scaling
    cdef object src_format
    cdef int quality
    cdef int speed
    cdef long frames
    cdef nvjpegHandle_t nv_handle
    cdef nvjpegEncoderState_t nv_enc_state
    cdef nvjpegEncoderParams_t nv_enc_params
    cdef nvjpegImage_t nv_image
    cdef object cuda_buffer
    cdef int cuda_stride
    cdef cudaStream_t stream
    cdef object __weakref__

    def __init__(self):
        self.width = self.height = self.quality = self.speed = self.frames = 0

    def init_context(self, device_context, width : int, height : int,
                     src_format, dst_formats, encoding, quality : int, speed : int, scaling, options : typedict):
        assert encoding=="jpeg"
        assert src_format in get_input_colorspaces(encoding)
        assert scaling==(1, 1)
        self.width = width
        self.height = height
        self.src_format = src_format
        self.quality = quality
        self.speed = speed
        self.scaling = scaling
        self.init_nvjpeg()
        self.init_cuda(device_context)

    def init_nvjpeg(self):
        # initialize nvjpeg structures
        errcheck(nvjpegCreateSimple(&self.nv_handle), "nvjpegCreateSimple")
        errcheck(nvjpegEncoderStateCreate(self.nv_handle, &self.nv_enc_state, self.stream), "nvjpegEncoderStateCreate")
        errcheck(nvjpegEncoderParamsCreate(self.nv_handle, &self.nv_enc_params, self.stream), "nvjpegEncoderParamsCreate")
        cdef nvjpegChromaSubsampling_t subsampling = get_subsampling(self.quality)
        cdef int r
        r = nvjpegEncoderParamsSetSamplingFactors(self.nv_enc_params, subsampling, self.stream)
        errcheck(r, "nvjpegEncoderParamsSetSamplingFactors %i (%s)",
                 <const nvjpegChromaSubsampling_t> subsampling, CSS_STR.get(subsampling, "invalid"))
        r = nvjpegEncoderParamsSetQuality(self.nv_enc_params, self.quality, self.stream)
        errcheck(r, "nvjpegEncoderParamsSetQuality %i", self.quality)
        cdef int huffman = int(self.speed<80)
        r = nvjpegEncoderParamsSetOptimizedHuffman(self.nv_enc_params, huffman, self.stream)
        errcheck(r, "nvjpegEncoderParamsSetOptimizedHuffman %i", huffman)
        log("init_nvjpeg() nv_handle=%#x, nv_enc_state=%#x, nv_enc_params=%#x",
            <uintptr_t> self.nv_handle, <uintptr_t> self.nv_enc_state, <uintptr_t> self.nv_enc_params)
        cdef nvjpegJpegEncoding_t encoding_type = NVJPEG_ENCODING_BASELINE_DCT
        #NVJPEG_ENCODING_EXTENDED_SEQUENTIAL_DCT_HUFFMAN
        #NVJPEG_ENCODING_PROGRESSIVE_DCT_HUFFMAN
        r = nvjpegEncoderParamsSetEncoding(self.nv_enc_params, encoding_type, self.stream)
        errcheck(r, "nvjpegEncoderParamsSetEncoding %i (%s)", encoding_type, ENCODING_STR.get(encoding_type, "invalid"))
        log("init_nvjpeg() quality=%s, huffman=%s, subsampling=%s, encoding type=%s",
            self.quality, huffman, CSS_STR.get(subsampling, "invalid"), ENCODING_STR.get(encoding_type, "invalid"))

    def init_cuda(self, device_context):
        stride = self.width*4
        with device_context:
            self.cuda_buffer, self.cuda_stride = driver.mem_alloc_pitch(stride, self.height, 4)

    def is_ready(self):
        return self.nv_handle!=NULL

    def is_closed(self):
        return self.nv_handle==NULL

    def clean(self):
        self.clean_cuda()
        self.clean_nvjpeg()

    def clean_nvjpeg(self):
        log("nvjpeg.clean()")
        self.width = self.height = self.quality = self.speed = 0
        cdef int r
        r = nvjpegEncoderParamsDestroy(self.nv_enc_params)
        errcheck(r, "nvjpegEncoderParamsDestroy %#x", <uintptr_t> self.nv_enc_params)
        r = nvjpegEncoderStateDestroy(self.nv_enc_state)
        errcheck(r, "nvjpegEncoderStateDestroy")
        r = nvjpegDestroy(self.nv_handle)
        errcheck(r, "nvjpegDestroy")
        self.nv_handle = NULL

    def clean_cuda(self):
        self.cuda_buffer = None
        self.cuda_stride = 0

    def get_encoding(self):
        return "jpeg"

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_cuda_stride(self):
        return self.cuda_stride

    def get_type(self):
        return "nvjpeg"

    def get_src_format(self):
        return self.src_format

    def get_info(self) -> dict:
        info = get_info()
        info.update({
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "speed"         : self.speed,
            "quality"       : self.quality,
            })
        return info

    def compress_image(self, device_context, image, int quality=-1, int speed=-1, options=None):
        pfstr = bytestostr(image.get_pixel_format())
        cdef nvjpegInputFormat_t input_format = FORMAT_VAL.get(pfstr, 0)
        if input_format==0:
            raise ValueError("unsupported input format %s" % pfstr)
        cdef int width, height
        cdef double start, end
        with device_context:
            self.upload_image(image)
            width = image.get_width()
            height = image.get_height()
            start = monotonic()
            r = nvjpegEncodeImage(self.nv_handle, self.nv_enc_state, self.nv_enc_params,
                                  &self.nv_image, input_format, width, height, self.stream)
            errcheck(r, "nvjpegEncodeImage")
            end = monotonic()
            log("nvjpegEncodeImage took %.1fms using input format %s",
                1000*(end-start), NVJPEG_INPUT_STR.get(input_format, input_format))
            self.frames += 1
            return memoryview(self.download_bitstream()), {}

    def download_bitstream(self):
        #r = cudaStreamSynchronize(stream)
        #if not r:
        #    raise Exception("nvjpeg failed to synchronize cuda stream: %i" % r)
        # get compressed stream size
        start = monotonic()
        cdef size_t length
        r = nvjpegEncodeRetrieveBitstream(self.nv_handle, self.nv_enc_state, NULL, &length, self.stream)
        errcheck(r, "nvjpegEncodeRetrieveBitstream")
        # get stream itself
        #log("allocating %i bytes for bitstream", length)
        cdef MemBuf output_buf = getbuf(length)
        cdef unsigned char* ptr = <unsigned char*> output_buf.get_mem()
        r = nvjpegEncodeRetrieveBitstream(self.nv_handle, self.nv_enc_state, ptr, &length, NULL)
        errcheck(r, "nvjpegEncodeRetrieveBitstream")
        end = monotonic()
        log("downloaded %i bytes in %.1fms", length, 1000*(end-start))
        return output_buf

    cdef upload_image(self, image):
        #from xpra.codecs.argb.argb import argb_swap
        #argb_swap(image, ("RGB", ))
        cdef double start = monotonic()
        cdef int height = image.get_height()
        cdef int stride = image.get_rowstride()
        log("upload_image(%s) wanted stride %i got %i", image, stride, self.cuda_stride)
        if self.cuda_stride>stride:
            assert image.restride(self.cuda_stride), "failed to restride %s for compression" % image
            stride = self.cuda_stride
        pixels = image.get_pixels()
        cdef Py_ssize_t buf_len = len(pixels)
        if buf_len<stride*height:
            pfstr = bytestostr(image.get_pixel_format())
            raise ValueError("%s buffer is too small: %i bytes, %ix%i=%i bytes required" % (
                pfstr, buf_len, stride, height, stride*height))
        #log("uploading %i bytes to %#x", buf_len, <uintptr_t> int(self.cuda_buffer))
        driver.memcpy_htod(self.cuda_buffer, pixels)
        cdef double end = monotonic()
        log("uploaded %i bytes to %#x in %.1fms", buf_len, <uintptr_t> int(self.cuda_buffer), 1000*(end-start))
        cdef uintptr_t cuda_ptr = int(self.cuda_buffer)
        #log("cuda_ptr=%#x", cuda_ptr)
        self.nv_image.channel[0] = <unsigned char *> cuda_ptr
        self.nv_image.pitch[0] = stride


class NVJPEG_Exception(Exception):
    pass

def errcheck(int r, fnname="", *args):
    if r:
        fstr = fnname % (args)
        raise NVJPEG_Exception("%s failed: %s" % (fstr, ERR_STRS.get(r, r)))


def compress_file(filename, save_to="./out.jpeg"):
    from PIL import Image
    img = Image.open(filename)
    rgb_format = "RGB"
    img = img.convert(rgb_format)
    w, h = img.size
    stride = w*len(rgb_format)
    data = img.tobytes("raw", img.mode)
    log("data=%i bytes (%s) for %s", len(data), type(data), img.mode)
    log("w=%i, h=%i, stride=%i, size=%i", w, h, stride, stride*h)
    from xpra.codecs.image_wrapper import ImageWrapper
    image = ImageWrapper(0, 0, w, h, data, rgb_format,
                       len(rgb_format)*8, stride, len(rgb_format), ImageWrapper.PACKED, True, None)
    jpeg_data = encode(image)[0]
    with open(save_to, "wb") as f:
        f.write(jpeg_data)

cdef nvjpegChromaSubsampling_t get_subsampling(int quality):
    if quality>=80:
        return NVJPEG_CSS_444
    if quality>=60:
        return NVJPEG_CSS_422
    return NVJPEG_CSS_420


def encode(image, int quality=50, speed=50):
    from xpra.codecs.cuda_common.cuda_context import select_device, cuda_device_context
    cdef double start = monotonic()
    cuda_device_id, cuda_device = select_device()
    if cuda_device_id<0 or not cuda_device:
        raise Exception("failed to select a cuda device")
    log("using device %s", cuda_device)
    cuda_context = cuda_device_context(cuda_device_id, cuda_device)
    cdef double end = monotonic()
    log("device init took %.1fms", 1000*(end-start))
    return device_encode(cuda_context, image, quality, speed)

errors = []
def get_errors():
    global errors
    return errors

def device_encode(device_context, image, int quality=50, speed=50):
    global errors
    pfstr = bytestostr(image.get_pixel_format())
    assert pfstr in ("RGB", "BGR"), "invalid pixel format %s" % pfstr
    options = typedict()
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    cdef int stride = 0
    cdef Encoder encoder
    try:
        encoder = Encoder()
        encoder.init_context(device_context, width, height,
                       pfstr, (pfstr, ),
                       "jpeg", quality, speed, scaling=(1, 1), options=options)
        r = encoder.compress_image(device_context, image, quality, speed, options)
        if not r:
            return None
        cdata, options = r
        if SAVE_TO_FILE:    # pragma: no cover
            filename = "./%s.jpeg" % time()
            with open(filename, "wb") as f:
                f.write(cdata)
            log.info("saved %i bytes to %s", len(cdata), filename)
        stride = encoder.get_cuda_stride()
        return cdata, width, height, stride, options
    except NVJPEG_Exception as e:
        errors.append(str(e))
        return None
    finally:
        encoder.clean()


def selftest(full=False):
    #this is expensive, so don't run it unless "full" is set:
    from xpra.codecs.codec_checks import make_test_image
    for size in (32, 256):
        img = make_test_image("BGR", size, size)
        log("testing with %s", img)
        v = encode(img)
        assert v, "failed to compress test image"
