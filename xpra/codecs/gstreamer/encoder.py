# This file is part of Xpra.
# Copyright (C) 2014-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from queue import Queue, Empty

from xpra.util import typedict, parse_simple_dict
from xpra.codecs.codec_constants import video_spec
from xpra.gst_common import (
    import_gst, make_buffer, normv,
    STREAM_TYPE, BUFFER_FORMAT,
    )
from xpra.gst_pipeline import Pipeline, GST_FLOW_OK
from xpra.log import Logger
from gi.repository import GObject
from xpra.codecs.image_wrapper import ImageWrapper

Gst = import_gst()
log = Logger("encoder", "gstreamer")

#ENCODER_PLUGIN = "vaapih264enc"
#ENCODER_PLUGIN = "x264enc"
ENCODER_PLUGIN = os.environ.get("XPRA_GSTREAMER_ENCODER_PLUGIN", "x264enc")
DEFAULT_ENCODER_OPTIONS = {
    "vaapih264enc" : {
        #"max-bframes" : 0,
        #"tune"  : 3,    #low-power
        #"rate-control" : 4, #vbr
        "quality-level" : 6,
        },
    "x264enc" : {
        "speed-preset"  : "ultrafast",
        "tune"          : "zerolatency",
        "byte-stream"   : True,
        "threads"       : 1,
        "key-int-max"   : 15,
        "intra-refresh" : True,
        }
    }


def get_version():
    return (5, 0)

def get_type():
    return "gstreamer"

def get_info():
    return {"version"   : get_version()}

def get_encodings():
    return ("h264", )

def get_input_colorspaces(encoding):
    assert encoding in get_encodings()
    return ("BGRX", )
    #return ("YUV420P", "BGRX", )

def get_output_colorspaces(encoding, input_colorspace):
    assert encoding in get_encodings()
    assert input_colorspace in get_input_colorspaces(encoding)
    return ("YUV420P", )

def init_module():
    log("gstreamer.init_module()")

def cleanup_module():
    log("gstreamer.cleanup_module()")


def get_spec(encoding, colorspace):
    assert encoding in get_encodings(), "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in get_input_colorspaces(encoding), "invalid colorspace: %s (must be one of %s)" % (colorspace, get_input_colorspaces(encoding))
    cpu_cost = 100
    gpu_cost = 0
    return video_spec(encoding=encoding, input_colorspace=colorspace,
                      output_colorspaces=get_output_colorspaces(encoding, colorspace),
                      has_lossless_mode=False,
                      codec_class=Encoder, codec_type=get_type(),
                      quality=40, speed=40,
                      setup_cost=100, cpu_cost=cpu_cost, gpu_cost=gpu_cost,
                      width_mask=0xFFFE, height_mask=0xFFFE, max_w=4096, max_h=4096)


