# This file is part of Xpra.
# Copyright (C) 2022-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from gi.repository import GObject  # @UnresolvedImport

from xpra.os_util import WIN32, OSX
from xpra.util import parse_simple_dict, envbool, csv, roundup, first_time, typedict
from xpra.codecs.codec_constants import video_spec, get_profile, get_x264_quality, get_x264_preset
from xpra.gst_common import (
    import_gst, normv, get_all_plugin_names,
    get_caps_str, get_element_str, get_gst_rgb_format, wrap_buffer,
    STREAM_TYPE, BUFFER_FORMAT, GST_FLOW_OK,
    )
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
VAAPI = envbool("XPRA_GSTREAMER_VAAPI", not (WIN32 or OSX))
NVENC = envbool("XPRA_GSTREAMER_NVENC", False)
FORMATS = os.environ.get("XPRA_GSTREAMER_ENCODER_FORMATS", "h264,hevc,vp8,vp9,av1").split(",")

assert get_version and init_module and cleanup_module
DEFAULT_ENCODER_OPTIONS = {
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
    #    "speed"         : 12,
    #    "gop-size"      : 251,
        "intra-refresh" : 1,    #open gop
    #    "lookahead"     : 0,
    #    "rc"            : 1,    #vbr
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
    DEFAULT_ENCODER_OPTIONS["av1enc"] = {
        "cpu-used"          : 5,
        "end-usage"         : 2,    #cq
        }

PACKED_RGB_FORMATS = ("RGBA", "BGRA", "ARGB", "ABGR", "RGB", "BGR", "BGRX", "XRGB", "XBGR")

assert get_type #all codecs must define this function
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

def ElementEncoderClass(element, options=None):
    class ElementEncoder(Encoder):
        pass
    ElementEncoder.encoder_element = element
    ElementEncoder.encoder_options = options or {}
    return ElementEncoder

def make_spec(element, encoding, cs_in, css_out, cpu_cost=50, gpu_cost=50):
    #use a metaclass so all encoders are gstreamer.encoder.Encoder subclasses,
    #each with different pipeline arguments based on the make_spec parameters:
    enc_options_str = os.environ.get(f"XPRA_{element.upper()}_OPTIONS", "")
    if enc_options_str:
        encoder_options = parse_simple_dict(enc_options_str)
        log(f"user overridden options for {element}: {encoder_options}")
    else:
        encoder_options = dict(DEFAULT_ENCODER_OPTIONS.get(element, {}))
    if cs_in in PACKED_RGB_FORMATS:
        width_mask = height_mask = 0xFFFF
    else:
        width_mask = height_mask = 0xFFFE
    spec = video_spec(
        encoding=encoding, input_colorspace=cs_in,
        output_colorspaces=css_out,
        has_lossless_mode=False,
        codec_class=ElementEncoderClass(element, encoder_options), codec_type=f"gstreamer-{element}",
        quality=40, speed=40,
        setup_cost=100, cpu_cost=cpu_cost, gpu_cost=gpu_cost,
        width_mask=width_mask, height_mask=height_mask,
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
    missing = []
    def add(element, encoding, cs_in, css_out, *args):
        if element in missing:
            return
        if encoding not in FORMATS:
            log(f"{encoding} not enabled - supported formats: {FORMATS}")
            return
        if element in exclude:
            return
        if element not in get_all_plugin_names():
            missing.append(element)
            return
        #add spec:
        css_out = css_out or (cs_in, )
        spec = make_spec(element, encoding, cs_in, css_out, *args)
        specs.setdefault(encoding, {}).setdefault(cs_in, []).append(spec)
        #update colorspaces map (add new output colorspaces - if any):
        cur = colorspaces.setdefault(encoding, {}).setdefault(cs_in, [])
        for v in css_out:
            if v not in cur:
                cur.append(v)
    vaapi = VAAPI
    if VAAPI and not NVIDIA_VAAPI:
        try:
            from xpra.codecs.nvidia.nv_util import has_nvidia_hardware
            vaapi = not has_nvidia_hardware()
        except ImportError:
            pass
    log(f"init_all_specs try vaapi? {vaapi}")
    if vaapi:
        add("vaapih264enc", "h264", "NV12", ("YUV420P", ), 20, 100)
        add("vaapih265enc", "hevc", "NV12", ("YUV420P", ), 20, 100)
    if WIN32:
        add("nvd3d11h264enc", "h264", "YUV420P", ("YUV420P", ), 20, 100)
        add("nvd3d11h265enc", "hevc", "YUV420P", ("YUV420P", ), 20, 100)
    if NVENC:
        add("nvh264enc", "h264", "YUV420P", ("YUV420P", ), 20, 100)
        add("nvh265enc", "hevc", "YUV420P", ("YUV420P", ), 20, 100)
    add("x264enc", "h264", "YUV420P", ("YUV420P", ), 100, 0)
    add("x264enc", "h264", "YUV444P", ("YUV444P", ), 100, 0)
    add("vp8enc", "vp8", "YUV420P", ("YUV420P", ), 100, 0)
    add("vp9enc", "vp9", "YUV444P", ("YUV444P", ), 100, 0)
    add("av1enc", "av1", "YUV420P", ("YUV420P", ), 100, 0)
    add("av1enc", "av1", "YUV444P", ("YUV444P", ), 100, 0)
    #svt encoders error out:
    #add("svtav1enc", "av1", "YUV420P", ("YUV420P", ), 100, 0)
    #add("svtvp9enc", "vp9", "YUV420P", ("YUV420P", ), 100, 0)
    #add: nvh264enc, nvh265enc ?
    global SPECS, COLORSPACES
    SPECS = specs
    COLORSPACES = colorspaces
    log("init_all_specs%s SPECS=%s", exclude, SPECS)
    log("init_all_specs%s COLORSPACES=%s", exclude, COLORSPACES)
    if missing and first_time("gstreamer-encoder-missing-elements"):
        log.info("some GStreamer elements are missing or unavailable on this system:")
        log.info(" "+csv(missing))


class Encoder(VideoPipeline):
    __gsignals__ = VideoPipeline.__generic_signals__.copy()
    encoder_element = "unset"

    def __repr__(self):
        if self.colorspace is None:
            return f"gstreamer-{self.encoder_element}(uninitialized)"
        return f"gstreamer-{self.encoder_element}({self.colorspace} - {self.width}x{self.height})"

    """
    Dispatch video encoding to a gstreamer pipeline
    """
    def create_pipeline(self, options : typedict):
        if self.encoding not in get_encodings():
            raise ValueError(f"invalid encoding {self.encoding!r}")
        self.extra_client_info = {}
        self.dst_formats = options.strtupleget("dst-formats")
        gst_rgb_format = get_gst_rgb_format(self.colorspace)
        vcaps = {
            "width" : self.width,
            "height" : self.height,
            "format" : gst_rgb_format,
            "framerate" : (60,1),
            "interlace" : "progressive",
            "colorimetry" : "bt709",
            }
        CAPS = get_caps_str("video/x-raw", vcaps)
        eopts, vopts = self.get_encoder_options(options)
        self.extra_client_info = vopts.copy()
        gst_encoding = {
            "hevc"  : "h265",
            }.get(self.encoding, self.encoding)
        appsrc_opts = {
            "name"          : "src",
            "emit-signals"  : 0,
            "do-timestamp"  : 1,
            "block"         : 0,
            "is-live"       : 1,
            "stream-type"   : STREAM_TYPE,
            "format"        : BUFFER_FORMAT,
            "caps"          : CAPS,
            #"leaky-type"    : 0,        #default is 0 and this is not available before GStreamer 1.20
            }
        elements = [
            get_element_str("appsrc", appsrc_opts),
            get_element_str(self.encoder_element, eopts),
            get_caps_str(f"video/x-{gst_encoding}", vopts),
            ]
        elements.append("appsink name=sink emit-signals=true max-buffers=10 drop=false sync=false async=false qos=true")
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")

    def get_encoder_options(self, options:typedict):
        eopts = self.encoder_options.copy()
        eopts["name"] = "encoder"
        if self.encoder_element=="av1enc":
            vopts = {
                "alignment"     : "tu",
                "stream-format" : "obu-stream",
                }
        else:
            vopts = {
                "alignment"     : "au",
                "stream-format" : "byte-stream",
                }
        default_profile = {
            #"x264enc"   : "constrained-baseline",
            #"vaapih264enc" : "constrained-baseline",
            #"nvh264enc" : "main",
            "vp8enc"   : None, #0-4
            "vp9enc"   : None, #0-4
            }.get(self.encoder_element)
        profile = get_profile(options, self.encoding, self.colorspace, default_profile)
        if profile:
            vopts["profile"] = profile
        if self.encoder_element=="x264enc":
            q = get_x264_quality(options.intget("quality", 50), profile)
            s = options.intget("speed", 50)
            eopts.update({
                "pass"  : "qual",
                "quantizer" : q,
                "speed-preset" : get_x264_preset(s),
                })
            vopts.update(self.extra_client_info)
        #if "bframes" in self.encoder_options:
        #    eopts["bframes"] = int(options.boolget("b-frames", False))
        return eopts, vopts

    def get_src_format(self):
        return self.colorspace

    def get_info(self) -> dict:
        info = super().get_info()
        if self.dst_formats:
            info["dst_formats"] = self.dst_formats
        return info

    def clean(self):
        self.cleanup()


    def on_new_sample(self, _bus) -> int:
        sample = self.sink.emit("pull-sample")
        buf = sample.get_buffer()
        size = buf.get_size()
        log("on_new_sample size=%s", size)
        if size:
            data = buf.extract_dup(0, size)
            client_info = self.extra_client_info
            self.extra_client_info = {}
            client_info["frame"] = self.frames
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
            log(f"added data to frame queue, client_info={client_info}")
        return GST_FLOW_OK

    def compress_image(self, image, options=None):
        if image.get_planes()==ImageWrapper.PACKED:
            data = image.get_pixels()
            rowstride = image.get_rowstride()
            want_rowstride = roundup(self.width, 2)*len(self.colorspace)
            if rowstride!=want_rowstride and not image.restride(want_rowstride):
                raise RuntimeError(f"failed to restride image from {rowstride}to {want_rowstride}")
        else:
            #merge all planes into a single buffer:
            data = b"".join(image.get_pixels())
        log(f"compress_image({image}, {options}) state={self.state} pixel buffer size={len(data)}")
        if self.state in ("stopped", "error"):
            log(f"pipeline is in {self.state} state, dropping buffer")
            return None
        return self.process_buffer(wrap_buffer(data))

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

init_all_specs()
