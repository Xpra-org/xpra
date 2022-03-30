# This file is part of Xpra.
# Copyright (C) 2021-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uintptr_t

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
