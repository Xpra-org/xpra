# This file is part of Xpra.
# Copyright (C) 2021-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from libc.string cimport memset #pylint: disable=syntax-error
from libc.stdint cimport uintptr_t
from xpra.buffers.membuf cimport getbuf, MemBuf #pylint: disable=syntax-error
from xpra.buffers.membuf cimport memalign, buffer_context

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger
log = Logger("encoder", "nvjpeg")


DEF NVJPEG_MAX_COMPONENT = 4

cdef extern from "library_types.h":
    cdef enum libraryPropertyType_t:
        MAJOR_VERSION
        MINOR_VERSION
        PATCH_LEVEL

ctypedef void* cudaStream_t
#cdef extern from "cuda_runtime_api.h":
#    ctypedef int cudaError_t
#    ctypedef void* cudaStream_t
#    cudaError_t cudaStreamCreate(cudaStream_t* pStream)
#    cudaError_t cudaStreamSynchronize(cudaStream_t stream)

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

    ctypedef struct nvjpegDevAllocator_t:
        pass

    ctypedef struct nvjpegPinnedAllocator_t:
        pass

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

    ctypedef struct nvjpegJpegState_t:
        pass
    nvjpegStatus_t nvjpegJpegStateCreate(nvjpegHandle_t handle, nvjpegJpegState_t *jpeg_handle)
    nvjpegStatus_t nvjpegJpegStateDestroy(nvjpegJpegState_t handle)

    nvjpegStatus_t nvjpegGetImageInfo(
        nvjpegHandle_t handle,
        const unsigned char *data,
        size_t length,
        int *nComponents,
        nvjpegChromaSubsampling_t *subsampling,
        int *widths,
        int *heights)

    nvjpegStatus_t nvjpegDecode(nvjpegHandle_t handle, nvjpegJpegState_t jpeg_handle,
                                const unsigned char *data,
                                size_t length,
                                nvjpegOutputFormat_t output_format,
                                nvjpegImage_t *destination,
                                cudaStream_t stream) nogil


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

NVJPEG_OUTPUT_STR = {
    NVJPEG_OUTPUT_UNCHANGED : "UNCHANGED",
    NVJPEG_OUTPUT_YUV       : "YUV",
    NVJPEG_OUTPUT_Y         : "Y",
    NVJPEG_OUTPUT_RGB       : "RGB",
    NVJPEG_OUTPUT_BGR       : "BGR",
    NVJPEG_OUTPUT_RGBI      : "RGBI",
    NVJPEG_OUTPUT_BGRI      : "BGRI",
    #NVJPEG_OUTPUT_FORMAT_MAX
    }


device = None

def get_version():
    cdef int major_version, minor_version, patch_level
    r = nvjpegGetProperty(MAJOR_VERSION, &major_version)
    errcheck(r, "nvjpegGetProperty MAJOR_VERSION")
    r = nvjpegGetProperty(MINOR_VERSION, &minor_version)
    errcheck(r, "nvjpegGetProperty MINOR_VERSION")
    r = nvjpegGetProperty(PATCH_LEVEL, &patch_level)
    errcheck(r, "nvjpegGetProperty PATCH_LEVEL")
    return (major_version, minor_version, patch_level)

def get_type() -> str:
    return "nvjpeg"

def get_encodings():
    return ("jpeg", )   #TODO: "jpega"

def get_info():
    info = {"version"   : get_version()}
    if device:
        info["device"] = device.get_info()
    return info

def init_module():
    log("nvjpeg.decoder.init_module() version=%s", get_version())

def cleanup_module():
    log("nvjpeg.decoder.cleanup_module()")


class NVJPEG_Exception(Exception):
    pass

def errcheck(int r, fnname="", *args):
    if r:
        fstr = fnname % (args)
        raise NVJPEG_Exception("%s failed: %s" % (fstr, ERR_STRS.get(r, r)))


errors = []
def get_errors():
    global errors
    return errors


