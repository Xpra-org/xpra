# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict, Iterable, Any
from collections.abc import Sequence
from time import monotonic

from libc.string cimport memset  # pylint: disable=syntax-error
from libc.stdint cimport uintptr_t
from xpra.buffers.membuf cimport getbuf, MemBuf  # pylint: disable=syntax-error
from xpra.buffers.membuf cimport buffer_context
from xpra.codecs.nvidia.nvjpeg.nvjpeg cimport (
    NVJPEG_OUTPUT_RGBI, NVJPEG_OUTPUT_BGRI, NVJPEG_OUTPUT_Y,
    NV_ENC_INPUT_PTR, NV_ENC_OUTPUT_PTR, NV_ENC_REGISTERED_PTR,
    nvjpegStatus_t, nvjpegChromaSubsampling_t, nvjpegOutputFormat_t,
    nvjpegInputFormat_t, nvjpegBackend_t, nvjpegJpegEncoding_t,
    nvjpegImage_t, nvjpegHandle_t,
    nvjpegGetProperty, nvjpegCreateSimple, nvjpegDestroy,
    nvjpegJpegState_t,
    nvjpegJpegStateCreate, nvjpegJpegStateDestroy,
    nvjpegGetImageInfo,
)
from xpra.codecs.nvidia.nvjpeg.common import (
    get_version,
    errcheck, NVJPEG_Exception,
    ERR_STR, CSS_STR,
)
from xpra.codecs.nvidia.cuda.context import get_default_device_context
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger
log = Logger("encoder", "nvjpeg")

#we can import pycuda safely here,
#because importing cuda/context will have imported it with the lock
from pycuda.driver import Memcpy2D, memcpy_dtoh, mem_alloc


DEF NVJPEG_MAX_COMPONENT = 4


#we could easily use ctypes here:
#(this would change from a compile time to runtime failure
# if the library + headers are not present)
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


def get_encodings() -> Sequence[str]:
    return ("jpeg", "jpega")


def get_info() -> Dict[str, Any]:
    info = {"version"   : get_version()}
    #if default_device:
    #    info["device"] = default_device.get_info()
    return info


def init_module(options: dict) -> None:
    log("nvjpeg.decoder.init_module(%s) version=%s", options, get_version())
    from xpra.codecs.nvidia.util import has_nvidia_hardware
    if has_nvidia_hardware() is False:
        raise ImportError("no nvidia GPU device found")


def cleanup_module() -> None:
    log("nvjpeg.decoder.cleanup_module()")


class NVJPEG_Exception(Exception):
    pass


def download_from_gpu(buf, size_t size):
    log("nvjpeg download_from_gpu%s", (buf, size))
    start = monotonic()
    cdef MemBuf pixels = getbuf(size, False)
    memcpy_dtoh(pixels, buf)
    end = monotonic()
    log("nvjpeg downloaded %i bytes in %ims", size, 1000*(end-start))
    return pixels


def decompress(rgb_format: str, img_data, options=None) -> ImageWrapper:
    #decompress using the default device,
    #and download the pixel data from the GPU:
    dev = get_default_device_context()
    if not dev:
        raise RuntimeError("no cuda device found")
    with dev as cuda_context:
        log("cuda_context=%s for device=%s", cuda_context, dev.get_info())
        return decompress_and_download(rgb_format, img_data, options)


def decompress_and_download(rgb_format: str, img_data, options=None) -> ImageWrapper:
    img = decompress_with_device(rgb_format, img_data, options)
    cuda_buffer = img.get_pixels()
    pixels = download_from_gpu(cuda_buffer, img.get_rowstride() * img.get_height())
    cuda_buffer.free()
    img.set_pixels(pixels)
    return img


