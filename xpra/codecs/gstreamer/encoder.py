# This file is part of Xpra.
# Copyright (C) 2022-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from gi.repository import GObject  # @UnresolvedImport

from xpra.os_util import WIN32, OSX
from xpra.util import parse_simple_dict, envbool, csv
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


assert get_version and init_module and cleanup_module
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
    "vp8enc" : {
        "deadline"      : 1,
        "error-resilient" : 0,
        },
    "vp9enc" : {
        "deadline"      : 1,
        "error-resilient" : 0,
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


COLORSPACES = {}
def get_encodings():
    return tuple(COLORSPACES.keys())

def get_input_colorspaces(encoding):
    colorspaces = COLORSPACES.get(encoding)
    assert colorspaces, f"invalid input colorspace for {encoding}"
    return tuple(colorspaces.keys())

def get_output_colorspaces(encoding, input_colorspace):
    colorspaces = COLORSPACES.get(encoding)
    assert colorspaces, f"invalid input colorspace for {encoding}"
    out_colorspaces = colorspaces.get(input_colorspace)
    assert out_colorspaces, f"invalid input colorspace {input_colorspace} for {encoding}"
    return out_colorspaces

def make_spec(element, encoding, cs_in, css_out, cpu_cost=50, gpu_cost=50):
    def factory():
        #let the user override options using an env var:
        enc_options_str = os.environ.get(f"XPRA_{element.upper()}_OPTIONS", "")
        if enc_options_str:
            encoder_options = parse_simple_dict(enc_options_str)
            log(f"user overriden options for {element}: {encoder_options}")
        else:
            encoder_options = dict(DEFAULT_ENCODER_OPTIONS.get(element, {}))
        e = Encoder()
        e.encoder_element = element
        e.encoder_options = encoder_options or {}
        return e
    spec = video_spec(
        encoding=encoding, input_colorspace=cs_in,
        output_colorspaces=css_out,
        has_lossless_mode=False,
        codec_class=factory, codec_type=get_type(),
        quality=40, speed=40,
        setup_cost=100, cpu_cost=cpu_cost, gpu_cost=gpu_cost,
        width_mask=0xFFFE, height_mask=0xFFFE,
        min_w=64, min_h=64,
        max_w=4096, max_h=4096)
    spec.gstreamer_element = element
    return spec

SPECS = {}
def get_specs(encoding, colorspace):
    colorspaces = SPECS.get(encoding)
    assert colorspaces, f"invalid encoding: {encoding} (must be one of %s)" % csv(SPECS.keys())
    assert colorspace in colorspaces, f"invalid colorspace: {colorspace} (must be one of %s)" % csv(colorspaces.keys())
    return colorspaces.get(colorspace)

def init_all_specs(*exclude):
    #by default, try to enable everything
    #the self-tests should disable what isn't available / doesn't work
    specs = {}
    colorspaces = {}
    def add(element, encoding, cs_in, css_out, *args):
        if element in exclude:
            return
        #add spec:
        spec = make_spec(element, encoding, cs_in, css_out, *args)
        specs.setdefault(encoding, {}).setdefault(cs_in, []).append(spec)
        #update colorspaces map (add new output colorspaces - if any):
        cur = colorspaces.setdefault(encoding, {}).setdefault(cs_in, [])
        for v in css_out:
            if v not in cur:
                cur.append(v)
    vaapi = False
    if NVIDIA_VAAPI:
        try:
            from xpra.codecs.nvidia.nv_util import has_nvidia_hardware
            vaapi = not has_nvidia_hardware()
        except ImportError:
            pass
    if vaapi:
        add("vaapih264enc", "h264", "YUV420P", ("YUV420P", ), 20, 100)
    add("x264enc", "h264", "YUV420P", ("YUV420P", ), 100, 0)
    add("x264enc", "h264", "BGRX", ("YUV444P", ), 100, 0)
    add("vp8enc", "vp8", "YUV420P", ("YUV420P", ), 100, 0)
    add("vp9enc", "vp9", "YUV444P", ("YUV444P", ), 100, 0)
    #add: nvh264enc, nvh265enc ?
    global SPECS, COLORSPACES
    SPECS = specs
    COLORSPACES = colorspaces
    log("init_all_specs%s SPECS=%s", exclude, SPECS)
    log("init_all_specs%s COLORSPACES=%s", exclude, COLORSPACES)
init_all_specs()


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
        encoder_str = self.encoder_element
        if self.encoder_options:
            encoder_str += " "+" ".join(f"{k}={v}" for k,v in self.encoder_options.items())
        elements = [
            #"do-timestamp=1",
            f"appsrc name=src emit-signals=1 block=0 is-live=1 stream-type={STREAM_TYPE} format={BUFFER_FORMAT} caps={CAPS}",
            "videoconvert",
            encoder_str,
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
    from xpra.codecs.codec_checks import test_encoder_spec, DEFAULT_TEST_SIZE
    W, H = DEFAULT_TEST_SIZE
    #test individual specs
    skip = []
    log(f"will self test: {SPECS}")
    for encoding, cs_map in SPECS.items():
        for cs_in, specs in cs_map.items():
            for spec in specs:
                try:
                    test_encoder_spec(spec.codec_class, encoding, cs_in, spec.output_colorspaces, W, H)
                    log(f"{spec.gstreamer_element} {encoding} {cs_in} -> {spec.output_colorspaces} passed")
                except Exception as e:
                    log("test_encoder_spec", exc_info=True)
                    log.warn(f"Warning: gstreamer {spec.gstreamer_element!r} encoder failed")
                    log.warn(f" {e}")
                    skip.append(spec.gstreamer_element)
    init_all_specs(*skip)
