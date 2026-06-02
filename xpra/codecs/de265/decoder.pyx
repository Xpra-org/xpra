# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec
from xpra.util.env import envint
from xpra.util.objects import typedict
from xpra.common import SizedBuffer
from xpra.codecs.image import ImageWrapper, PlanarFormat
from xpra.log import Logger

log = Logger("decoder", "de265")

from libc.stdint cimport int64_t, uint8_t, uintptr_t
from cpython.bytes cimport PyBytes_FromStringAndSize
from xpra.buffers.membuf cimport buffer_context  # pylint: disable=syntax-error

THREADS = envint("XPRA_DE265_THREADS", 0)


cdef extern from "libde265/de265.h":
    ctypedef int64_t de265_PTS

    ctypedef enum de265_error:
        DE265_OK
        DE265_ERROR_OUT_OF_MEMORY
        DE265_ERROR_IMAGE_BUFFER_FULL
        DE265_ERROR_WAITING_FOR_INPUT_DATA

    const char *de265_get_error_text(de265_error err)
    int de265_isOK(de265_error err)

    const char *de265_get_version()
    int de265_get_version_number_major()
    int de265_get_version_number_minor()
    int de265_get_version_number_maintenance()

    cdef struct de265_image:
        pass

    cdef enum de265_chroma:
        de265_chroma_mono
        de265_chroma_420
        de265_chroma_422
        de265_chroma_444

    int de265_get_image_width(const de265_image *, int channel)
    int de265_get_image_height(const de265_image *, int channel)
    de265_chroma de265_get_chroma_format(const de265_image *)
    int de265_get_bits_per_pixel(const de265_image *, int channel)
    const uint8_t *de265_get_image_plane(const de265_image *, int channel, int *out_stride)
    int de265_get_image_full_range_flag(const de265_image *)

    ctypedef void de265_decoder_context

    de265_decoder_context *de265_new_decoder()
    de265_error de265_free_decoder(de265_decoder_context *)
    de265_error de265_start_worker_threads(de265_decoder_context *, int number_of_threads)
    de265_error de265_push_data(de265_decoder_context *, const void *data, int length,
                                de265_PTS pts, void *user_data)
    void de265_push_end_of_frame(de265_decoder_context *)
    de265_error de265_flush_data(de265_decoder_context *)
    de265_error de265_decode(de265_decoder_context *, int *more) nogil
    const de265_image *de265_get_next_picture(de265_decoder_context *)
    void de265_release_next_picture(de265_decoder_context *)
    void de265_reset(de265_decoder_context *)


COLORSPACES: Sequence[str] = ("YUV444P", "YUV422P", "YUV420P")
CHROMA_TO_PIXEL_FORMAT: dict[int, str] = {
    de265_chroma_420: "YUV420P",
    de265_chroma_422: "YUV422P",
    de265_chroma_444: "YUV444P",
}

MAX_WIDTH, MAX_HEIGHT = (8192, 4096)


cdef inline str error_text(de265_error err):
    return de265_get_error_text(err).decode("latin1")


cdef int check(de265_error err, str action) except -1:
    if de265_isOK(err):
        return 0
    if err == DE265_ERROR_OUT_OF_MEMORY:
        raise MemoryError(f"libde265 {action} failed: {error_text(err)}")
    raise RuntimeError(f"libde265 {action} failed: {error_text(err)}")


def get_version() -> Tuple[int, int, int]:
    return (
        de265_get_version_number_major(),
        de265_get_version_number_minor(),
        de265_get_version_number_maintenance(),
    )


def get_type() -> str:
    return "de265"


def get_info() -> Dict[str, Any]:
    return {
        "version": get_version(),
        "version-string": de265_get_version().decode("latin1"),
    }


def get_encodings() -> Sequence[str]:
    return ("h265", )


def get_min_size(_encoding: str) -> Tuple[int, int]:
    return 32, 32


def get_specs() -> Sequence[VideoSpec]:
    specs = []
    for colorspace in COLORSPACES:
        specs.append(VideoSpec(
            encoding="h265", input_colorspace=colorspace, output_colorspaces=(colorspace, ),
            has_lossless_mode=colorspace == "YUV444P",
            codec_class=Decoder, codec_type=get_type(),
            quality=40, speed=20,
            size_efficiency=40,
            setup_cost=0, width_mask=0xFFFE, height_mask=0xFFFE,
            max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
        ))
    return specs


