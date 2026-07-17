# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: libva hardware decoder.
# ABOUTME: Wraps the C va_decode API and returns NV12 / YUV444P / XYUV / AYUV frames.

#cython: wraparound=False

from time import monotonic
from typing import Any, Dict, Tuple
from collections.abc import Sequence

from xpra.codecs.constants import VideoSpec, EncodingNotSupported, CodecStateException
from xpra.codecs.vacommon import config_libva_logging
from xpra.codecs.image import ImageWrapper
from xpra.common import SizedBuffer
from xpra.util.objects import typedict
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("decoder", "libva")

from libc.stdint cimport uint8_t, uintptr_t
from xpra.buffers.membuf cimport buffer_context  # pylint: disable=syntax-error


cdef void libva_log_callback(const char *msg) noexcept with gil:
    log("%s", msg.decode("utf-8", "replace"))


cdef extern from "va_decode.h":
    ctypedef struct LibVADecoder:
        pass

    ctypedef enum LibVADecodeStatus:
        LIBVA_DEC_OK
        LIBVA_DEC_ERROR
        LIBVA_DEC_NOT_AVAILABLE
        LIBVA_DEC_UNSUPPORTED

    ctypedef enum LibVADecodeFormat:
        LIBVA_DEC_FMT_UNKNOWN
        LIBVA_DEC_FMT_NV12
        LIBVA_DEC_FMT_YUV444P
        LIBVA_DEC_FMT_XYUV
        LIBVA_DEC_FMT_AYUV

    ctypedef struct LibVADecodedFrame:
        uint8_t *planes[3]
        int      strides[3]
        int      sizes[3]
        int      nplanes
        int      width
        int      height
        int      depth
        int      bytes_per_pixel
        int      full_range
        LibVADecodeFormat format
        int      us_submit
        int      us_sync
        int      us_map
        int      us_copy

    ctypedef void (*libva_log_fn)(const char *msg)

    void              libva_decode_set_log(libva_log_fn fn)
    LibVADecodeStatus libva_decode_startup()
    void              libva_decode_shutdown()
    const char       *libva_decode_get_device()
    const char       *libva_decode_get_vendor()
    const char       *libva_decode_get_last_error()
    int               libva_decode_get_major()
    int               libva_decode_get_minor()
    int               libva_decode_supports(const char *encoding, const char *colorspace)

    LibVADecodeStatus libva_decoder_create(LibVADecoder **out, const char *encoding,
                                           int width, int height, const char *colorspace) nogil
    void              libva_decoder_destroy(LibVADecoder *dec) nogil
    LibVADecodeStatus libva_decoder_decode(LibVADecoder *dec,
                                           const uint8_t *data, int data_len,
                                           LibVADecodedFrame *frame) nogil

    int               libva_decoder_get_width(LibVADecoder *dec)
    int               libva_decoder_get_height(LibVADecoder *dec)
    int               libva_decoder_get_last_status(LibVADecoder *dec)
    const char       *libva_decoder_get_last_error(LibVADecoder *dec)
    const char       *libva_decode_status_str(LibVADecodeStatus status)
    const char       *libva_decode_format_str(LibVADecodeFormat format)


ENCODINGS: Sequence[str] = ("h264", "vp8", "vp9")
COLORSPACES: dict[str, tuple[str, ...]] = {
    "h264": ("YUV420P", "YUV444P"),
    "vp8": ("YUV420P", ),
    "vp9": ("YUV420P", ),
}


def init_module(options: dict = None) -> None:
    log("libva.decoder.init_module()")
    config_libva_logging()
    libva_decode_set_log(libva_log_callback)
    cdef LibVADecodeStatus status = libva_decode_startup()
    if status != LIBVA_DEC_OK:
        detail = libva_decode_get_last_error().decode("utf-8", "replace")
        msg = "libva decoder startup failed: %s" % libva_decode_status_str(status).decode("latin-1")
        if detail:
            msg += " (%s)" % detail
        raise ImportError(msg)


def cleanup_module() -> None:
    libva_decode_shutdown()


def get_version() -> Tuple[int, int]:
    return 1, 0


def get_type() -> str:
    return "libva"


def get_info() -> Dict[str, Any]:
    info = {
        "version": get_version(),
        "type": "libva",
        "device": libva_decode_get_device().decode("utf-8", "replace"),
        "vendor": libva_decode_get_vendor().decode("utf-8", "replace"),
        "libva": (libva_decode_get_major(), libva_decode_get_minor()),
    }
    for encoding in ENCODINGS:
        colorspaces = COLORSPACES.get(encoding, ())
        supported = tuple(cs for cs in colorspaces if supports(encoding, cs))
        if supported:
            info.setdefault(encoding, {})["colorspaces"] = supported
    return info


