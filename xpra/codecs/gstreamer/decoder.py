# This file is part of Xpra.
# Copyright (C) 2014-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from gi.repository import GObject  # @UnresolvedImport
from typing import Dict, Tuple, Any

from xpra.gst_common import (
    GST_FLOW_OK, STREAM_TYPE, GST_FORMAT_BYTES,
    make_buffer, has_plugins,
    get_caps_str,
    )
from xpra.codecs.gstreamer.codec_common import (
    VideoPipeline,
    get_version, get_type, get_info,
    init_module, cleanup_module,
    get_default_decoder_options,
    )
from xpra.os_util import WIN32
from xpra.util import roundup, typedict
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger

log = Logger("decoder", "gstreamer")

log(f"decoder: {get_type()} {get_version()}, {init_module}, {cleanup_module}")

FORMATS = os.environ.get("XPRA_GSTREAMER_DECODER_FORMATS", "h264,hevc,vp8,vp9,av1").split(",")


def get_default_mappings() -> Dict[str,Tuple[str,...]]:
    #should always be available:
    m : Dict[str,Tuple[str,...]] = {
        "vp8"   : ("vp8dec", ),
        "vp9"   : ("vp9dec", ),
        }
    if WIN32:
        m["h264"] = ("d3d11h264dec", )
    else:
        m["av1"] = ("av1dec", )
        #enable nv decoder unless we don't find nvidia hardware:
        h264 = ["nvh264dec"]
        try:
            from xpra.codecs.nvidia.nv_util import has_nvidia_hardware
            if not has_nvidia_hardware():
                h264 = []
        except ImportError:
            pass
        h264.append("avdec_h264")
        m["h264"] = tuple(h264)
        m["hevc"] = ("vaapih265dec", )
    return m


def get_codecs_options() -> Dict[str,Tuple[str,...]]:
    dm = os.environ.get("XPRA_GSTREAMER_DECODER_MAPPINGS")
    if not dm:
        return get_default_mappings()
    codec_options = {}
    for mapping in dm.split(";"):   #ie: mapping="vp8:vp8dec"
        try:
            enc, elements_str = mapping.split(":", 1)
        except IndexError:
            log.warn(f"Warning: invalid decoder mapping {mapping}")
        else:
            #ie: codec_options["h264"] = ["avdec_h264", "nvh264dec"]
            codec_options[enc] = tuple(elements_str.split(","))
    return codec_options

def find_codecs(options) -> Dict[str,str]:
    codecs : Dict[str,str] = {}
    for encoding, elements in options.items():
        if encoding in FORMATS and elements:
            found = [x for x in elements if has_plugins(x)]
            if found:
                codecs[encoding] = found[0]
    log(f"find_codecs({options})={codecs}")
    return codecs


CODECS = find_codecs(get_codecs_options())


def get_encodings() -> Tuple[str,...]:
    return tuple(CODECS.keys())

def get_min_size(_encoding:str):
    return 48, 16

def get_input_colorspaces(encoding:str) -> Tuple[str,...]:
    if encoding not in CODECS:
        raise ValueError(f"unsupported encoding {encoding}")
    return ("YUV420P", )
    #return ("YUV420P", "BGRX", )

def get_output_colorspace(encoding:str, input_colorspace:str) -> str:
    encoder = CODECS.get(encoding)
    if not encoder:
        raise ValueError(f"unsupported encoding {encoding}")
    assert input_colorspace in get_input_colorspaces(encoding)
    if encoder.startswith("nv"):
        return "NV12"
    return "YUV420P"