def decompress_with_device(rgb_format: str, img_data, options=None) -> ImageWrapper:
    log("decompress_with_device(%s, %i bytes, %s)", rgb_format, len(img_data), options)
    cdef unsigned int alpha_offset = (options or {}).get("alpha-offset", 0)
    cdef double start, end
    cdef nvjpegHandle_t nv_handle
    cdef nvjpegJpegState_t jpeg_handle
    cdef size_t data_len
    cdef const unsigned char* data_buf
    cdef int[NVJPEG_MAX_COMPONENT] nComponents
    cdef nvjpegChromaSubsampling_t subsampling
    cdef int[NVJPEG_MAX_COMPONENT] widths
    cdef int[NVJPEG_MAX_COMPONENT] heights
    cdef nvjpegOutputFormat_t output_format = NVJPEG_OUTPUT_RGBI
    if rgb_format=="BGR":
        output_format = NVJPEG_OUTPUT_BGRI
    elif rgb_format=="RGB":
        output_format = NVJPEG_OUTPUT_RGBI
    elif rgb_format=="Y":
        output_format = NVJPEG_OUTPUT_Y
    else:
        raise ValueError("invalid rgb format %r" % rgb_format)
    cdef nvjpegImage_t nv_image
    stream = (options or {}).get("stream", None)
    cdef cudaStream_t nv_stream = NULL
    if stream:
        nv_stream = <cudaStream_t> (<uintptr_t> stream.handle)
    cdef nvjpegStatus_t r
    cdef uintptr_t dmem = 0
    cdef int rowstride = 0, width = 0, height = 0

    pixels = None
    try:
        errcheck(nvjpegCreateSimple(&nv_handle), "nvjpegCreateSimple")
        try:
            errcheck(nvjpegJpegStateCreate(nv_handle, &jpeg_handle), "nvjpegJpegStateCreate")
            with buffer_context(img_data) as bc:
                if alpha_offset:
                    #decompress up to alpha data:
                    assert len(bc)>alpha_offset, "invalid alpha offset %i for data length %i" % (alpha_offset, len(bc))
                    data_len = alpha_offset
                else:
                    #decompress everything:
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
                rgb = mem_alloc(rowstride*height)
                dmem = <uintptr_t> int(rgb)
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
                log("nvjpegDecode to %s took %ims", rgb_format, 1000*(end-start))
                pixels = rgb
                if alpha_offset:
                    data_len = len(bc)-alpha_offset
                    data_buf = <const unsigned char*> (<uintptr_t> int(bc) + alpha_offset)
                    errcheck(nvjpegGetImageInfo(nv_handle, data_buf, data_len,
                                                nComponents, &subsampling, widths, heights),
                                                "nvjpegGetImageInfo")
                    log("got image info: %4ix%-4i YUV%s", widths[0], heights[0], CSS_STR.get(subsampling, subsampling))
                    assert width==widths[0] and height==heights[0], "invalid dimensions for alpha channel, expected %ix%i but found %ix%i" % (
                        widths[0], heights[0], width, height,
                        )
                    alpha_size = width*height
                    alpha = mem_alloc(alpha_size)
                    dmem = <uintptr_t> int(alpha)
                    nv_image.pitch[0] = width
                    nv_image.channel[0] = <unsigned char *> dmem
                    start = monotonic()
                    with nogil:
                        r = nvjpegDecode(nv_handle, jpeg_handle,
                                         data_buf, data_len,
                                         NVJPEG_OUTPUT_Y,
                                         &nv_image,
                                         nv_stream)
                    if r:
                        raise NVJPEG_Exception("decoding failed: %s" % ERR_STR.get(r, r))
                    end = monotonic()
                    log("nvjpegDecode to Y took %ims", 1000*(end-start))
                    #combine RGB and A,
                    #start by adding one byte of padding: RGB -> RGBX
                    start = monotonic()
                    rgba = mem_alloc(width*height*4)
                    memcpy = Memcpy2D()
                    memcpy.src_x_in_bytes = memcpy.src_y = 0
                    memcpy.dst_x_in_bytes = memcpy.dst_y = 0
                    memcpy.src_pitch = 3
                    memcpy.dst_pitch = 4
                    memcpy.width_in_bytes = 3
                    memcpy.set_src_device(rgb)
                    memcpy.set_dst_device(rgba)
                    memcpy.height = width*height
                    memcpy(stream)
                    rgb.free()
                    #fill in the alpha channel:
                    memcpy = Memcpy2D()
                    memcpy.src_x_in_bytes = memcpy.src_y = memcpy.dst_y = 0
                    memcpy.dst_x_in_bytes = 3
                    memcpy.src_pitch = 1
                    memcpy.dst_pitch = 4
                    memcpy.width_in_bytes = 1
                    memcpy.set_src_device(alpha)
                    memcpy.set_dst_device(rgba)
                    memcpy.height = alpha_size
                    memcpy(stream)
                    alpha.free()
                    end = monotonic()
                    log("alpha merge took %ims", 1000*(end-start))
                    rowstride = width*4
                    rgb_format += "A"
                    pixels = rgba
        finally:
            errcheck(nvjpegJpegStateDestroy(jpeg_handle), "nvjpegJpegStateDestroy")
    finally:
        errcheck(nvjpegDestroy(nv_handle), "nvjpegDestroy")
    return ImageWrapper(0, 0, width, height, pixels, rgb_format, len(rgb_format)*8, rowstride, planes=len(rgb_format))


def selftest(full=False) -> None:
    from xpra.util.env import envbool
    from xpra.codecs.nvidia.util import has_nvidia_hardware, get_nvidia_module_version
    mod_ver = get_nvidia_module_version()
    if envbool("XPRA_NVJPEG_MODULE_CHECK", True):
        if mod_ver<(522, 6):
            vstr = ".".join(str(x) for x in mod_ver)
            raise ImportError(f"nvidia module {vstr} is too old, version 522.6 or later is required")
        if not has_nvidia_hardware():
            raise ImportError("no nvidia GPU device found")
    from xpra.codecs.checks import TEST_PICTURES
    #options = {"cuda-device-context" : get_device_context()}
    for size, samples in TEST_PICTURES["jpeg"].items():
        for bdata in samples:
            decompress("RGB", bdata)
