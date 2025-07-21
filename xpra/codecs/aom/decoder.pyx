# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: wraparound=False

import weakref
from time import sleep
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec
from xpra.util.env import envbool
from xpra.util.str_fn import hexstr
from xpra.util.objects import typedict
from xpra.codecs.image import ImageWrapper, PlanarFormat
from xpra.log import Logger

log = Logger("decoder", "aom")

from libc.string cimport memset, memcpy
from libc.stdint cimport uint8_t, uintptr_t
from xpra.buffers.membuf cimport wrapbuf, MemBuf, buffer_context  # pylint: disable=syntax-error
from xpra.codecs.argb.argb cimport show_plane_range


cdef unsigned char debug_enabled = log.is_debug_enabled()
cdef unsigned char SHOW_PLANE_RANGES = envbool("XPRA_SHOW_PLANE_RANGES", False)


from xpra.codecs.aom.api cimport (
    get_format_str,
    aom_codec_iface_t, aom_codec_ctx_t, aom_codec_iface_name,
    aom_codec_version, aom_codec_err_t, aom_codec_err_to_string,
    aom_codec_dec_cfg_t, aom_codec_dec_init_ver, aom_codec_decode ,aom_codec_destroy,
    aom_codec_get_frame, aom_codec_iter_t, aom_image_t, aom_img_plane_width,
    aom_codec_error_detail,
    aom_img_plane_height, aom_img_fmt_t, AOM_BITS_8, AOM_CR_FULL_RANGE,
    AOM_DECODER_ABI_VERSION, AOM_CODEC_OK, AOM_CODEC_MEM_ERROR,
    AOM_CODEC_ABI_MISMATCH, AOM_CODEC_INCAPABLE, AOM_CODEC_UNSUP_BITSTREAM,
    AOM_CODEC_UNSUP_FEATURE, AOM_CODEC_CORRUPT_FRAME, AOM_CODEC_INVALID_PARAM
)


cdef extern from "aom/aomdx.h":
    aom_codec_iface_t *aom_codec_av1_dx() nogil


cdef int check(r: aom_codec_err_t) except -1:
    if r == AOM_CODEC_OK:
        return 0
    elif r == AOM_CODEC_MEM_ERROR:
        raise MemoryError("AOM codec memory error")
    elif r == AOM_CODEC_ABI_MISMATCH:
        raise RuntimeError("AOM codec ABI mismatch")
    elif r == AOM_CODEC_INCAPABLE:
        raise RuntimeError("AOM codec incapable")
    elif r == AOM_CODEC_UNSUP_BITSTREAM:
        raise RuntimeError("AOM codec unsupported bitstream")
    elif r == AOM_CODEC_UNSUP_FEATURE:
        raise RuntimeError("AOM codec unsupported feature")
    elif r == AOM_CODEC_CORRUPT_FRAME:
        raise RuntimeError("AOM codec corrupt frame")
    elif r == AOM_CODEC_INVALID_PARAM:
        raise ValueError("AOM codec invalid parameter")
    else:
        raise RuntimeError(f"AOM codec error: {aom_codec_err_to_string(r).decode('utf-8')}")


def get_version() -> Tuple[int, int, int]:
    cdef int version = aom_codec_version()
    return (version >> 16, (version >> 8) & 0xFF, version & 0xFF)


def get_type() -> str:
    return "aom"


def get_info() -> Dict[str, Tuple[int, int, int] | int]:
    return {
        "version": get_version(),
        "abi": AOM_DECODER_ABI_VERSION,
    }


def get_min_size(encoding: str) -> Tuple[int, int]:
    return 16, 16


def get_encodings() -> Sequence[str]:
    return ("av1", )


MAX_WIDTH, MAX_HEIGHT = (8192, 4096)

COLORSPACES = ("YUV420P", "YUV422P", "YUV444P", "YUV420P16", "YUV422P16", "YUV444P16", "NV12")


def get_specs() -> Sequence[VideoSpec]:
    specs = []
    for cs in COLORSPACES:
        specs.append(
            VideoSpec(
                encoding="av1", input_colorspace=cs, output_colorspaces=(cs, ),
                has_lossless_mode=False,
                codec_class=Decoder, codec_type=get_type(),
                quality=40, speed=20,
                size_efficiency=40,
                setup_cost=0, width_mask=0xFFFE, height_mask=0xFFFE,
                max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
            )
        )
    return specs


