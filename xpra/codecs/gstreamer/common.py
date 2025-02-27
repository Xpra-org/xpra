# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from queue import SimpleQueue, Empty
from typing import Any
from collections.abc import Callable

from xpra.util.parsing import parse_simple_dict
from xpra.util.objects import typedict
from xpra.util.env import envint
from xpra.os_util import OSX, gi_import
from xpra.gstreamer.common import import_gst, GST_FLOW_OK
from xpra.gstreamer.pipeline import Pipeline
from xpra.log import Logger

Gst = import_gst()
log = Logger("encoder", "gstreamer")

FRAME_JUNK_TIMEOUT = envint("XPRA_FRAME_JUNK_TIMEOUT", 100)
FRAME_QUEUE_TIMEOUT = envint("XPRA_GSTREAMER_FRAME_QUEUE_TIMEOUT", 1000)
FRAME_QUEUE_INITIAL_TIMEOUT = envint("XPRA_GSTREAMER_FRAME_QUEUE_INITIAL_TIMEOUT", 3000)


def get_default_encoder_options() -> dict[str, dict[str, Any]]:
    options: dict[str, dict[str, Any]] = {
        "vaapih264enc": {
            "max-bframes": 0,  # int(options.boolget("b-frames", False))
            # "tune"          : 3,    #low-power
            # "rate-control" : 8, #qvbr
            "compliance-mode": 0,  # restrict-buf-alloc (1) – Restrict the allocation size of coded-buffer
            # "keyframe-period"   : 9999,
            # "prediction-type" : 1, #hierarchical-p (1) – Hierarchical P frame encode
            # "quality-factor" : 10,
            # "quality-level" : 50,
            # "bitrate"   : 2000,
            # "prediction-type" : 1,    #Hierarchical P frame encode
            # "keyframe-period" : 4294967295,
            "aud": True,
        },
        "vaapih265enc": {
            "max-bframes": 0,  # int(options.boolget("b-frames", False))
            # "tune"          : 3,    #low-power
            # "rate-control" : 8, #qvbr
        },
        "amfh264enc": {
            "usage": "ultra-low-latency",
        },
        "amfh265enc": {
            "usage": "ultra-low-latency",
        },
        "x264enc": {
            "speed-preset": "ultrafast",
            "tune": "zerolatency",
            "byte-stream": True,
            "threads": 1,
            "key-int-max": 15,
            "intra-refresh": True,
        },
        "vp8enc": {
            "deadline": 1,
            "error-resilient": 0,
        },
        "vp9enc": {
            "deadline": 1,
            "error-resilient": 0,
            "lag-in-frames": 0,
            "cpu-used": 16,
        },
        "nvh264enc": {
            "zerolatency": True,
            "rc-mode": 3,  # vbr
            "preset": 5,  # low latency, high performance
            "bframes": 0,
            "aud": True,
        },
        "nvh265enc": {
            "zerolatency": True,
            "rc-mode": 3,  # vbr
            "preset": 5,  # low latency, high performance
            # should be in GStreamer 1.18, but somehow missing?
            # "bframes"       : 0,
            "aud": True,
        },
        "nvd3d11h264enc": {
            "bframes": 0,
            "aud": True,
            "preset": 5,  # low latency, high performance
            "zero-reorder-delay": True,
        },
        "nvd3d11h265enc": {
            "bframes": 0,
            "aud": True,
            "preset": 5,  # low latency, high performance
            "zero-reorder-delay": True,
        },
        "svtav1enc": {
            # "speed"         : 12,
            # "gop-size"      : 251,
            "intra-refresh": 1,  # open gop
            # "lookahead"     : 0,
            # "rc"            : 1,    #vbr
        },
        "svtvp9enc": {
        },
        # "svthevcenc" : {
        #    "b-pyramid"         : 0,
        #    "baselayer-mode"    : 1,
        #    "enable-open-gop"   : True,
        #    "key-int-max"       : 255,
        #    "lookahead"         : 0,
        #    "pred-struct"       : 0,
        #    "rc"                : 1, #vbr
        #    "speed"             : 9,
        #    "tune"              : 0,
        # }
    }
    if not OSX:
        options["av1enc"] = {
            "cpu-used": 5,
            "end-usage": 2,  # cq
        }
    # now apply environment overrides:
    for element in options.keys():
        enc_options_str = os.environ.get(f"XPRA_{element.upper()}_OPTIONS", "")
        if enc_options_str:
            encoder_options = parse_simple_dict(enc_options_str)
            log(f"user overridden options for {element}: {encoder_options}")
            options[element] = encoder_options
    return options


