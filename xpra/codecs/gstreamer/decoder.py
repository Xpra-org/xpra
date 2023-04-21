# This file is part of Xpra.
# Copyright (C) 2014-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from gi.repository import GObject  # @UnresolvedImport

from xpra.gst_common import (
    GST_FLOW_OK, STREAM_TYPE, GST_FORMAT_BYTES,
    make_buffer, has_plugins,
    get_caps_str,
    )
from xpra.codecs.gstreamer.codec_common import (
    VideoPipeline,
    get_version, get_type, get_info,
    init_module, cleanup_module,
    )
from xpra.os_util import WIN32
from xpra.util import roundup
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger

log = Logger("decoder", "gstreamer")

assert get_version and get_type and init_module and cleanup_module


DEFAULT_MAPPINGS = "vp8:vp8dec;vp9:vp9dec"
if not WIN32:
    #enable nv decoder unless we don't find nvidia hardware:
    h264 = "nvh264dec,"
    try:
        from xpra.codecs.nvidia.nv_util import has_nvidia_hardware
        if not has_nvidia_hardware():
            h264 = ""
    except ImportError:
        pass
    h264 += "avdec_h264"
    DEFAULT_MAPPINGS += f";av1:av1dec;h264:{h264};hevc:vaapih265dec"

def get_codecs_options():
    dm = os.environ.get("XPRA_GSTREAMER_DECODER_MAPPINGS", DEFAULT_MAPPINGS)
    codec_options = {}
    for mapping in dm.split(";"):   #ie: mapping="vp8:vp8dec"
        try:
            enc, elements_str = mapping.split(":", 1)
        except IndexError:
            log.warn(f"Warning: invalid decoder mapping {mapping}")
        else:
            #ie: codec_options["h264"] = ["avdec_h264", "nvh264dec"]
            codec_options[enc] = elements_str.split(",")
    return codec_options

def find_codecs(options):
    codecs = {}
    for encoding, elements in options.items():
        for element in elements:
            if has_plugins(element):
                codecs[encoding] = element
                break
    log(f"find_codecs({options})={codecs}")
    return codecs

CODECS = find_codecs(get_codecs_options())


def get_encodings() -> tuple:
    return tuple(CODECS.keys())

def get_min_size(encoding):
    return 48, 16

def get_input_colorspaces(encoding) -> tuple:
    if encoding not in CODECS:
        raise ValueError(f"unsupported encoding {encoding}")
    return ("YUV420P", )
    #return ("YUV420P", "BGRX", )

def get_output_colorspace(encoding, input_colorspace) -> str:
    encoder = CODECS.get(encoding)
    if not encoder:
        raise ValueError(f"unsupported encoding {encoding}")
    assert input_colorspace in get_input_colorspaces(encoding)
    if encoder.startswith("nv"):
        return "NV12"
    return "YUV420P"


class Decoder(VideoPipeline):
    __gsignals__ : dict = VideoPipeline.__generic_signals__.copy()
    """
    Dispatch video decoding to a gstreamer pipeline
    """
    def create_pipeline(self, options):
        if self.encoding not in get_encodings():
            raise ValueError(f"invalid encoding {self.encoding!r}")
        self.dst_formats = options.strtupleget("dst-formats")
        decoder_element = CODECS.get(self.encoding)
        if not decoder_element:
            raise RuntimeError(f"invalid encoding {self.encoding}")
        stream_attrs = {
            "width"     : self.width,
            "height"    : self.height,
            }
        for k,v in {
            "profile"       : "main",
            "stream-format" : "byte-stream",
            "alignment"     : "au",
            }.items():
            stream_attrs[k] = options.strget(k, v)
        stream_caps = get_caps_str(f"video/x-{self.encoding}", stream_attrs)
        if decoder_element.startswith("nv"):
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
            f"{decoder_element} name=decoder",
            f"appsink name=sink emit-signals=1 max-buffers=10 drop=false sync=false async=true qos=false caps={output_caps}",
            ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")

    def get_colorspace(self) -> str:
        return self.colorspace

    def on_new_sample(self, _bus):
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


    def decompress_image(self, data, options=None):
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