cdef class Decoder:
    cdef unsigned long frames
    cdef unsigned int width
    cdef unsigned int height
    cdef object colorspace
    cdef aom_codec_iface_t *codec
    cdef aom_codec_ctx_t context
    cdef object image_wrapper

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("aom.init_context%s", (encoding, width, height, colorspace))
        assert encoding == "av1", f"invalid encoding: {encoding}"
        if colorspace not in COLORSPACES:
            raise ValueError(f"invalid colorspace: {colorspace!r}, expected one of {COLORSPACES}")
        self.width = width
        self.height = height
        self.colorspace = colorspace
        self.frames = 0
        self.codec = <aom_codec_iface_t*> aom_codec_av1_dx()
        name = aom_codec_iface_name(self.codec)
        log("codec: %s", name.decode("utf-8"))
        cdef aom_codec_dec_cfg_t config
        memset(&config, 0, sizeof(aom_codec_dec_cfg_t))
        config.threads = options.intget("threads", 0)  # 0 means use the default number of threads
        config.w = width
        config.h = height
        config.allow_lowbitdepth = 1
        cdef aom_codec_err_t err = aom_codec_dec_init_ver(&self.context, self.codec, &config,
                                                          0, AOM_DECODER_ABI_VERSION)
        check(err)

    def get_encoding(self) -> str:
        return "av1"

    def get_colorspace(self) -> str:
        return self.colorspace

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def is_closed(self) -> bool:
        return bool(self.codec != NULL)

    def get_type(self) -> str:
        return "aom"

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        self.frames = 0
        self.width = 0
        self.height = 0
        self.colorspace = ""
        cdef aom_codec_err_t r
        if self.codec != NULL:
            r = aom_codec_destroy(&self.context)
            if r:
                log.error("Error destroying codec: %i", r)
            self.codec = NULL

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames"        : int(self.frames),
            "width"         : self.width,
            "height"        : self.height,
            "colorspace"    : self.colorspace,
        }
        return info

    def wait_for_image(self) -> None:
        cdef object wrapper = None
        ref = self.image_wrapper
        if ref is None:
            return      # no image wrapper to wait for
        for i in range(20):
            wrapper = self.image_wrapper()
            if wrapper is None or wrapper.freed:
                self.image_wrapper = None  # clear the weakref
                return
            log("wait_for_image() wrapper=%s", wrapper)
            # if the image wrapper still exists,
            # then it references the libaom buffers
            # we can't just call:
            # `wrapper.clone_pixel_data()`
            # because the pixel buffers may already be in use
            sleep(i / 1000)  # wait a bit for the image wrapper to be released
        raise RuntimeError("ImageWrapper is still in use, cannot decode new image")

    def decompress_image(self, data: bytes, options: typedict) -> ImageWrapper:
        log("decompress_image(%i bytes, %s)", len(data), options)
        cdef aom_codec_err_t r = AOM_CODEC_OK

        self.wait_for_image()  # wait for the previous image to be released

        cdef size_t data_len
        cdef const uint8_t* data_buf
        with buffer_context(data) as bc:
            data_len = len(bc)
            data_buf = <const uint8_t*> (<uintptr_t> int(bc))
            with nogil:
                r = aom_codec_decode(&self.context, data_buf, data_len, NULL)
        log("aom_codec_decode(..)=%s", r)
        check(r)

        cdef aom_codec_iter_t iter = NULL
        cdef aom_image_t *image = NULL
        with nogil:
            image = aom_codec_get_frame(&self.context, &iter)
        if image == NULL:
            err = aom_codec_error_detail(&self.context).decode("utf-8")
            log.error("Error retrieving frame: %s", err)
            raise RuntimeError(err)

        pixel_format = get_format_str(image.fmt)
        log("got aom av1 image at %#x, pixel format %s", <uintptr_t> image, pixel_format)
        if pixel_format not in COLORSPACES:
            raise RuntimeError(f"Unsupported image format %r" % pixel_format)
        Bpp = 6 if pixel_format.endswith("P16") else 3
        if image.bit_depth != AOM_BITS_8:
            raise RuntimeError("image bit depth %i is not supported yet" % image.bit_depth)
        depth = Bpp * image.bit_depth

        # expose these eventually:
        # aom_color_primaries color_primaries
        # aom_transfer_characteristics transfer_characteristics
        # aom_matrix_coefficients matrix_coefficients
        if image.monochrome:
            log("monochrome image")
        # aom_chroma_sample_position chroma_sample_position
        full_range = image.range == AOM_CR_FULL_RANGE
        if image.w < self.width or image.h < self.height:
            log.error("Error: image size %ix%i does not match expected size %ix%i",
                      image.w, image.h, self.width, self.height)
            return None

        # we have to copy the image data to a new buffer,
        # until we can implement the aom_codec_set_frame_buffer_functions callbacks
        pyplanes = []
        pystrides = []
        cdef MemBuf plane_buf
        cdef int plane_width
        cdef int plane_height
        cdef int stride
        for i in range(3):
            assert image.planes[i] != NULL
            plane_width = aom_img_plane_width(image, i)
            plane_height = aom_img_plane_height(image, i)
            stride = image.stride[i]
            log("plane %s: %4ix%-4i, stride=%i", "YUV"[i], plane_width, plane_height, stride)
            plane_buf = wrapbuf(<void *> image.planes[i], plane_height * stride)
            pyplanes.append(memoryview(plane_buf))
            pystrides.append(stride)

        if SHOW_PLANE_RANGES:
            self.show_planes(pyplanes, pystrides)

        self.frames += 1
        wrapper = ImageWrapper(0, 0, self.width, self.height, pyplanes, pixel_format, depth,
                               pystrides, planes=PlanarFormat.PLANAR_3, bytesperpixel=Bpp, full_range=full_range)
        self.image_wrapper = weakref.ref(wrapper)
        return wrapper


    def show_planes(self, pyplanes: Sequence[memoryview], pystrides: Sequence[int]) -> None:
        show_plane_range("Y", pyplanes[0], self.width, pystrides[0], self.height)
        log.info("Y[0]=%s", hexstr(pyplanes[0][:64]))
        show_plane_range("U", pyplanes[1], self.width, pystrides[1], self.height//2)
        log.info("U[0]=%s", hexstr(pyplanes[1][:64]))
        show_plane_range("V", pyplanes[2], self.width, pystrides[2], self.height//2)
        log.info("V[0]=%s", hexstr(pyplanes[2][:64]))


def selftest(full=False) -> None:
    log("aom selftest: %s", get_info())
    if log.is_debug_enabled():
        global debug_enabled
        debug_enabled = True
    from xpra.codecs.checks import testdecoder
    from xpra.codecs.aom import decoder
    testdecoder(decoder, full)
