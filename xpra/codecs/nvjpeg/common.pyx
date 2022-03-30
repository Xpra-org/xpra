# This file is part of Xpra.
# Copyright (C) 2021-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "library_types.h":
    cdef enum libraryPropertyType_t:
        MAJOR_VERSION
        MINOR_VERSION
        PATCH_LEVEL

from xpra.codecs.nvjpeg.nvjpeg cimport (
    NVJPEG_VER_MAJOR, NVJPEG_VER_MINOR, NVJPEG_VER_PATCH, NVJPEG_VER_BUILD,
    #ERR_STR:
    NVJPEG_STATUS_SUCCESS,
    NVJPEG_STATUS_NOT_INITIALIZED,
    NVJPEG_STATUS_INVALID_PARAMETER,
    NVJPEG_STATUS_BAD_JPEG,
    NVJPEG_STATUS_JPEG_NOT_SUPPORTED,
    NVJPEG_STATUS_ALLOCATOR_FAILURE,
    NVJPEG_STATUS_EXECUTION_FAILED,
    NVJPEG_STATUS_ARCH_MISMATCH,
    NVJPEG_STATUS_INTERNAL_ERROR,
    NVJPEG_STATUS_IMPLEMENTATION_NOT_SUPPORTED,
    #CSS_STR:
    NVJPEG_CSS_444,
    NVJPEG_CSS_422,
    NVJPEG_CSS_420,
    NVJPEG_CSS_440,
    NVJPEG_CSS_411,
    NVJPEG_CSS_410,
    NVJPEG_CSS_GRAY,
    NVJPEG_CSS_UNKNOWN,
    #ENCODING_STR:
    NVJPEG_ENCODING_UNKNOWN,
    NVJPEG_ENCODING_BASELINE_DCT,
    NVJPEG_ENCODING_EXTENDED_SEQUENTIAL_DCT_HUFFMAN,
    NVJPEG_ENCODING_PROGRESSIVE_DCT_HUFFMAN,
    #INPUT_STR:
    NVJPEG_INPUT_RGB,
    NVJPEG_INPUT_BGR,
    NVJPEG_INPUT_RGBI,
    NVJPEG_INPUT_BGRI,
    #OUTPUT_STR:
    NVJPEG_OUTPUT_UNCHANGED,
    NVJPEG_OUTPUT_YUV,
    NVJPEG_OUTPUT_Y,
    NVJPEG_OUTPUT_RGB,
    NVJPEG_OUTPUT_BGR,
    NVJPEG_OUTPUT_RGBI,
    NVJPEG_OUTPUT_BGRI,
    NVJPEG_OUTPUT_FORMAT_MAX,
    #get_version:
    nvjpegGetProperty,
    )


class NVJPEG_Exception(Exception):
    pass

def errcheck(int r, fnname="", *args):
    if r:
        fstr = fnname % (args)
        raise NVJPEG_Exception("%s failed: %s" % (fstr, ERR_STR.get(r, r)))


def get_cuda_version():
    cdef int major_version, minor_version, patch_level
    r = nvjpegGetProperty(MAJOR_VERSION, &major_version)
    errcheck(r, "nvjpegGetProperty MAJOR_VERSION")
    r = nvjpegGetProperty(MINOR_VERSION, &minor_version)
    errcheck(r, "nvjpegGetProperty MINOR_VERSION")
    r = nvjpegGetProperty(PATCH_LEVEL, &patch_level)
    errcheck(r, "nvjpegGetProperty PATCH_LEVEL")
    return (major_version, minor_version, patch_level)

def get_version():
    return (NVJPEG_VER_MAJOR, NVJPEG_VER_MINOR, NVJPEG_VER_PATCH, NVJPEG_VER_BUILD)


ERR_STR = {
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
