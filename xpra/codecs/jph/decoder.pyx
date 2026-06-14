# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from typing import Any, Dict, Tuple
from collections.abc import Sequence

from libc.stdint cimport uint8_t, uint32_t, uintptr_t
from libc.stddef cimport size_t
from xpra.buffers.membuf cimport makebuf, MemBuf, buffer_context

from xpra.common import SizedBuffer
from xpra.codecs.debug import may_save_image
from xpra.codecs.image import ImageWrapper
from xpra.util.objects import typedict
from xpra.log import Logger
log = Logger("decoder", "jph")


cdef extern from "jph.h":
    int jph_version_major()
    int jph_version_minor()
    int jph_version_patch()
    int jph_decode(const uint8_t *data, size_t data_size,
                   uint8_t **pixels, size_t *pixels_size,
                   uint32_t *width, uint32_t *height, uint32_t *stride,
                   char *error, size_t error_size) nogil


def get_version() -> Tuple[int, int, int]:
    return jph_version_major(), jph_version_minor(), jph_version_patch()


def get_type() -> str:
    return "jph"


def get_encodings() -> Sequence[str]:
    return ("jph", )


def get_info() -> Dict[str, Any]:
    return {
        "version": get_version(),
        "encodings": get_encodings(),
    }


def decompress(data: SizedBuffer, options: typedict = None) -> ImageWrapper:
    cdef const uint8_t *src
    cdef uint8_t *pixels = NULL
    cdef size_t pixels_size = 0
    cdef uint32_t width = 0
    cdef uint32_t height = 0
    cdef uint32_t stride = 0
    cdef char error[1024]
    error[0] = 0
    cdef int r = 0
    cdef size_t data_size = 0
    with buffer_context(data) as bc:
        src = <const uint8_t*> (<uintptr_t> int(bc))
        data_size = len(bc)
        with nogil:
            r = jph_decode(src, data_size, &pixels, &pixels_size,
                           &width, &height, &stride, error, sizeof(error))
    if r != 0:
        raise RuntimeError("jph decode failed: %s" % error.decode("utf-8", "replace"))
    if pixels == NULL or pixels_size == 0:
        raise RuntimeError("jph decode produced no pixels")
    cdef MemBuf membuf = makebuf(pixels, pixels_size, 1)
    may_save_image("jph", data)
    return ImageWrapper(0, 0, width, height, memoryview(membuf), "BGRX", 24, stride, planes=ImageWrapper.PACKED)


def decompress_to_rgb(data: SizedBuffer, options: typedict = None) -> ImageWrapper:
    return decompress(data, options)


def selftest(full=False) -> None:
    log("jph selftest")
    from xpra.codecs.checks import TEST_PICTURES
    for size, samples in TEST_PICTURES["jph"].items():
        w, h = size
        for data, options in samples:
            img = decompress(data, typedict(options))
            assert img.get_width()==w and img.get_height()==h
            assert len(img.get_pixels())>0
            img.free()
            if full:
                try:
                    v = decompress(data[:len(data)//2], typedict(options))
                except Exception:
                    pass
                else:
                    raise RuntimeError("should not be able to decompress incomplete jph data, but got %s" % v)
