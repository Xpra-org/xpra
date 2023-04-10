# This file is part of Xpra.
# Copyright (C) 2014-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from gi.repository import GObject  # @UnresolvedImport

from xpra.gst_common import (
    GST_FLOW_OK, STREAM_TYPE, GST_FORMAT_BYTES,
    make_buffer, has_plugins,
    get_caps_str, get_element_str,
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


DEFAULT_MAPPINGS = "vp8:vp8dec,vp9:vp9dec"
if not WIN32:
    DEFAULT_MAPPINGS += ",av1:av1dec,h264:avdec_h264"

def get_codecs_options():
    dm = os.environ.get("XPRA_GSTREAMER_DECODER_MAPPINGS", DEFAULT_MAPPINGS)
    codec_options = {}
    for mapping in dm.split(","):   #ie: mapping="vp8:vp8dec"
        try:
            enc, element = mapping.split(":", 1)
        except IndexError:
            log.warn(f"Warning: invalid decoder mapping {mapping}")
        else:
            codec_options[enc] = element    #ie: codec_options["vp8"] = "vp8dec"
    return codec_options

def find_codecs(options):
    codecs = []
    for encoding, element in options.items():
        if has_plugins(element):
            codecs.append(encoding)
    return tuple(codecs)

CODECS = find_codecs(get_codecs_options())


def get_encodings():
    return CODECS

def get_min_size(encoding):
    return 16, 16

def get_input_colorspaces(encoding):
    assert encoding in get_encodings()
    return ("YUV420P", )
    #return ("YUV420P", "BGRX", )

def get_output_colorspace(encoding, input_colorspace):
    assert encoding in get_encodings()
    assert input_colorspace in get_input_colorspaces(encoding)
    return "YUV420P"


class Decoder(VideoPipeline):
    __gsignals__ = VideoPipeline.__generic_signals__.copy()
    """
    Dispatch video decoding to a gstreamer pipeline
    """
    def create_pipeline(self, options):
        if self.encoding not in get_encodings():
            raise ValueError(f"invalid encoding {self.encoding!r}")
        self.dst_formats = options.strtupleget("dst-formats")
        stream_attrs = {
            "width"     : self.width,
            "height"    : self.height,
            }
        decoder_element = f"{self.encoding}dec"
        if self.encoding in ("vp8", "vp9", "av1"):
            pass
        elif self.encoding=="h264" and not WIN32:
            for k,v in {
                "profile"       : "main",
                "stream-format" : "byte-stream",
                "alignment"     : "au",
                }.items():
                stream_attrs[k] = options.strget(k, v)
            #decode = ["vaapih264dec"]
            #decode = ["openh264dec"]
            decoder_element = f"avdec_{self.encoding}"
        else:
            raise RuntimeError(f"invalid encoding {self.encoding}")
        stream_caps = get_caps_str(f"video/x-{self.encoding}", stream_attrs)
        gst_rgb_format = "I420"
        output_caps = get_caps_str("video/x-raw", {
            "width" : self.width,
            "height" : self.height,
            "format" : gst_rgb_format,
            })
        elements = [
            #"do-timestamp=1",
            f"appsrc name=src emit-signals=1 block=0 is-live=1 do-timestamp=1 stream-type={STREAM_TYPE} format={GST_FORMAT_BYTES} caps={stream_caps}",
            decoder_element,
            f"appsink name=sink emit-signals=true max-buffers=10 drop=true sync=false async=false qos=false caps={output_caps}",
            ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")

    def get_colorspace(self):
        return self.colorspace

    def on_new_sample(self, _bus):
        sample = self.sink.emit("pull-sample")
        buf = sample.get_buffer()
        size = buf.get_size()
        log("on_new_sample size=%s", size)
        if size:
            mem = memoryview(buf.extract_dup(0, size))
            #I420 gstreamer definition:
            Ystride = roundup(self.width, 4)
            Ysize = Ystride*roundup(self.height, 2)
            UVstride = roundup(roundup(self.width, 2)//2, 4)
            UVsize = UVstride*roundup(self.height, 2)//2
            total = Ysize+2*UVsize
            if size<total:
                raise RuntimeError(f"I420 sample buffer is too small: expected {total} but got {size}")
            Y = mem[:Ysize]
            U = mem[Ysize:Ysize+UVsize]
            V = mem[Ysize+UVsize:total]
            strides = (Ystride, UVstride, UVstride)
            image = ImageWrapper(0, 0, self.width, self.height, (Y, U, V), "YUV420P", 24, strides, 3, ImageWrapper.PLANAR_3)
            self.frame_queue.put(image)
        return GST_FLOW_OK


    def decompress_image(self, data, options=None):
        log(f"decompress_image(..) state={self.state} data size={len(data)}")
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
    decoder.CODECS = testdecoder(decoder, full)
