# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from libc.stdint cimport uint8_t, uint32_t, uintptr_t
from libc.stddef cimport size_t
from xpra.buffers.membuf cimport makebuf, MemBuf, buffer_context

from xpra.codecs.constants import is_video_content
from xpra.codecs.debug import may_save_image
from xpra.codecs.image import ImageWrapper
from xpra.net.compression import Compressed
from xpra.util.objects import typedict
from xpra.log import Logger
log = Logger("encoder", "jph")


cdef extern from "jph.h":
    int jph_version_major()
    int jph_version_minor()
    int jph_version_patch()
    int jph_encode(const uint8_t *pixels,
                   uint32_t width, uint32_t height, uint32_t stride,
                   int bytes_per_pixel, int r_offset, int g_offset, int b_offset,
                   int quality, int continuous_tone,
                   uint8_t **out, size_t *out_size,
                   char *error, size_t error_size) nogil


INPUT_FORMATS: Dict[str, Tuple[int, int, int, int]] = {
    "RGB": (3, 0, 1, 2),
    "BGR": (3, 2, 1, 0),
    "RGBX": (4, 0, 1, 2),
    "RGBA": (4, 0, 1, 2),
    "BGRX": (4, 2, 1, 0),
    "BGRA": (4, 2, 1, 0),
    "XRGB": (4, 1, 2, 3),
    "ARGB": (4, 1, 2, 3),
    "XBGR": (4, 3, 2, 1),
    "ABGR": (4, 3, 2, 1),
}


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


cdef tuple do_encode(object image, object options):
    cdef int width = image.get_width()
    cdef int height = image.get_height()
    cdef int scaled_width = options.intget("scaled-width", width)
    cdef int scaled_height = options.intget("scaled-height", height)
    if scaled_width != width or scaled_height != height:
        from xpra.codecs.argb.scale import scale_image
        image = scale_image(image, scaled_width, scaled_height)
        width = scaled_width
        height = scaled_height

    pixel_format = image.get_pixel_format()
    if pixel_format not in INPUT_FORMATS:
        from xpra.codecs.argb.argb import argb_swap
        if not argb_swap(image, tuple(INPUT_FORMATS)):
            raise ValueError(f"jph cannot handle pixel format {pixel_format!r}")
        pixel_format = image.get_pixel_format()
    offsets = INPUT_FORMATS[pixel_format]
    cdef int bpp = offsets[0]
    cdef int ro = offsets[1]
    cdef int go = offsets[2]
    cdef int bo = offsets[3]

    cdef uint8_t *out = NULL
    cdef size_t out_size = 0
    cdef char error[1024]
    error[0] = 0
    cdef int r = 0
    cdef const uint8_t *src
    cdef uint32_t stride = image.get_rowstride()
    cdef int quality = options.intget("quality", 100)
    #photographs and video frames need a finer quantiser than screen content
    #to reach the same quality - a window we have not identified is treated
    #as screen content, which is what it usually is:
    cdef int continuous_tone = is_video_content(options.strtupleget("content-types", ()))
    pixels = image.get_pixels()
    with buffer_context(pixels) as bc:
        if len(bc) < stride * height:
            raise ValueError(f"{pixel_format} buffer is too small: {len(bc)} bytes, need {stride * height}")
        src = <const uint8_t*> (<uintptr_t> int(bc))
        with nogil:
            r = jph_encode(src, width, height, stride, bpp, ro, go, bo, quality, continuous_tone,
                           &out, &out_size, error, sizeof(error))
    if r != 0:
        raise RuntimeError("jph encode failed: %s" % error.decode("utf-8", "replace"))
    if out == NULL or out_size == 0:
        raise RuntimeError("jph encode produced no data")
    cdef MemBuf cdata = makebuf(out, out_size, 1)
    may_save_image("jph", cdata, monotonic())
    return cdata, {
        "quality": quality,
    }, width, height


def encode(coding: str, image: ImageWrapper, options=None) -> Tuple:
    assert coding == "jph"
    cdata, client_options, width, height = do_encode(image, typedict(options or {}))
    return "jph", Compressed("jph", memoryview(cdata), False), client_options, width, height, 0, 24


def selftest(full=False) -> None:
    from xpra.codecs.checks import make_test_image
    img = make_test_image("BGRX", 32, 32)
    r = encode("jph", img, typedict({"quality": 100}))
    assert r and len(r[1].data) > 0