def decompress(rgb_format, img_data, options=None):
    log("decompress(%s, %i bytes, %s)", rgb_format, len(img_data), options)
    cdef nvjpegHandle_t nv_handle
    cdef nvjpegJpegState_t jpeg_handle
    cdef size_t data_len
    cdef const unsigned char* data_buf
    cdef int[NVJPEG_MAX_COMPONENT] nComponents
    cdef nvjpegChromaSubsampling_t subsampling
    cdef int[NVJPEG_MAX_COMPONENT] widths
    cdef int[NVJPEG_MAX_COMPONENT] heights
    cdef nvjpegOutputFormat_t output_format = NVJPEG_OUTPUT_BGRI
    cdef nvjpegImage_t nv_image
    cdef cudaStream_t nv_stream = NULL
    cdef nvjpegStatus_t r
    cdef unsigned int rowstride = 0, width = 0, height = 0

    pixels = None
    stream = None
    #with dev:
    if True:
        #from pycuda import driver
        #stream = driver.Stream()
        #nv_stream = <void *> stream.handle
        log.info("stream=%s, handle=%#x", stream, <uintptr_t> nv_stream)
        try:
            errcheck(nvjpegCreateSimple(&nv_handle), "nvjpegCreateSimple")
            try:
                errcheck(nvjpegJpegStateCreate(nv_handle, &jpeg_handle), "nvjpegJpegStateCreate")
                with buffer_context(img_data) as bc:
                    data_len = len(bc)
                    data_buf = <const unsigned char*> (<uintptr_t> int(bc))
                    errcheck(nvjpegGetImageInfo(nv_handle, data_buf, data_len,
                                                nComponents, &subsampling, widths, heights),
                                                "nvjpegGetImageInfo")
                    log("got image info: %4ix%-4i YUV%s", widths[0], heights[0], CSS_STR.get(subsampling, subsampling))
                    #    NVJPEG_OUTPUT_STR.get(output_format, output_format), nComponents)
                    width = widths[0]
                    height = heights[0]
                    rowstride = width*3
                    pixels = getbuf(rowstride * height)
                    memset(<void*> pixels.get_mem(), 0, rowstride * height)
                    #initialize image:
                    for i in range(1, NVJPEG_MAX_COMPONENT):
                        nv_image.channel[i] = NULL
                        nv_image.pitch[i] = 0
                    nv_image.pitch[0] = rowstride
                    nv_image.channel[0] = <unsigned char *> pixels.get_mem()
                    start = monotonic()
                    with nogil:
                        r = nvjpegDecode(nv_handle, jpeg_handle,
                                    data_buf, data_len,
                                    output_format,
                                    &nv_image,
                                    nv_stream)
                    if r:
                        raise NVJPEG_Exception("decoding failed: %s" % ERR_STRS.get(r, r))
                    if stream:
                        stream.synchronize()
                    end = monotonic()
                    log.info("nvjpegDecode took %ims", 1000*(end-start))
            finally:
                errcheck(nvjpegJpegStateDestroy(jpeg_handle), "nvjpegJpegStateDestroy")
        finally:
            errcheck(nvjpegDestroy(nv_handle), "nvjpegDestroy")
    return ImageWrapper(0, 0, width, height, memoryview(pixels), "RGB", 24, rowstride, planes=ImageWrapper.PACKED)

def get_device_context():
    from xpra.codecs.cuda_common.cuda_context import select_device, cuda_device_context
    cdef double start = monotonic()
    cuda_device_id, cuda_device = select_device()
    if cuda_device_id<0 or not cuda_device:
        raise Exception("failed to select a cuda device")
    log("using device %s", cuda_device)
    cuda_context = cuda_device_context(cuda_device_id, cuda_device)
    cdef double end = monotonic()
    log("device init took %.1fms", 1000*(end-start))
    return cuda_context

dev = get_device_context()


def selftest(full=False):
    from xpra.codecs.codec_checks import TEST_PICTURES
    #options = {"cuda-device-context" : get_device_context()}
    for hexdata in TEST_PICTURES["jpeg"]:
        import binascii
        bdata = binascii.unhexlify(hexdata)
        decompress("RGB", bdata)