def get_encodings() -> Sequence[str]:
    return tuple(
        encoding for encoding in ENCODINGS
        if any(supports(encoding, cs) for cs in COLORSPACES.get(encoding, ()))
    )


def get_min_size(encoding) -> Tuple[int, int]:
    return 64, 64


cdef bint supports(str encoding, str colorspace):
    cdef bytes enc = encoding.encode("latin-1")
    cdef bytes cs = colorspace.encode("latin-1")
    return bool(libva_decode_supports(enc, cs))


# driver limits, overridable for hardware whose VA driver cannot
# express them (ie: the VDPAU bridge on feature-set-A NVIDIA: H264
# maxes at 2048x2048 AND 8192 macroblocks = 2097152 pixels):
MAX_WIDTH = envint("XPRA_LIBVA_MAX_WIDTH", 8192)
MAX_HEIGHT = envint("XPRA_LIBVA_MAX_HEIGHT", 8192)
MAX_PIXELS = envint("XPRA_LIBVA_MAX_PIXELS", 0)


def get_specs() -> Sequence[VideoSpec]:
    specs = []
    for encoding, colorspaces in COLORSPACES.items():
        for colorspace in colorspaces:
            if not supports(encoding, colorspace):
                continue
            output_colorspaces = ("NV12", ) if colorspace == "YUV420P" else ("XYUV", "AYUV")
            specs.append(VideoSpec(
                encoding=encoding,
                input_colorspace=colorspace,
                output_colorspaces=output_colorspaces,
                has_lossless_mode=False,
                codec_class=Decoder,
                codec_type=get_type(),
                quality=80, speed=90,
                size_efficiency=70,
                # setup_cost 0 (was 50): choose_decoder() ranks by
                # setup_cost alone and openh264 declares 0, so any
                # nonzero value here means the hardware decoder can
                # NEVER be selected when openh264 is present.  With
                # equal cost the tie-break is list order = the user's
                # --video-decoders order, which is the right authority.
                setup_cost=0,
                # ONE live hardware decode stream at a time: on the
                # VDPAU bridge (NVIDIA VP2 era) two concurrent decode
                # streams corrupt each other's luma via the shared video
                # engine's per-channel state (measured: whole-frame Y
                # damage on 13-41% of frames, chroma bit-exact).  The
                # selection layer routes additional streams to the next
                # decoder (ie: openh264) while one is live.
                max_instances=1,
                min_w=64, min_h=64,
                width_mask=0xFFFF, height_mask=0xFFFF,
                max_w=MAX_WIDTH, max_h=MAX_HEIGHT,
                max_pixels=MAX_PIXELS,
                cpu_cost=10,
                gpu_cost=80,
            ))
    return tuple(specs)


cdef str frame_pixel_format(LibVADecodeFormat fmt):
    return libva_decode_format_str(fmt).decode("latin-1")