class Encoder(Pipeline):
    __gsignals__ = Pipeline.__generic_signals__.copy()
    """
    Dispatch video encoding to a gstreamer pipeline
    """
    def init_context(self, encoding, width, height, src_format, options=None):
        options = typedict(options or {})
        if encoding not in get_encodings():
            raise ValueError(f"invalid encoding {encoding!r}")
        self.encoding = encoding
        self.width = width
        self.height = height
        self.src_format = src_format
        self.dst_formats = options.strtupleget("dst-formats")
        self.frames = 0
        self.pipeline_str = ""
        self.frame_queue = Queue()
        if src_format in (
            "NV12",
            "RGBA", "BGRA", "ARGB", "ABGR",
            "RGB", "BGR",
            "RGB15", "RGB16", "BGR15",
            "r210",
            "BGRP", "RGBP",
            ):
            #identical name:
            gst_rgb_format = src_format
        else:
            #translate to gstreamer name:
            gst_rgb_format = {
            "YUV420P"   : "I420",
            "YUV444P"   : "Y444",
            "BGRX"      : "BGRx",
            "XRGB"      : "xRGB",
            "XBGR"      : "xBGR",
            "YUV400"    : "GRAY8",
            #"RGB8P"
            }[src_format] 
        CAPS = f"video/x-raw,width={self.width},height={self.height},format=(string){gst_rgb_format},framerate=30/1"
        #parse encoder plugin string:
        parts = ENCODER_PLUGIN.split(" ", 1)
        encoder = parts[0]
        encoder_options = DEFAULT_ENCODER_OPTIONS.get(encoder, {})
        if len(parts)==2:
            #override encoder options:
            encoder_options.update(parse_simple_dict(parts[1], " "))
        encoder_str = encoder
        if encoder_options:
            encoder_str += " "+" ".join(f"{k}={v}" for k,v in encoder_options.items())
        elements = [
            #"do-timestamp=1",
            f"appsrc name=src emit-signals=1 block=0 is-live=1 stream-type={STREAM_TYPE} format={BUFFER_FORMAT} caps={CAPS}",
            #f"capsfilter 'video/x-raw,format=(string){self.src_format},width={self.width},height={self.height},framerate=(fraction)30/1'",
            #f"capsfilter caps=video/x-raw,format={src_format},width={self.width},height={self.height}",
            "queue max-size-buffers=2",
            "videoconvert",
            encoder_str,
            #mp4mux
            "appsink name=sink emit-signals=true max-buffers=10 drop=true sync=false async=false qos=false",
            ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")
        self.src    = self.pipeline.get_by_name("src")
        self.src.set_property("format", Gst.Format.TIME)
        #self.src.set_caps(Gst.Caps.from_string(CAPS))
        self.sink   = self.pipeline.get_by_name("sink")
        self.sink.connect("new-sample", self.on_new_sample)
        self.sink.connect("new-preroll", self.on_new_preroll)
        self.start()

    def on_new_preroll(self, _appsink):
        log("new-preroll")
        return GST_FLOW_OK

    def is_ready(self):
        return True

    def get_info(self) -> dict:
        info = get_info()
        if self.src_format is None:
            return info
        info.update({
            "frames"    : self.frames,
            "width"     : self.width,
            "height"    : self.height,
            "encoding"  : self.encoding,
            "src_format": self.src_format,
            "dst_formats" : self.dst_formats,
            "version"   : get_version(),
            })
        return info

    def __repr__(self):
        if self.src_format is None:
            return "gstreamer(uninitialized)"
        return f"gstreamer({self.src_format} - {self.width}x{self.height})"

    def is_closed(self):
        return self.src_format is None

    def get_encoding(self):
        return self.encoding

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):
        return "gstreamer"

    def get_src_format(self):
        return self.src_format

    def clean(self):
        super().stop()
        self.width = 0
        self.height = 0
        self.src_format = None
        self.encoding = ""
        self.src_format = ""
        self.dst_formats = []
        self.frames = 0


    def do_emit_info(self):
        pass


    def on_new_sample(self, _bus):
        sample = self.sink.emit("pull-sample")
        buf = sample.get_buffer()
        size = buf.get_size()
        log("on_new_sample size=%s", size)
        if size:
            data = buf.extract_dup(0, size)
            client_info = {}
            pts = normv(buf.pts)
            if pts>=0:
                client_info["timestamp"] = pts
            duration = normv(buf.duration)
            if duration>=0:
                client_info["duration"] = duration
            qs = self.frame_queue.qsize()
            if qs>0:
                client_info["delayed"] = qs
            self.frame_queue.put((data, client_info))
        return GST_FLOW_OK

    def compress_image(self, image, options=None):
        if image.get_planes()==ImageWrapper.PACKED:
            data = image.get_pixels()
        else:
            data = b"".join(image.get_pixels())
        log(f"compress_image({image}, {options}) state={self.state} pixel buffer size={len(data)}")
        if self.state in ("stopped", "error"):
            log(f"pipeline is in {self.state} state, dropping buffer")
            return None
        buf = make_buffer(data)
        duration = normv(0)
        if duration>0:
            buf.duration = duration
        #buf.size = size
        #buf.timestamp = timestamp
        #buf.offset = offset
        #buf.offset_end = offset_end
        r = self.src.emit("push-buffer", buf)
        if r!=GST_FLOW_OK:
            log.error("Error: unable to push image buffer")
            return None
        try:
            r = self.frame_queue.get(timeout=0.5)
            self.frames += 1
            return r
        except Empty:
            log.error("Error: frame queue timeout")
            return None

GObject.type_register(Encoder)