def get_default_decoder_options() -> dict[str, dict[str, Any]]:
    options: dict[str, dict[str, Any]] = {
        "av1dec": {
            "stream-format": "obu-stream",
            "alignment": "tu",
        },
    }
    return options


def get_version() -> tuple[int, int]:
    return 5, 0


def get_type() -> str:
    return "gstreamer"


def get_info() -> dict[str, Any]:
    return {"version": get_version()}


IDENTICAL_PIXEL_FORMATS = (
    "NV12",
    "RGBA", "BGRA", "ARGB", "ABGR",
    "RGB", "BGR",
    "RGB15", "RGB16", "BGR15",
    "r210",
    "BGRP", "RGBP",
)
XPRA_TO_GSTREAMER = {
    "YUV420P": "I420",
    "YUV444P": "Y444",
    "BGRX": "BGRx",
    "XRGB": "xRGB",
    "XBGR": "xBGR",
    "YUV400": "GRAY8",
    # "RGB8P"
}
GSTREAMER_TO_XPRA = dict((v, k) for k, v in XPRA_TO_GSTREAMER.items())


def get_gst_rgb_format(rgb_format: str) -> str:
    if rgb_format in IDENTICAL_PIXEL_FORMATS:
        return rgb_format
    # translate to gstreamer name:
    return XPRA_TO_GSTREAMER.get(rgb_format, "")


def get_xpra_rgb_format(rgb_format: str) -> str:
    if rgb_format in IDENTICAL_PIXEL_FORMATS:
        return rgb_format
    # translate to gstreamer name:
    return GSTREAMER_TO_XPRA.get(rgb_format, "")


def gst_to_native(value: Any) -> tuple | str:
    if isinstance(value, Gst.ValueList):
        return tuple(value.get_value(value, i) for i in range(value.get_size(value)))
    if isinstance(value, Gst.IntRange):
        return value.range.start, value.range.stop
    if isinstance(value, Gst.FractionRange):

        def preferint(v):
            if int(v) == v:
                return int(v)
            return v

        def numdenom(fraction):
            return preferint(fraction.num), preferint(fraction.denom)
        return numdenom(value.start), numdenom(value.stop)
    # print(f"value={value} ({type(value)} - {dir(value)}")
    return Gst.value_serialize(value)


_overrides_verified = False


def verify_gst_overrides() -> bool:
    hasp3g = has_python3_gstreamer()
    global _overrides_verified
    if not hasp3g and not _overrides_verified:
        log.warn("Warning: `python3-gstreamer` is not installed")
        log.warn(" this will prevent the python bindings from working properly")
    _overrides_verified = True
    return hasp3g


def has_python3_gstreamer() -> bool:
    from importlib.util import find_spec
    return bool(find_spec("gi.overrides.Gst"))


def get_encoder_info(element="vp8enc") -> dict:
    """
    Get the element's input information,
    we only retrieve the "SINK" pad
    if it accepts `video/x-raw`.
    Convert Gst types into native types,
    and convert pixel formats to the names used in xpra.
    """
    factory = Gst.ElementFactory.find(element)
    if not factory:
        return {}
    if factory.get_num_pad_templates() == 0:
        return {}
    verify_gst_overrides()
    pads = factory.get_static_pad_templates()
    info = {}
    GLib = gi_import("GLib")
    log(f"get_encoder_info({element}) pads={pads}")
    for pad in pads:
        if pad.direction != Gst.PadDirection.SINK:
            log(f"ignoring {pad.direction}")
            continue
        padtemplate = pad.get()
        caps = padtemplate.get_caps()
        if not caps:
            log(f"pad template {padtemplate} has no caps!")
            continue
        if caps.is_any():
            continue
        if caps.is_empty():
            continue
        for i in range(caps.get_size()):
            structure = caps.get_structure(i)
            if structure.get_name() != "video/x-raw":
                continue

            def add_cap(field, value):
                fname = GLib.quark_to_string(field)
                native_value = gst_to_native(value)
                log(f"{fname}={native_value} ({type(native_value)})")
                if fname == "format":
                    if isinstance(native_value, str):
                        # convert it to a tuple:
                        native_value = native_value,
                    if isinstance(native_value, tuple):
                        xpra_formats = tuple(get_xpra_rgb_format(x) for x in native_value)
                        native_value = tuple(fmt for fmt in xpra_formats if fmt)
                info[fname] = native_value
                return True
            structure.foreach(add_cap)
    return info