cdef class Decoder:
    cdef de265_decoder_context *context
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object colorspace

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("de265.init_context%s", (encoding, width, height, colorspace, options))
        assert encoding == "h265", f"invalid encoding: {encoding}"
        if colorspace not in COLORSPACES:
            raise ValueError(f"invalid colorspace: {colorspace!r}, expected one of {COLORSPACES}")
        self.width = width
        self.height = height
        self.colorspace = colorspace
        self.frames = 0
        self.context = de265_new_decoder()
        if self.context == NULL:
            raise RuntimeError("failed to create libde265 decoder")
        threads = options.intget("threads", THREADS)
        if threads > 0:
            check(de265_start_worker_threads(self.context, threads), "start worker threads")

    def get_encoding(self) -> str:
        return "h265"

    def get_colorspace(self) -> str:
        return self.colorspace

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return self.context == NULL

    def get_type(self) -> str:
        return "de265"

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        log("de265 close context %#x", <uintptr_t> self.context)
        cdef de265_error r
        if self.context != NULL:
            r = de265_free_decoder(self.context)
            if not de265_isOK(r):
                log.error("Error freeing libde265 decoder: %s", error_text(r))
            self.context = NULL
        self.frames = 0
        self.width = 0
        self.height = 0
        self.colorspace = ""

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "colorspace"    : self.colorspace,
        }
        return info

    def decompress_image(self, data: SizedBuffer, options: typedict) -> ImageWrapper:
        log("de265.decompress_image(%i bytes, %s)", len(data), options)
        assert self.context != NULL
        cdef double start = monotonic()
        cdef const uint8_t *src
        cdef Py_ssize_t src_len
        cdef de265_error r
        with buffer_context(data) as bc:
            src = <const uint8_t*> (<uintptr_t> int(bc))
            src_len = len(bc)
            if src_len > 0x7fffffff:
                raise ValueError(f"frame data is too large: {src_len} bytes")
            r = de265_push_data(self.context, <const void *> src, <int> src_len, self.frames, NULL)
        check(r, "push data")
        de265_push_end_of_frame(self.context)

        cdef int more = 1
        cdef int decode_runs = 0
        cdef const de265_image *image = NULL
        while image == NULL:
            with nogil:
                r = de265_decode(self.context, &more)
            decode_runs += 1
            if not de265_isOK(r):
                if r == DE265_ERROR_WAITING_FOR_INPUT_DATA:
                    break
                if r == DE265_ERROR_IMAGE_BUFFER_FULL:
                    image = de265_get_next_picture(self.context)
                    if image != NULL:
                        break
                check(r, "decode")
            image = de265_get_next_picture(self.context)
            if image != NULL:
                break
            if not more:
                break
            if decode_runs > 64:
                raise RuntimeError("libde265 decode did not produce a picture")

        if image == NULL and options.intget("delayed", 0) > 0:
            log("libde265 did not return a decoded picture, delayed=%i", options.intget("delayed", 0))
            return None
        if image == NULL:
            raise RuntimeError("libde265 did not return a decoded picture")

        try:
            return self.make_image_wrapper(image, options, src_len, start)
        finally:
            de265_release_next_picture(self.context)

    cdef object make_image_wrapper(self, const de265_image *image, object options,
                                   Py_ssize_t src_len, double start):
        cdef de265_chroma chroma = de265_get_chroma_format(image)
        pixel_format = CHROMA_TO_PIXEL_FORMAT.get(chroma)
        if not pixel_format:
            raise RuntimeError(f"unsupported libde265 chroma format: {int(chroma)}")

        cdef int bpp
        cdef int plane_width
        cdef int plane_height
        cdef int stride
        cdef const uint8_t *plane
        pyplanes = []
        pystrides = []
        for i in range(3):
            bpp = de265_get_bits_per_pixel(image, i)
            if bpp != 8:
                raise RuntimeError(f"unsupported libde265 plane {i} depth: {bpp}")
            plane_width = de265_get_image_width(image, i)
            plane_height = de265_get_image_height(image, i)
            if plane_width <= 0 or plane_height <= 0:
                raise RuntimeError(f"invalid libde265 plane {i} size: {plane_width}x{plane_height}")
            plane = de265_get_image_plane(image, i, &stride)
            if plane == NULL:
                raise RuntimeError(f"missing libde265 plane {i}")
            if stride < plane_width:
                raise RuntimeError(f"invalid libde265 plane {i} stride: {stride} < {plane_width}")
            pystrides.append(stride)
            pyplanes.append(PyBytes_FromStringAndSize(<const char *> plane, stride * plane_height))

        if de265_get_image_width(image, 0) < self.width or de265_get_image_height(image, 0) < self.height:
            raise RuntimeError("decoded image is smaller than expected: "
                               f"{de265_get_image_width(image, 0)}x{de265_get_image_height(image, 0)} "
                               f"instead of {self.width}x{self.height}")

        self.frames += 1
        self.colorspace = pixel_format
        cdef double elapsed = 1000 * (monotonic() - start)
        log("de265 decoded %i bytes into %ix%i %s in %ims",
            src_len, self.width, self.height, pixel_format, int(elapsed))
        full_range = bool(de265_get_image_full_range_flag(image))
        if "full-range" in options:
            full_range = options.boolget("full-range")
        return ImageWrapper(0, 0, self.width, self.height, pyplanes, pixel_format, 24,
                            pystrides, bytesperpixel=1, planes=PlanarFormat.PLANAR_3, full_range=full_range)


def selftest(full=False) -> None:
    log("de265 selftest: %s", get_info())
    from xpra.codecs.checks import testdecoder
    from xpra.codecs.de265 import decoder
    testdecoder(decoder, full)
