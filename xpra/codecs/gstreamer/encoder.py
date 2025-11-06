# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Sequence

from xpra.os_util import WIN32, OSX, gi_import
from xpra.common import roundup
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envbool, first_time
from xpra.codecs.constants import VideoSpec, get_profile
from xpra.gstreamer.common import (
    import_gst, normv, get_all_plugin_names,
    get_caps_str, get_element_str,
    get_default_appsink_attributes, get_default_appsrc_attributes,
    BUFFER_FORMAT, GST_FLOW_OK,
)
from xpra.codecs.gstreamer.common import (
    VideoPipeline,
    get_version, get_type, get_info,
    get_gst_encoding, get_gst_rgb_format, get_video_encoder_caps,
    get_video_encoder_options,
)
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger

GObject = gi_import("GObject")
Gst = import_gst()
log = Logger("encoder", "gstreamer")

NVIDIA_VAAPI = envbool("XPRA_NVIDIA_VAAPI", False)
VAAPI = envbool("XPRA_GSTREAMER_VAAPI", not (WIN32 or OSX))
NVENC = envbool("XPRA_GSTREAMER_NVENC", False)
NVD3D11 = envbool("XPRA_GSTREAMER_NVD3D11", WIN32)
FORMATS = os.environ.get("XPRA_GSTREAMER_ENCODER_FORMATS", "h264,hevc,vp8,vp9,av1").split(",")

log(f"encoder: {get_type()} {get_version()}")

PACKED_RGB_FORMATS = ("RGBA", "BGRA", "ARGB", "ABGR", "RGB", "BGR", "BGRX", "XRGB", "XBGR")

assert get_type()  # all codecs must define this function
COLORSPACES: dict[str, dict[str, list[str]]] = {}


def get_encodings() -> Sequence[str]:
    return tuple(COLORSPACES.keys())


def ElementEncoderClass(element: str):
    class ElementEncoder(Encoder):
        pass

    ElementEncoder.encoder_element = element
    return ElementEncoder


def make_spec(element: str, encoding: str, cs_in: str, css_out: Sequence[str],
              cpu_cost: int = 50, gpu_cost: int = 50) -> VideoSpec:
    # use a metaclass so all encoders are gstreamer.encoder.Encoder subclasses,
    # each with different pipeline arguments based on the make_spec parameters:
    if cs_in in PACKED_RGB_FORMATS:
        width_mask = height_mask = 0xFFFF
    else:
        width_mask = height_mask = 0xFFFE
    spec = VideoSpec(
        encoding=encoding, input_colorspace=cs_in,
        output_colorspaces=css_out,
        has_lossless_mode=False,
        codec_class=ElementEncoderClass(element), codec_type=f"gstreamer-{element}",
        quality=40, speed=20,
        setup_cost=100, cpu_cost=cpu_cost, gpu_cost=gpu_cost,
        width_mask=width_mask, height_mask=height_mask,
        min_w=64, min_h=64,
        max_w=4096, max_h=4096)
    spec.gstreamer_element = element
    return spec


SPECS: dict[str, dict[str, list[VideoSpec]]] = {}


def get_specs() -> Sequence[VideoSpec]:
    # easy, just flatten the ones we found:
    specs: Sequence[VideoSpec] = []
    for cs_dicts in SPECS.values():
        for lspecs in cs_dicts.values():
            specs += lspecs
    return specs


