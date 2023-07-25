# This file is part of Xpra.
# Copyright (C) 2014-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from queue import Queue, Empty
from typing import Tuple, Dict, Any, Callable, Optional

from xpra.util import typedict, envint, parse_simple_dict
from xpra.os_util import OSX
from xpra.gst_common import import_gst, GST_FLOW_OK
from xpra.gst_pipeline import Pipeline
from xpra.log import Logger

Gst = import_gst()
log = Logger("encoder", "gstreamer")

FRAME_QUEUE_TIMEOUT = envint("XPRA_GSTREAMER_FRAME_QUEUE_TIMEOUT", 1)
FRAME_QUEUE_INITIAL_TIMEOUT = envint("XPRA_GSTREAMER_FRAME_QUEUE_INITIAL_TIMEOUT", 3)


def get_default_encoder_options() -> Dict[str,Dict[str,Any]]:
    options : Dict[str,Dict[str,Any]] = {
        "vaapih264enc" : {
            "max-bframes"   : 0,    #int(options.boolget("b-frames", False))
            #"tune"          : 3,    #low-power
            #"rate-control" : 8, #qvbr
            "compliance-mode" : 0,  #restrict-buf-alloc (1) – Restrict the allocation size of coded-buffer
            #"keyframe-period"   : 9999,
            #"prediction-type" : 1, #hierarchical-p (1) – Hierarchical P frame encode
            #"quality-factor" : 10,
            #"quality-level" : 50,
            #"bitrate"   : 2000,
            #"prediction-type" : 1,    #Hierarchical P frame encode
            #"keyframe-period" : 4294967295,
            "aud"   : True,
            },
        "vaapih265enc" : {
            "max-bframes"   : 0,    #int(options.boolget("b-frames", False))
            #"tune"          : 3,    #low-power
            #"rate-control" : 8, #qvbr
            },
        "amfh264enc" : {
            "usage"    : "ultra-low-latency",
            },
        "amfh265enc" : {
            "usage"    : "ultra-low-latency",
            },
        "x264enc" : {
            "speed-preset"  : "ultrafast",
            "tune"          : "zerolatency",
            "byte-stream"   : True,
            "threads"       : 1,
            "key-int-max"   : 15,
            "intra-refresh" : True,
            },
        "vp8enc" : {
            "deadline"      : 1,
            "error-resilient" : 0,
            },
        "vp9enc" : {
            "deadline"      : 1,
            "error-resilient" : 0,
            "lag-in-frames" : 0,
            "cpu-used"      : 16,
            },
        "nvh264enc" : {
            "zerolatency"   : True,
            "rc-mode"       : 3,    #vbr
            "preset"        : 5,    #low latency, high performance
            "bframes"       : 0,
            "aud"           : True,
            },
        "nvh265enc" : {
            "zerolatency"   : True,
            "rc-mode"       : 3,    #vbr
            "preset"        : 5,    #low latency, high performance
            #should be in GStreamer 1.18, but somehow missing?
            #"bframes"       : 0,
            "aud"           : True,
            },
        "nvd3d11h264enc" : {
            "bframes"       : 0,
            "aud"           : True,
            "preset"        : 5,    #low latency, high performance
            "zero-reorder-delay"    : True,
            },
        "nvd3d11h265enc" : {
            "bframes"       : 0,
            "aud"           : True,
            "preset"        : 5,    #low latency, high performance
            "zero-reorder-delay"    : True,
            },
        "svtav1enc" : {
            # "speed"         : 12,
            # "gop-size"      : 251,
            "intra-refresh" : 1,    #open gop
            # "lookahead"     : 0,
            # "rc"            : 1,    #vbr
            },
        "svtvp9enc" : {
            },
        #"svthevcenc" : {
        #    "b-pyramid"         : 0,
        #    "baselayer-mode"    : 1,
        #    "enable-open-gop"   : True,
        #    "key-int-max"       : 255,
        #    "lookahead"         : 0,
        #    "pred-struct"       : 0,
        #    "rc"                : 1, #vbr
        #    "speed"             : 9,
        #    "tune"              : 0,
        #    }
        }
    if not OSX:
        options["av1enc"] = {
            "cpu-used"          : 5,
            "end-usage"         : 2,    #cq
            }
    #now apply environment overrides:
    for element in options.keys():
        enc_options_str = os.environ.get(f"XPRA_{element.upper()}_OPTIONS", "")
        if enc_options_str:
            encoder_options = parse_simple_dict(enc_options_str)
            log(f"user overridden options for {element}: {encoder_options}")
            options[element] = encoder_options
    return options

def get_default_decoder_options() -> Dict[str,Dict[str,Any]]:
    options : Dict[str,Dict[str,Any]] = {
        "av1dec"    : {
            "stream-format": "obu-stream",
            "alignment": "tu",
        },
    }
    return options


