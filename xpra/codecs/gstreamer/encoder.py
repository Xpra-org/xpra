# This file is part of Xpra.
# Copyright (C) 2014-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from gi.repository import GObject  # @UnresolvedImport

from xpra.util import parse_simple_dict, envbool
from xpra.codecs.codec_constants import video_spec
from xpra.gst_common import (
    import_gst, normv,
    STREAM_TYPE, BUFFER_FORMAT,
    )
from xpra.gst_pipeline import GST_FLOW_OK
from xpra.codecs.gstreamer.codec_common import (
    VideoPipeline,
    get_version, get_type, get_info,
    init_module, cleanup_module,
    )
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger

Gst = import_gst()
log = Logger("encoder", "gstreamer")

NVIDIA_VAAPI = envbool("XPRA_NVIDIA_VAAPI", False)
CODECS = os.environ.get("XPRA_GSTREAMER_ENCODINGS", "h264,av1").split(",")


assert get_version and init_module and cleanup_module
ENCODERS = {
    "h264"  : ("vaapih264enc", "x264enc"),
    "av1"   : ("av1enc", ),
    }
DEFAULT_ENCODER_OPTIONS = {
    "vaapih264enc" : {
        "max-bframes" : 0,
        "tune"  : 3,    #low-power
        #"rate-control" : 8, #qvbr
        "compliance-mode" : 1,  #restrict-buf-alloc (1) – Restrict the allocation size of coded-buffer
        #"keyframe-period"   : 9999,
        "prediction-type" : 1, #hierarchical-p (1) – Hierarchical P frame encode
        #"quality-factor" : 10,
        #"quality-level" : 50,
        #"bitrate"   : 2000,
        },
    "x264enc" : {
        "speed-preset"  : "ultrafast",
        "tune"          : "zerolatency",
        "byte-stream"   : True,
        "threads"       : 1,
        "key-int-max"   : 15,
        "intra-refresh" : True,
        },
    #"svtav1enc" : {
    #    "speed"         : 12,
    #    "gop-size"      : 251,
    #    "intra-refresh" : 1,    #open gop
    #    "lookahead"     : 0,
    #    "rc"            : 1,    #vbr
    #    },
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
    "av1enc" : {
        "cpu-used"          : 5,
        "end-usage"         : 2,    #cq
        }
    }


CODECS = ("h264", "av1")
def get_encodings():
    return CODECS

def get_input_colorspaces(encoding):
    assert encoding in get_encodings()
    return ("YUV420P", )
    #return ("YUV420P", "BGRX", )

def get_output_colorspaces(encoding, input_colorspace):
    assert encoding in get_encodings()
    assert input_colorspace in get_input_colorspaces(encoding)
    return ("YUV420P", )


def get_spec(encoding, colorspace):
    assert encoding in get_encodings(), "invalid encoding: %s (must be one of %s" % (encoding, get_encodings())
    assert colorspace in get_input_colorspaces(encoding), "invalid colorspace: %s (must be one of %s)" % (colorspace, get_input_colorspaces(encoding))
    cpu_cost = 20 if "vaapih264enc" else 100
    gpu_cost = 80 if "vaapih264enc" else 0
    return video_spec(encoding=encoding, input_colorspace=colorspace,
                      output_colorspaces=get_output_colorspaces(encoding, colorspace),
                      has_lossless_mode=False,
                      codec_class=Encoder, codec_type=get_type(),
                      quality=40, speed=40,
                      setup_cost=100, cpu_cost=cpu_cost, gpu_cost=gpu_cost,
                      width_mask=0xFFFE, height_mask=0xFFFE,
                      min_w=64, min_h=64,
                      max_w=4096, max_h=4096)


class Encoder(VideoPipeline):
    __gsignals__ = VideoPipeline.__generic_signals__.copy()
    """
    Dispatch video encoding to a gstreamer pipeline
    """
    def create_pipeline(self, options):
        if self.encoding not in get_encodings():
            raise ValueError(f"invalid encoding {self.encoding!r}")
        self.dst_formats = options.strtupleget("dst-formats")
        if self.colorspace in (
            "NV12",
            "RGBA", "BGRA", "ARGB", "ABGR",
            "RGB", "BGR",
            "RGB15", "RGB16", "BGR15",
            "r210",
            "BGRP", "RGBP",
            ):
            #identical name:
            gst_rgb_format = self.colorspace
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
            }[self.colorspace] 
        CAPS = f"video/x-raw,width={self.width},height={self.height},format=(string){gst_rgb_format},framerate=60/1,interlace=progressive"
        #parse encoder plugin string:
        encoder_options = list(ENCODERS.get(self.encoding, ()))
        encoder_str = os.environ.get("XPRA_GSTREAMER_ENCODER_PLUGIN")
        if not encoder_str:
            if not encoder_options:
                raise ValueError(f"{self.encoding} is not supported here")
            #choose the first option (ie: "vaapih264enc")
            # but skip 'vaapih264enc' on nvidia hardware:
            while encoder_options:
                encoder_str = encoder_options.pop(0)
                if NVIDIA_VAAPI or encoder_str!="vaapih264enc":
                    break
                try:
                    from xpra.codecs.nvidia.nv_util import has_nvidia_hardware
                    if not has_nvidia_hardware():
                        break
                except ImportError:
                    break
        parts = encoder_str.split(" ", 1)
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
            "videoconvert",
            encoder_str,
            #mp4mux
            "appsink name=sink emit-signals=true max-buffers=10 drop=true sync=false async=false qos=false",
            ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")

    def get_src_format(self):
        return self.colorspace

    def get_info(self) -> dict:
        info = super().get_info()
        if self.dst_formats:
            info["dst_formats"] = self.dst_formats
        return info


    def on_new_sample(self, _bus):
        sample = self.sink.emit("pull-sample")
        buf = sample.get_buffer()
        size = buf.get_size()
        log("on_new_sample size=%s", size)
        if size:
            data = buf.extract_dup(0, size)
            #log(" output=%s", hexstr(data))
            client_info = {
                "frame" : self.frames,
                }
            self.frames += 1
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
            #merge all planes into a single buffer:
            data = b"".join(image.get_pixels())
        log(f"compress_image({image}, {options}) state={self.state} pixel buffer size={len(data)}")
        if self.state in ("stopped", "error"):
            log(f"pipeline is in {self.state} state, dropping buffer")
            return None
        mf = Gst.MemoryFlags
        buf = Gst.Buffer.new_wrapped_full(
            mf.PHYSICALLY_CONTIGUOUS | mf.READONLY,
            data,
            len(data),
            0,
            None,
            None)
        #duration = normv(0)
        #if duration>0:
        #    buf.duration = duration
        #buf.size = size
        #buf.timestamp = timestamp
        #buf.offset = offset
        #buf.offset_end = offset_end
        return self.process_buffer(buf)

GObject.type_register(Encoder)


def selftest(full=False):
    log("gstreamer encoder selftest: %s", get_info())
    from xpra.codecs.codec_checks import testencoder
    from xpra.codecs.gstreamer import encoder
    encoder.CODECS = testencoder(encoder, full)