def get_video_encoder_caps(encoder: str = "x264enc") -> dict[str, Any]:
    if encoder == "jpeg":
        return {}
    if encoder == "av1enc":
        return {
            "alignment": "tu",
            "stream-format": "obu-stream",
        }
    return {
        "alignment": "au",
        "stream-format": "byte-stream",
    }


def get_video_encoder_options(encoder: str = "x264", profile: str = "", options: typedict | None = None):
    eopts = get_default_encoder_options().get(encoder, {})
    eopts["name"] = "encoder"
    if encoder == "x264enc" and options:
        from xpra.codecs.constants import get_x264_quality, get_x264_preset
        q = get_x264_quality(options.intget("quality", 50), profile)
        s = options.intget("speed", 50)
        eopts |= {
            "pass": "qual",
            "quantizer": q,
            "speed-preset": get_x264_preset(s),
        }
    # should check for "bframes" flag in options?
    return eopts


def get_gst_encoding(encoding: str) -> str:
    if encoding in ("jpeg", "png"):
        return f"image/{encoding}"
    video = {"hevc": "h265"}.get(encoding, encoding)
    return f"video/x-{video}"


class VideoPipeline(Pipeline):
    __generic_signals__: dict[str, tuple] = Pipeline.__generic_signals__.copy()
    """
    Dispatch video encoding or decoding to a gstreamer pipeline
    """

    def __init__(self):
        super().__init__()
        self.encoding = ""
        self.width = 0
        self.height = 0
        self.colorspace = ""
        self.frames = 0
        self.frame_queue: SimpleQueue[Any] = SimpleQueue()
        self.pipeline_str = ""
        self.src: Gst.Element | None = None
        self.sink: Gst.Element | None = None

    def init_context(self, encoding: str, width: int, height: int, colorspace: str, options: typedict) -> None:
        self.encoding = encoding
        self.width = width
        self.height = height
        self.colorspace = colorspace
        self.create_pipeline(options)
        self.src: Gst.Element = self.pipeline.get_by_name("src")
        self.src.set_property("format", Gst.Format.TIME)
        self.sink: Gst.Element = self.pipeline.get_by_name("sink")

        def sh(sig: str, handler: Callable):
            self.element_connect(self.sink, sig, handler)

        sh("new-sample", self.on_new_sample)
        sh("new-preroll", self.on_new_preroll)
        self.start()

    def create_pipeline(self, options):
        raise NotImplementedError()

    def on_message(self, bus, message) -> int:
        if message.type == Gst.MessageType.NEED_CONTEXT and self.pipeline_str.find("vaapi") >= 0:
            log("vaapi is requesting a context")
            return GST_FLOW_OK
        return super().on_message(bus, message)

    def on_new_preroll(self, _appsink) -> int:
        log("new-preroll")
        return GST_FLOW_OK

    def process_buffer(self, buf, options: typedict):
        r = self.src.emit("push-buffer", buf)
        if r != GST_FLOW_OK:
            log.error("Error: unable to push image buffer")
            return None

        junk = options.boolget("junk")
        if junk:
            timeout = FRAME_JUNK_TIMEOUT
        elif self.frames == 0:
            timeout = FRAME_QUEUE_INITIAL_TIMEOUT
        else:
            timeout = FRAME_QUEUE_TIMEOUT
        try:
            return self.frame_queue.get(timeout=timeout/1000)
        except Empty:
            log_fn = log.debug if junk else log.error
            log_fn(f"Error: frame queue timeout after {timeout}ms")
            try:
                btype = type(buf).__qualname__.lower()
                log_fn(f" on {btype!r} of size {buf.get_size()}")
                log_fn(f" of {repr(self)}")
            except AttributeError:
                pass
            for k, v in self.get_info().items():
                log_fn(f" {k:<16}: {v}")
            return None

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = get_info()
        if not self.colorspace:
            return info
        info |= {
            "frames": self.frames,
            "width": self.width,
            "height": self.height,
            "encoding": self.encoding,
            "colorspace": self.colorspace,
            "version": get_version(),
        }
        return info

    def __repr__(self):
        if not self.colorspace:
            return "gstreamer(uninitialized)"
        return f"gstreamer({self.colorspace} - {self.width}x{self.height})"

    def is_ready(self) -> bool:
        return bool(self.colorspace)

    def is_closed(self) -> bool:
        return not bool(self.colorspace)

    def get_encoding(self) -> str:
        return self.encoding

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "gstreamer"

    def clean(self) -> None:
        super().cleanup()
        self.width = 0
        self.height = 0
        self.colorspace = ""
        self.encoding = ""
        self.frames = 0

    def do_emit_info(self) -> None:
        self.emit_info_timer = 0