def init_all_specs(*exclude) -> None:
    # by default, try to enable everything
    # the self-tests should disable what isn't available / doesn't work
    specs: dict[str, dict[str, list]] = {}
    colorspaces: dict[str, dict[str, list]] = {}
    missing: list[str] = []

    def add(element: str, encoding: str, cs_in: str, css_out, *args):
        if element in missing:
            return
        if encoding not in FORMATS:
            log(f"{encoding} not enabled - supported formats: {FORMATS}")
            return
        if element in exclude:
            return
        if element not in get_all_plugin_names():
            if element not in ("amfh264enc", "amfh265enc"):
                missing.append(element)
            return
        # add spec:
        css_out = css_out or (cs_in,)
        spec = make_spec(element, encoding, cs_in, css_out, *args)
        specs.setdefault(encoding, {}).setdefault(cs_in, []).append(spec)
        # update colorspaces map (add new output colorspaces - if any):
        cur = colorspaces.setdefault(encoding, {}).setdefault(cs_in, [])
        for v in css_out:
            if v not in cur:
                cur.append(v)

    vaapi = VAAPI
    if VAAPI and not NVIDIA_VAAPI:
        try:
            from xpra.codecs.nvidia.util import has_nvidia_hardware
            vaapi = not has_nvidia_hardware()
        except ImportError:
            pass
    log(f"init_all_specs try vaapi? {vaapi}")
    if vaapi:
        add("vah264lpenc", "h264", "NV12", ("YUV420P",), 20, 100)
        add("vah264enc", "h264", "NV12", ("YUV420P",), 20, 100)
        add("vaapih264enc", "h264", "NV12", ("YUV420P",), 20, 100)
        add("vaapih265enc", "hevc", "NV12", ("YUV420P",), 20, 100)
    if NVD3D11:
        add("nvd3d11h264enc", "h264", "YUV420P", ("YUV420P",), 20, 100)
        add("nvd3d11h265enc", "hevc", "YUV420P", ("YUV420P",), 20, 100)
    if NVENC:
        add("nvh264enc", "h264", "YUV420P", ("YUV420P",), 20, 100)
        add("nvh265enc", "hevc", "YUV420P", ("YUV420P",), 20, 100)
    if not (OSX or WIN32):
        add("amfh264enc", "h264", "NV12", ("YUV420P",), 20, 100)
        add("amfh265enc", "hevc", "NV12", ("YUV420P",), 20, 100)
    add("x264enc", "h264", "YUV420P", ("YUV420P",), 100, 0)
    add("x264enc", "h264", "YUV444P", ("YUV444P",), 100, 0)
    add("openh264enc", "h264", "YUV420P", ("YUV420P",), 100, 0)
    add("vp8enc", "vp8", "YUV420P", ("YUV420P",), 100, 0)
    add("vp9enc", "vp9", "YUV444P", ("YUV444P",), 100, 0)
    if not OSX:
        add("av1enc", "av1", "YUV420P", ("YUV420P",), 100, 0)
        add("av1enc", "av1", "YUV444P", ("YUV444P",), 100, 0)
    # svt encoders error out:
    # add("svtav1enc", "av1", "YUV420P", ("YUV420P", ), 100, 0)
    # add("svtvp9enc", "vp9", "YUV420P", ("YUV420P", ), 100, 0)
    # add: nvh264enc, nvh265enc ?
    global SPECS, COLORSPACES
    SPECS = specs
    COLORSPACES = colorspaces
    log("init_all_specs%s SPECS=%s", exclude, SPECS)
    log("init_all_specs%s COLORSPACES=%s", exclude, COLORSPACES)
    if missing and first_time("gstreamer-encoder-missing-elements"):
        log.info("some GStreamer elements are missing or unavailable on this system:")
        log.info(" " + csv(missing))


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

    def create_pipeline(self, options: typedict) -> None:
        if self.encoding not in get_encodings():
            raise ValueError(f"invalid encoding {self.encoding!r}")
        self.dst_formats = options.strtupleget("dst-formats")
        gst_rgb_format = get_gst_rgb_format(self.colorspace)
        if not gst_rgb_format:
            raise ValueError(f"unable to map {self.colorspace} to a gstreamer pixel format")
        vcaps: dict[str, Any] = {
            "width": self.width,
            "height": self.height,
            "format": gst_rgb_format,
            "framerate": (60, 1),
            "interlace": "progressive",
            "colorimetry": "bt709",
        }
        CAPS = get_caps_str("video/x-raw", vcaps)
        self.profile = self.get_profile(options)  # ie: "high"
        eopts = get_video_encoder_options(self.encoder_element, self.profile, options)
        vcaps = get_video_encoder_caps(self.encoder_element)
        self.extra_client_info = vcaps.copy()
        if self.profile:
            vcaps["profile"] = self.profile
            self.extra_client_info["profile"] = self.profile
        appsrc_opts = get_default_appsrc_attributes()
        appsrc_opts |= {
            "is-live": True,
            "do-timestamp": True,
            "format": BUFFER_FORMAT,
            "caps": CAPS,
            # "leaky-type"    : 0,        # default is 0 and this is not available before GStreamer 1.20
        }
        gst_encoding = get_gst_encoding(self.encoding)  # ie: "hevc" -> "video/x-h265"
        elements = [
            get_element_str("appsrc", appsrc_opts),
            get_element_str(self.encoder_element, eopts),
            get_caps_str(gst_encoding, vcaps),
            get_element_str("appsink", get_default_appsink_attributes())
        ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")

    def get_profile(self, options: typedict) -> str:
        default_profile: str = {
            # "x264enc"   : "constrained-baseline",
            # "vaapih264enc" : "constrained-baseline",
            # "nvh264enc" : "main",
            "vp8enc": "",  # 0-4
            "vp9enc": "",  # 0-4
        }.get(self.encoder_element, "")
        return get_profile(options, self.encoding, self.colorspace, default_profile)

    def get_src_format(self) -> str:
        return self.colorspace

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        if self.dst_formats:
            info["dst_formats"] = self.dst_formats
        return info

    def clean(self) -> None:
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
            if pts >= 0:
                client_info["timestamp"] = pts
            duration = normv(buf.duration)
            if duration >= 0:
                client_info["duration"] = duration
            qs = self.frame_queue.qsize()
            if qs > 0:
                client_info["delayed"] = qs
            self.frame_queue.put((data, client_info))
            log(f"added data to frame queue, client_info={client_info}")
        return GST_FLOW_OK

    def compress_image(self, image: ImageWrapper, options: typedict):
        if image.get_planes() == ImageWrapper.PACKED:
            data = image.get_pixels()[:]
            rowstride = image.get_rowstride()
            want_rowstride = roundup(self.width, 2) * len(self.colorspace)
            if rowstride != want_rowstride and not image.restride(want_rowstride):
                raise RuntimeError(f"failed to restride image from {rowstride}to {want_rowstride}")
        else:
            # merge all planes into a single buffer:
            data = b"".join(image.get_pixels())
        log(f"compress_image({image}, {options}) state={self.state} pixel buffer size={len(data)}")
        if self.state in ("stopped", "error"):
            log(f"pipeline is in {self.state} state, dropping buffer")
            return None
        return self.process_buffer(Gst.Buffer.new_wrapped(data), options)


GObject.type_register(Encoder)


def selftest(full=False):
    log("gstreamer encoder selftest: %s", get_info())
    from xpra.codecs.checks import test_encoder_spec, DEFAULT_TEST_SIZE
    W, H = DEFAULT_TEST_SIZE
    # test individual specs
    skip = []
    log(f"will self test: {SPECS}")
    for encoding, cs_map in SPECS.items():
        for cs_in, specs in cs_map.items():
            for spec in specs:
                try:
                    for cs_out in spec.output_colorspaces:
                        test_encoder_spec(spec.codec_class, encoding, cs_in, cs_out, W, H, full, typedict())
                        log(f"{spec.gstreamer_element} {encoding} {cs_in} -> {spec.output_colorspaces} passed")
                except Exception as e:
                    log("test_encoder_spec", exc_info=True)
                    log.warn(f"Warning: gstreamer {spec.gstreamer_element!r} encoder failed")
                    log.warn(f" {e}")
                    skip.append(spec.gstreamer_element)
    init_all_specs(*skip)


init_all_specs()
