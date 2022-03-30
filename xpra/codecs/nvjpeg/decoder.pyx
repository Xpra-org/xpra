# This file is part of Xpra.
# Copyright (C) 2021-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from libc.string cimport memset #pylint: disable=syntax-error
from libc.stdint cimport uintptr_t
from xpra.buffers.membuf cimport getbuf, MemBuf #pylint: disable=syntax-error
from xpra.buffers.membuf cimport memalign, buffer_context
from xpra.codecs.nvjpeg.nvjpeg cimport (
    NVJPEG_VER_MAJOR, NVJPEG_VER_MINOR, NVJPEG_VER_PATCH, NVJPEG_VER_BUILD,
    NVJPEG_OUTPUT_BGRI,
    NV_ENC_INPUT_PTR, NV_ENC_OUTPUT_PTR, NV_ENC_REGISTERED_PTR,
    nvjpegStatus_t, nvjpegChromaSubsampling_t, nvjpegOutputFormat_t,
    nvjpegInputFormat_t, nvjpegBackend_t, nvjpegJpegEncoding_t,
    nvjpegImage_t, nvjpegHandle_t,
    nvjpegGetProperty, nvjpegCreateSimple, nvjpegDestroy,
    nvjpegJpegState_t,
    nvjpegJpegStateCreate, nvjpegJpegStateDestroy,
    nvjpegGetImageInfo,
    ERR_STRS, CSS_STR, ENCODING_STR, NVJPEG_OUTPUT_STR,
    )

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

    nvjpegStatus_t nvjpegDecode(nvjpegHandle_t handle, nvjpegJpegState_t jpeg_handle,
                                const unsigned char *data,
                                size_t length,
                                nvjpegOutputFormat_t output_format,
                                nvjpegImage_t *destination,
                                cudaStream_t stream) nogil


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
