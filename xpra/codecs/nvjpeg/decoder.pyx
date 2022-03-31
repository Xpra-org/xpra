# This file is part of Xpra.
# Copyright (C) 2021-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from pycuda import driver

from libc.string cimport memset #pylint: disable=syntax-error
from libc.stdint cimport uintptr_t
from xpra.buffers.membuf cimport getbuf, MemBuf #pylint: disable=syntax-error
from xpra.buffers.membuf cimport memalign, buffer_context
from xpra.codecs.nvjpeg.nvjpeg cimport (
    NVJPEG_OUTPUT_RGBI,
    NV_ENC_INPUT_PTR, NV_ENC_OUTPUT_PTR, NV_ENC_REGISTERED_PTR,
    nvjpegStatus_t, nvjpegChromaSubsampling_t, nvjpegOutputFormat_t,
    nvjpegInputFormat_t, nvjpegBackend_t, nvjpegJpegEncoding_t,
    nvjpegImage_t, nvjpegHandle_t,
    nvjpegGetProperty, nvjpegCreateSimple, nvjpegDestroy,
    nvjpegJpegState_t,
    nvjpegJpegStateCreate, nvjpegJpegStateDestroy,
    nvjpegGetImageInfo,
    )
from xpra.codecs.nvjpeg.common import (
    get_version,
    errcheck, NVJPEG_Exception,
    ERR_STR, CSS_STR,
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

cdef extern from "nvjpeg.h":
    ctypedef void* cudaStream_t
    nvjpegStatus_t nvjpegDecode(nvjpegHandle_t handle, nvjpegJpegState_t jpeg_handle,
                                const unsigned char *data,
                                size_t length,
                                nvjpegOutputFormat_t output_format,
                                nvjpegImage_t *destination,
                                cudaStream_t stream) nogil



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
    cdef nvjpegOutputFormat_t output_format = NVJPEG_OUTPUT_RGBI
    cdef nvjpegImage_t nv_image
    cdef cudaStream_t nv_stream = NULL
    cdef nvjpegStatus_t r
    cdef uintptr_t dmem
    cdef unsigned int rowstride = 0, width = 0, height = 0

    buf = None
    with device:
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
                    width = widths[0]
                    height = heights[0]
                    rowstride = width*3
                    for i in range(1, NVJPEG_MAX_COMPONENT):
                        nv_image.channel[i] = NULL
                        nv_image.pitch[i] = 0
                    nv_image.pitch[0] = rowstride
                    buf = driver.mem_alloc(rowstride * height)
                    dmem = <uintptr_t> int(buf)
                    nv_image.channel[0] = <unsigned char *> dmem
                    start = monotonic()
                    with nogil:
                        r = nvjpegDecode(nv_handle, jpeg_handle,
                                    data_buf, data_len,
                                    output_format,
                                    &nv_image,
                                    nv_stream)
                    if r:
                        raise NVJPEG_Exception("decoding failed: %s" % ERR_STR.get(r, r))
                    end = monotonic()
                    log("nvjpegDecode took %ims", 1000*(end-start))
                start = monotonic()
                pixels = bytearray(rowstride * height)
                driver.memcpy_dtoh(pixels, buf)
                end = monotonic()
                log("nvjpeg downloaded %i bytes in %ims", rowstride * height, 1000*(end-start))
            finally:
                if buf:
                    buf.free()
                errcheck(nvjpegJpegStateDestroy(jpeg_handle), "nvjpegJpegStateDestroy")
        finally:
            errcheck(nvjpegDestroy(nv_handle), "nvjpegDestroy")
    return ImageWrapper(0, 0, width, height, pixels, "RGB", 24, rowstride, planes=ImageWrapper.PACKED)

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

device = get_device_context()


def selftest(full=False):
    from xpra.codecs.codec_checks import TEST_PICTURES
    #options = {"cuda-device-context" : get_device_context()}
    for hexdata in TEST_PICTURES["jpeg"]:
        import binascii
        bdata = binascii.unhexlify(hexdata)
        decompress("RGB", bdata)
