# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: auto_pickle=False, cdivision=True, language_level=3

from libc.stdint cimport uintptr_t
from xpra.monotonic_time cimport monotonic_time
from xpra.buffers.membuf cimport getbuf, MemBuf, object_as_buffer #pylint: disable=syntax-error

from pycuda import driver

from xpra.os_util import bytestostr
from xpra.codecs.cuda_common.cuda_context import (
    select_device,
    )

from xpra.log import Logger
log = Logger("encoder", "nvjpeg")


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
        # return luma component only, if YCbCr colorspace, 
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


def errcheck(int r, fnname="", *args):
    if r:
        fstr = fnname % (args)
        raise Exception("%s failed: %s" % (fstr, ERR_STRS.get(r, r)))


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
    if quality>=60:
        return NVJPEG_CSS_444
    if quality>=30:
        return NVJPEG_CSS_422
    return NVJPEG_CSS_420


def encode(image, int quality=50, speed=50):
    cdef double start = monotonic_time()
    cuda_device_id, cuda_device = select_device()
    if cuda_device_id<0 or not cuda_device:
        raise Exception("failed to select a cuda device")
    log("using device %s", cuda_device)
    cuda_ctx = cuda_device.make_context(flags=driver.ctx_flags.SCHED_AUTO | driver.ctx_flags.MAP_HOST)
    cdef double end = monotonic_time()
    log("device init took %.1fms", 1000*(end-start))
    try:
        return device_encode(cuda_device, image, quality, speed)
    finally:
        cuda_ctx.pop()