class Decoder(VideoPipeline):
    __gsignals__ : Dict[str,Tuple] = VideoPipeline.__generic_signals__.copy()
    """
    Dispatch video decoding to a gstreamer pipeline
    """
    def create_pipeline(self, options:typedict):
        if self.encoding not in get_encodings():
            raise ValueError(f"invalid encoding {self.encoding!r}")
        self.dst_formats = options.strtupleget("dst-formats")
        decoder = CODECS.get(self.encoding)
        if not decoder:
            raise RuntimeError(f"invalid encoding {self.encoding}")
        stream_attrs : Dict[str,Any] = {
            "width"     : self.width,
            "height"    : self.height,
            }
        eopts = get_default_decoder_options().get(decoder, {})
        if not eopts:
            eopts = {
                "profile"       : "main",
                "stream-format" : "byte-stream",
                "alignment"     : "au",
            }
        for k,v in eopts.items():
            stream_attrs[k] = options.strget(k, v)
        stream_caps = get_caps_str(f"video/x-{self.encoding}", stream_attrs)
        if decoder.startswith("nv"):
            gst_format = "NV12"
            self.output_format = "NV12"
        else:
            gst_format = "I420"
            self.output_format = "YUV420P"
        output_caps = get_caps_str("video/x-raw", {
            "width" : self.width,
            "height" : self.height,
            "format" : gst_format,
            })
        elements = [
            f"appsrc name=src emit-signals=1 block=0 is-live=1 do-timestamp=1 stream-type={STREAM_TYPE} format={GST_FORMAT_BYTES} caps={stream_caps}",
            f"{decoder} name=decoder",
            f"appsink name=sink emit-signals=1 max-buffers=10 drop=false sync=false async=true qos=false caps={output_caps}",
            ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")

    def get_colorspace(self) -> str:
        return self.colorspace

    def on_new_sample(self, _bus) -> int:
        sample = self.sink.emit("pull-sample")
        buf = sample.get_buffer()
        size = buf.get_size()
        log("on_new_sample size=%s, output_format=%s", size, self.output_format)
        if size:
            mem = memoryview(buf.extract_dup(0, size))
            #I420 gstreamer definition:
            Ystride = roundup(self.width, 4)
            Ysize = Ystride*roundup(self.height, 2)
            Y = mem[:Ysize]
            planes : Tuple[memoryview,...]
            strides : Tuple[int,...]
            if self.output_format=="YUV420P":
                UVstride = roundup(roundup(self.width, 2)//2, 4)
                UVsize = UVstride*roundup(self.height, 2)//2
                total = Ysize+2*UVsize
                if size<total:
                    raise RuntimeError(f"I420 sample buffer is too small: expected {total} but got {size}")
                U = mem[Ysize:Ysize+UVsize]
                V = mem[Ysize+UVsize:total]
                planes = (Y, U, V)
                strides = (Ystride, UVstride, UVstride)
            else:
                UVstride = roundup(self.width, 4)
                UVsize = UVstride*roundup(self.height, 2)//2
                UV = mem[Ysize:Ysize+UVsize]
                planes = (Y, UV)
                strides = (Ystride, UVstride)
            image = ImageWrapper(0, 0, self.width, self.height, planes,
                                 self.output_format, 24, strides, 3, ImageWrapper.PLANAR_3)
            self.frame_queue.put(image)
        return GST_FLOW_OK


    def decompress_image(self, data:bytes, options=None):
        log(f"decompress_image(.., {options}) state={self.state} data size={len(data)}")
        if self.state in ("stopped", "error"):
            log(f"pipeline is in {self.state} state, dropping buffer")
            return None
        buf = make_buffer(data)
        #duration = normv(0)
        #if duration>0:
        #    buf.duration = duration
        #buf.size = size
        #buf.timestamp = timestamp
        #buf.offset = offset
        #buf.offset_end = offset_end
        return self.process_buffer(buf)

GObject.type_register(Decoder)


def selftest(full=False):
    log("gstreamer decoder selftest: %s", get_info())
    from xpra.codecs.codec_checks import testdecoder
    from xpra.codecs.gstreamer import decoder
    remaining = testdecoder(decoder, full)
    decoder.CODECS = dict((k,v) for k,v in decoder.CODECS.items() if k in remaining)