cdef class Decoder:
    cdef LibVADecoder *context
    cdef unsigned long frames
    cdef int width
    cdef int height
    cdef object colorspace
    cdef object encoding
    cdef int full_range

    cdef object __weakref__

    def init_context(self, encoding: str, int width, int height, colorspace: str, options: typedict) -> None:
        log("libva.decoder.init_context%s", (encoding, width, height, colorspace, options))
        assert encoding in ENCODINGS, "unsupported encoding: %s" % encoding
        assert colorspace in COLORSPACES[encoding], "invalid colorspace %s for %s" % (colorspace, encoding)
        # odd display sizes are fine: the bitstream is coded at the
        # padded even size (SPS crop carries the display size) and the
        # NV12 copy-out handles odd width/height (ceil'd chroma rows,
        # even-rounded chroma stride)
        if width > MAX_WIDTH or height > MAX_HEIGHT or (MAX_PIXELS > 0 and width * height > MAX_PIXELS):
            # belt-and-braces for callers that bypass the size-aware
            # decoder selection: fail here (cleanly, before creating a
            # decoder that would error on every submit)
            raise RuntimeError("%ix%i exceeds this device's decode limits" % (width, height))
        self.encoding = encoding
        self.colorspace = colorspace
        self.width = width
        self.height = height
        self.frames = 0
        # modern mode omits steady-state full-range=True, so missing metadata defaults to
        # full-range until the bitstream or an explicit option says otherwise.
        self.full_range = True

        cdef bytes encoding_bytes = encoding.encode("latin-1")
        cdef bytes colorspace_bytes = colorspace.encode("latin-1")
        cdef const char *encoding_name = encoding_bytes
        cdef const char *colorspace_name = colorspace_bytes
        cdef LibVADecodeStatus status
        with nogil:
            status = libva_decoder_create(&self.context, encoding_name, width, height, colorspace_name)
        if status != LIBVA_DEC_OK:
            status_str = libva_decode_status_str(status).decode("latin-1")
            detail = libva_decode_get_last_error().decode("utf-8", "replace")
            msg = "failed to create libva %s decoder (%dx%d %s): %s" % (
                encoding, width, height, colorspace, status_str)
            if detail:
                msg += " (%s)" % detail
            if status == LIBVA_DEC_NOT_AVAILABLE:
                raise EncodingNotSupported(msg)
            raise RuntimeError(msg)

    def __repr__(self):
        if self.context == NULL:
            return "libva_decoder(closed)"
        return "libva_decoder(%s:%ix%i:%s)" % (self.encoding, self.width, self.height, self.colorspace)

    def __dealloc__(self):
        self.clean()

    def clean(self) -> None:
        cdef LibVADecoder *context = self.context
        if context != NULL:
            log("libva decoder close context %#x", <uintptr_t> context)
            self.context = NULL
            with nogil:
                libva_decoder_destroy(context)
        self.frames = 0
        self.width = 0
        self.height = 0
        self.colorspace = ""
        self.encoding = ""

    def is_closed(self) -> bool:
        return self.context == NULL

    def get_encoding(self) -> str:
        return self.encoding

    def get_colorspace(self) -> str:
        return self.colorspace

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "libva"

    def get_info(self) -> Dict[str, Any]:
        info = get_info()
        info |= {
            "frames": int(self.frames),
            "width": self.width,
            "height": self.height,
            "colorspace": self.colorspace,
            "encoding": self.encoding,
        }
        return info

    def decompress_image(self, data: SizedBuffer, options: typedict) -> ImageWrapper:
        cdef LibVADecodedFrame frame
        cdef LibVADecodeStatus status = LIBVA_DEC_ERROR
        cdef uint8_t *src
        cdef Py_ssize_t src_len

        assert self.context != NULL, "decoder is closed"
        start = monotonic()
        with buffer_context(data) as bc:
            src = <uint8_t*> (<uintptr_t> int(bc))
            src_len = len(bc)
            with nogil:
                status = libva_decoder_decode(self.context, <const uint8_t *> src, <int> src_len, &frame)
        if status != LIBVA_DEC_OK:
            detail = libva_decoder_get_last_error(self.context).decode("utf-8", "replace")
            last_sts = libva_decoder_get_last_status(self.context)
            # CodecStateException (not RuntimeError): the paint code
            # restarts the decoder on it (backing.py), whereas other
            # exception types propagate and leave a stale decoder in
            # place; a mid-stream failure here always invalidates the
            # decoder state (DPB / reference chain)
            raise CodecStateException("libva decode error: %s (detail: %s, sts=%d)" % (
                libva_decode_status_str(status).decode("latin-1"), detail, last_sts))

        pixels = tuple(frame.planes[i][:frame.sizes[i]] for i in range(frame.nplanes))
        strides = tuple(frame.strides[i] for i in range(frame.nplanes))
        pixel_format = frame_pixel_format(frame.format)
        planes = ImageWrapper.PACKED
        if frame.nplanes == 2:
            planes = ImageWrapper.PLANAR_2
        elif frame.nplanes == 3:
            planes = ImageWrapper.PLANAR_3
        elapsed = int((monotonic() - start) * 1000000)
        log("libva decoded %s %8d bytes into %dx%d %s in %dms submit=%dus sync=%dus map=%dus copy=%dus",
            self.encoding, src_len, frame.width, frame.height, pixel_format, (elapsed + 500) // 1000,
            frame.us_submit, frame.us_sync, frame.us_map, frame.us_copy)
        self.frames += 1
        # va_decode.c parses the colour range from the bitstream headers for h264 (SPS VUI)
        # and vp9 (color_config), but vp8 has no range syntax - so for vp8 we reuse the range
        # from an earlier frame's options; the client option always takes precedence:
        if "full-range" in options:
            self.full_range = options.boolget("full-range")
        elif self.encoding != "vp8":
            self.full_range = bool(frame.full_range)
        return ImageWrapper(0, 0, self.width, self.height,
                            pixels, pixel_format, frame.depth, strides,
                            frame.bytes_per_pixel, planes,
                            full_range=bool(self.full_range))


def selftest(full=False) -> None:
    global ENCODINGS
    log("libva decoder selftest: %s", get_info())
    from xpra.codecs.checks import testdecoder
    from xpra.codecs.libva import decoder
    ENCODINGS = testdecoder(decoder, full)