def device_encode(device, image, int quality=50, speed=50):
    cdef nvjpegHandle_t nv_handle = NULL
    cdef nvjpegEncoderState_t nv_enc_state = NULL
    cdef nvjpegEncoderParams_t nv_enc_params = NULL
    cdef cudaStream_t stream = NULL
    cdef int r
    #r = cudaStreamCreate(&stream)
    #    raise Exception("failed to create CUDA stream: %i" % r)
    #if r:
    # initialize nvjpeg structures
    errcheck(nvjpegCreateSimple(&nv_handle), "nvjpegCreateSimple")
    errcheck(nvjpegEncoderStateCreate(nv_handle, &nv_enc_state, stream), "nvjpegEncoderStateCreate")
    errcheck(nvjpegEncoderParamsCreate(nv_handle, &nv_enc_params, stream), "nvjpegEncoderParamsCreate")
    cdef nvjpegChromaSubsampling_t subsampling = get_subsampling(quality)
    r = nvjpegEncoderParamsSetSamplingFactors(nv_enc_params, subsampling, stream)
    errcheck(r, "nvjpegEncoderParamsSetSamplingFactors %i (%s)", <const nvjpegChromaSubsampling_t> subsampling, CSS_STR.get(subsampling, "invalid"))
    r = nvjpegEncoderParamsSetQuality(nv_enc_params, quality, stream)
    errcheck(r, "nvjpegEncoderParamsSetQuality %i", quality)
    cdef int huffman = int(speed<80)
    r = nvjpegEncoderParamsSetOptimizedHuffman(nv_enc_params, huffman, stream)
    errcheck(r, "nvjpegEncoderParamsSetOptimizedHuffman %i", huffman)
    log("compress(%s) nv_handle=%#x, nv_enc_state=%#x, nv_enc_params=%#x",
        image, <uintptr_t> nv_handle, <uintptr_t> nv_enc_state, <uintptr_t> nv_enc_params)
    encoding_type = NVJPEG_ENCODING_BASELINE_DCT
    #encoding_type = NVJPEG_ENCODING_EXTENDED_SEQUENTIAL_DCT_HUFFMAN
    #encoding_type = NVJPEG_ENCODING_PROGRESSIVE_DCT_HUFFMAN
    r = nvjpegEncoderParamsSetEncoding(nv_enc_params, encoding_type, stream)
    errcheck(r, "nvjpegEncoderParamsSetEncoding %i (%s)", encoding_type, ENCODING_STR.get(encoding_type, "invalid"))

    cdef int width = image.get_width()
    cdef int height = image.get_height()
    cdef int stride = image.get_rowstride()

    cdef double start = monotonic_time()
    cuda_buffer, buf_stride = driver.mem_alloc_pitch(stride, height, 4)
    log("wanted stride %i got %i", stride, buf_stride)
    if buf_stride>stride:
        assert image.restride(buf_stride), "failed to restride %s for compression" % image
        stride = buf_stride
        log("done restride")

    cdef nvjpegImage_t nv_image
    pixels = image.get_pixels()
    pfstr = bytestostr(image.get_pixel_format())
    #pfstr = bytestostr(image.get_pixel_format())
    cdef const unsigned char* buf
    cdef Py_ssize_t buf_len
    assert object_as_buffer(pixels, <const void**> &buf, &buf_len)==0, "unable to convert %s to a buffer" % type(pixels)
    assert buf_len>=stride*height, "%s buffer is too small: %i bytes, %ix%i=%i bytes required" % (pfstr, buf_len, stride, height, stride*height)
    cdef double end = monotonic_time()
    log("prepared in %.1fms", 1000*(end-start))

    start = monotonic_time()
    log("uploading %i bytes to %#x", buf_len, <uintptr_t> int(cuda_buffer))
    driver.memcpy_htod(cuda_buffer, pixels)
    #nv_image.channel[0] = <unsigned char*> buf
    cdef uintptr_t cuda_ptr = int(cuda_buffer)
    log("cuda_ptr=%#x", cuda_ptr)
    nv_image.channel[0] = <unsigned char *> cuda_ptr
    nv_image.pitch[0] = buf_stride
    log("calling nvjpegEncodeImage")
    r = nvjpegEncodeImage(nv_handle, nv_enc_state, nv_enc_params,
                          &nv_image, NVJPEG_INPUT_RGBI, width, height, stream)
    errcheck(r, "nvjpegEncodeImage image=%s, buffer stride=%s, cuda_ptr=%#x",
             image, buf_stride, cuda_ptr)
    #r = cudaStreamSynchronize(stream)
    #if not r:
    #    raise Exception("nvjpeg failed to synchronize cuda stream: %i" % r)
    # get compressed stream size
    log("retrieving bitstream size")
    cdef size_t length
    r = nvjpegEncodeRetrieveBitstream(nv_handle, nv_enc_state, NULL, &length, stream)
    errcheck(r, "nvjpegEncodeRetrieveBitstream")
    # get stream itself
    log("allocating %i bytes", length)
    cdef MemBuf output_buf = getbuf(length)
    cdef unsigned char* ptr = <unsigned char*> output_buf.get_mem()
    log("downloading compressed data")
    r = nvjpegEncodeRetrieveBitstream(nv_handle, nv_enc_state, ptr, &length, NULL)
    log("cleaning up")
    errcheck(r, "nvjpegEncodeRetrieveBitstream")
    r = nvjpegEncoderParamsDestroy(nv_enc_params)
    errcheck(r, "nvjpegEncoderParamsDestroy %#x", <uintptr_t> nv_enc_params)
    r = nvjpegEncoderStateDestroy(nv_enc_state)
    errcheck(r, "nvjpegEncoderStateDestroy")
    end = monotonic_time()
    log("got %i bytes in %.1fms", length, 1000*(end-start))
    return memoryview(output_buf), width, height, stride

def init_module():
    log("nvjpeg.init_module() version=%s", get_version())

def cleanup_module():
    log("nvjpeg.cleanup_module()")

def selftest(full=False):
    #this is expensive, so don't run it unless "full" is set:
    from xpra.codecs.codec_checks import make_test_image
    for size in (32, 256):
        img = make_test_image("BGRA", size, size)
        log("testing with %s", img)
        v = encode(img)
        assert v, "failed to compress test image"