def get_version() -> Tuple[int, ...]:
    return (5, 0)

def get_type() -> str:
    return "gstreamer"

def get_info() -> Dict[str,Any]:
    return {"version"   : get_version()}

def init_module() -> None:
    log("gstreamer.init_module()")

def cleanup_module() -> None:
    log("gstreamer.cleanup_module()")


def get_gst_rgb_format(rgb_format : str) -> str:
    if rgb_format in (
        "NV12",
        "RGBA", "BGRA", "ARGB", "ABGR",
        "RGB", "BGR",
        "RGB15", "RGB16", "BGR15",
        "r210",
        "BGRP", "RGBP",
        ):
        #identical name:
        return rgb_format
    #translate to gstreamer name:
    return {
        "YUV420P"   : "I420",
        "YUV444P"   : "Y444",
        "BGRX"      : "BGRx",
        "XRGB"      : "xRGB",
        "XBGR"      : "xBGR",
        "YUV400"    : "GRAY8",
        #"RGB8P"
        }[rgb_format]


def get_video_encoder_caps(encoder:str="x264enc") -> Dict[str,Any]:
    if encoder=="jpeg":
        return {}
    if encoder=="av1enc":
        return {
            "alignment"     : "tu",
            "stream-format" : "obu-stream",
            }
    return {
        "alignment"     : "au",
        "stream-format" : "byte-stream",
        }

def get_video_encoder_options(encoder:str="x264", profile:str="", options:Optional[typedict]=None):
    eopts = get_default_encoder_options().get(encoder, {})
    eopts["name"] = "encoder"
    if encoder=="x264enc" and options:
        from xpra.codecs.codec_constants import get_x264_quality, get_x264_preset
        q = get_x264_quality(options.intget("quality", 50), profile)
        s = options.intget("speed", 50)
        eopts.update({
            "pass"  : "qual",
            "quantizer" : q,
            "speed-preset" : get_x264_preset(s),
            })
    #should check for "bframes" flag in options?
    return eopts

def get_gst_encoding(encoding:str) -> str:
    if encoding in ("jpeg", "png"):
        return f"image/{encoding}"
    video = {"hevc" : "h265"}.get(encoding, encoding)
    return f"video/x-{video}"


class VideoPipeline(Pipeline):
    __generic_signals__ : Dict[str,Tuple] = Pipeline.__generic_signals__.copy()
    """
    Dispatch video encoding or decoding to a gstreamer pipeline
    """
    def init_context(self, encoding:str, width:int, height:int, colorspace:str, options=None):
        options = typedict(options or {})
        self.encoding : str = encoding
        self.width : int = width
        self.height : int = height
        self.colorspace : str = colorspace
        self.frames : int = 0
        self.frame_queue : Queue[Any] = Queue()
        self.pipeline_str : str = ""
        self.create_pipeline(options)
        self.src : Gst.Element = self.pipeline.get_by_name("src")
        self.src.set_property("format", Gst.Format.TIME)
        #self.src.set_caps(Gst.Caps.from_string(CAPS))
        self.sink : Gst.Element = self.pipeline.get_by_name("sink")
        def sh(sig:str, handler:Callable):
            self.element_connect(self.sink, sig, handler)
        sh("new-sample", self.on_new_sample)
        sh("new-preroll", self.on_new_preroll)
        self.start()

    def create_pipeline(self, options):
        raise NotImplementedError()

    def on_message(self, bus, message) -> int:
        if message.type == Gst.MessageType.NEED_CONTEXT and self.pipeline_str.find("vaapi")>=0:
            log("vaapi is requesting a context")
            return GST_FLOW_OK
        return super().on_message(bus, message)

    def on_new_preroll(self, _appsink) -> int:
        log("new-preroll")
        return GST_FLOW_OK

    def process_buffer(self, buf):
        r = self.src.emit("push-buffer", buf)
        if r!=GST_FLOW_OK:
            log.error("Error: unable to push image buffer")
            return None
        timeout = FRAME_QUEUE_INITIAL_TIMEOUT if self.frames==0 else FRAME_QUEUE_TIMEOUT
        try:
            return self.frame_queue.get(timeout=timeout)
        except Empty:
            log.error(f"Error: frame queue timeout after {timeout}s")
            try:
                btype = type(buf).__qualname__
                log.error(f" on {btype!r} of size {buf.get_size()}")
            except AttributeError:
                pass
            for k,v in self.get_info().items():
                log.error(f" {k:<16}: {v}")
            return None


    def get_info(self) -> Dict[str,Any]:
        info : Dict[str,Any] = get_info()
        if not self.colorspace:
            return info
        info.update({
            "frames"    : self.frames,
            "width"     : self.width,
            "height"    : self.height,
            "encoding"  : self.encoding,
            "colorspace": self.colorspace,
            "version"   : get_version(),
            })
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
