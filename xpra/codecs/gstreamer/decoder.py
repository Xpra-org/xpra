# This file is part of Xpra.
# Copyright (C) 2014-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from gi.repository import GObject

from xpra.gst_common import STREAM_TYPE, GST_FORMAT_BYTES, make_buffer
from xpra.gst_pipeline import GST_FLOW_OK
from xpra.codecs.gstreamer.codec_common import (
    VideoPipeline,
    get_version, get_type, get_info,
    init_module, cleanup_module,
    )
from xpra.util import roundup
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger

log = Logger("decoder", "gstreamer")

assert get_version and get_type and init_module and cleanup_module


CODECS = ("vp8", "h264", "av1")
def get_encodings():
    return CODECS

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
        gst_rgb_format = "I420"
        IMAGE_CAPS = f"video/x-raw,width={self.width},height={self.height},format=(string){gst_rgb_format}"
        if self.encoding=="vp8":
            stream_caps = f"video/x-vp8,width={self.width},height={self.height}"
            decode = ["vp8dec"]
        elif self.encoding=="h264":
            stream_caps = f"video/x-h264,profile=main,stream-format=avc,alignment=au,width={self.width},height={self.height}"
            #decode = ["vaapih264dec"]
            #decode = ["openh264dec"]
            decode = ["avdec_h264"]
        elif self.encoding=="av1":
            stream_caps = f"video/x-av1,width={self.width},height={self.height}"
            decode = ["av1dec"]
        else:
            raise RuntimeError(f"invalid encoding {self.encoding}")
        elements = [
            #"do-timestamp=1",
            f"appsrc name=src emit-signals=1 block=0 is-live=1 do-timestamp=1 stream-type={STREAM_TYPE} format={GST_FORMAT_BYTES} caps={stream_caps}"
            ] + decode + [
            f"appsink name=sink emit-signals=true max-buffers=10 drop=true sync=false async=false qos=false caps={IMAGE_CAPS}",
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
