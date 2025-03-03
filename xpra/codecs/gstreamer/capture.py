# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from queue import Queue, Empty, Full
from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.util.objects import typedict, AtomicInteger
from xpra.gstreamer.common import (
    import_gst, GST_FLOW_OK, get_element_str,
    get_default_appsink_attributes,
    get_caps_str,
)
from xpra.gtk.gobject import n_arg_signal
from xpra.gstreamer.pipeline import Pipeline
from xpra.codecs.constants import get_profile, CSC_ALIAS, VideoSpec
from xpra.codecs.gstreamer.common import (
    get_version, get_type, get_info,
    get_video_encoder_caps, get_video_encoder_options,
    get_gst_encoding, get_encoder_info, get_gst_rgb_format,
)
from xpra.codecs.video import getVideoHelper
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger

Gst = import_gst()
log = Logger("encoder", "gstreamer")

GObject = gi_import("GObject")

log(f"capture: {get_type()} {get_version()}")

SAVE_TO_FILE = envbool("XPRA_SAVE_TO_FILE")

generation = AtomicInteger()


class Capture(Pipeline):
    """
    Uses a GStreamer pipeline to capture the screen
    """
    __gsignals__ = Pipeline.__generic_signals__.copy()
    __gsignals__["new-image"] = n_arg_signal(3)

    def __init__(self, element: str = "ximagesrc", pixel_format: str = "BGRX",
                 width: int = 0, height: int = 0, framerate: int = 0):
        super().__init__()
        self.capture_element = element.split(" ")[0]
        self.pixel_format: str = pixel_format
        self.width: int = width
        self.height: int = height
        self.frames: int = 0
        self.framerate: int = framerate
        self.image: Queue[ImageWrapper] = Queue(maxsize=1)
        self.sink = None
        self.capture = None
        self.extra_client_info = {}
        self.create_pipeline(element)
        assert width > 0 and height > 0

    def create_pipeline(self, capture_element: str = "ximagesrc") -> None:
        elements = [
            f"{capture_element} name=capture",  # ie: ximagesrc or pipewiresrc
        ]
        if self.framerate > 0:
            elements.append(f"video/x-raw,framerate={self.framerate}/1")
        elements += [
            "videoconvert",
            "appsink name=sink emit-signals=true max-buffers=10 drop=true sync=false async=false qos=false",
        ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")
        self.sink = self.pipeline.get_by_name("sink")
        self.capture = self.pipeline.get_by_name("capture")

        def sh(sig, handler):
            self.element_connect(self.sink, sig, handler)

        sh("new-sample", self.on_new_sample)
        sh("new-preroll", self.on_new_preroll)

    def on_new_sample(self, _bus) -> int:
        sample = self.sink.emit("pull-sample")
        buf = sample.get_buffer()
        size = buf.get_size()
        log("on_new_sample size=%s", size)
        if size:
            data = buf.extract_dup(0, size)
            self.frames += 1
            bytesperpixel = len(self.pixel_format)
            rowstride = self.width * bytesperpixel
            image = ImageWrapper(x=0, y=0, width=self.width, height=self.height, pixels=data,
                                 pixel_format=self.pixel_format, depth=24,
                                 rowstride=rowstride, bytesperpixel=bytesperpixel, planes=ImageWrapper.PACKED)
            log(f"image={image}")
            while True:
                try:
                    self.image.get(block=False)
                except Empty:
                    break
            try:
                self.image.put_nowait(image)
            except Full:
                log("image queue is already full")
            else:
                client_info = {"frame": self.frames}
                self.emit("new-image", self.pixel_format, image, client_info)
        return GST_FLOW_OK

    def on_new_preroll(self, _appsink) -> int:
        log("new-preroll")
        return GST_FLOW_OK

    def get_image(self, x: int = 0, y: int = 0, width: int = 0, height: int = 0) -> ImageWrapper | None:
        log("get_image%s", (x, y, width, height))
        if self.state == "stopped":
            return None
        try:
            return self.image.get(timeout=5)
        except Empty:
            return None

    def refresh(self) -> bool:
        return not self.image.empty()

    def clean(self) -> None:
        self.stop()
        f = self.file
        if f:
            self.file = None
            f.close()

    def get_type(self) -> str:
        return self.capture_element


GObject.type_register(Capture)


def choose_video_encoder(preferred_encoding: str, full_csc_modes: typedict) -> VideoSpec | None:
    log(f"choose_video_encoder({preferred_encoding}, {full_csc_modes})")
    vh = getVideoHelper()
    scores: dict[int, list[VideoSpec]] = {}
    for encoding in full_csc_modes.keys():
        csc_modes = full_csc_modes.strtupleget(encoding)
        encoder_specs = vh.get_encoder_specs(encoding)
        # ignore the input colorspace for now,
        # and assume we can `videoconvert` to this format
        # TODO: take csc into account for scoring
        for codec_list in encoder_specs.values():
            for codec in codec_list:
                if not codec.codec_type.startswith("gstreamer"):
                    continue
                if "*" not in csc_modes:
                    # verify that the client can decode this csc mode:
                    matches = tuple(x for x in codec.output_colorspaces if x in csc_modes)
                    if not matches:
                        log(f"skipped {codec}: {codec.output_colorspaces} not in {csc_modes}")
                        continue
                # prefer encoding matching what the user requested and GPU accelerated:
                gpu = bool(codec.gpu_cost > codec.cpu_cost)
                score = int(codec.encoding == preferred_encoding or gpu) * 100 + codec.quality + codec.score_boost
                log(f"score({codec.codec_type})={score} ({gpu=}, quality={codec.quality}, boost={codec.score_boost})")
                # (lowest score wins)
                scores.setdefault(-score, []).append(codec)
    log(f"choose_video_encoder: scores={scores}")
    if not scores:
        return None
    best_score = sorted(scores)[0]
    best = scores[best_score][0]
    log(f"choose_video_encoder({preferred_encoding}, {full_csc_modes})={best}")
    return best


def choose_csc(modes: Sequence[str], quality=100) -> str:
    prefer = "YUV420P" if quality < 80 else "YUV444P"
    if not modes or prefer in modes:
        return prefer
    return modes[0]


class CaptureAndEncode(Capture):
    """
    Uses a GStreamer pipeline to capture the screen
    and encode it to a video stream
    """

    def __init__(self, element: str = "ximagesrc", encoding="vp8", encoder="vp8enc",
                 pixel_format: str = "YUV420P", width: int = 0, height: int = 0, framerate: int = 0):
        self.encoding = encoding
        self.encoder = encoder
        super().__init__(element, pixel_format, width, height, framerate)

    def create_pipeline(self, capture_element: str = "ximagesrc") -> None:
        options = typedict({
            "speed": 100,
            "quality": 100,
        })
        einfo = get_encoder_info(self.encoder)
        log(f"{self.encoder}: {einfo=}")
        self.profile = get_profile(options, self.encoding, csc_mode=self.pixel_format,
                                   default_profile="high" if self.encoder == "x264enc" else "")
        eopts = get_video_encoder_options(self.encoder, self.profile, options)
        vcaps = get_video_encoder_caps(self.encoder)
        self.extra_client_info: dict[str, Any] = vcaps.copy()
        if self.profile:
            vcaps["profile"] = self.profile
            self.extra_client_info["profile"] = self.profile
        gst_encoding = get_gst_encoding(self.encoding)  # ie: "hevc" -> "video/x-h265"
        elements = [
            f"{capture_element} name=capture",  # ie: ximagesrc or pipewiresrc
        ]
        if self.framerate > 0:
            elements.append(f"video/x-raw,framerate={self.framerate}/1")
        elements += [
            "queue leaky=2 max-size-buffers=1",
            "videoconvert",
            "video/x-raw,format=%s" % get_gst_rgb_format(self.pixel_format),
            get_element_str(self.encoder, eopts),
            get_caps_str(gst_encoding, vcaps),
            get_element_str("appsink", get_default_appsink_attributes()),
        ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")
        self.sink: Gst.Element = self.pipeline.get_by_name("sink")
        self.capture = self.pipeline.get_by_name("capture")
        self.file = None

        def sh(sig, handler):
            self.element_connect(self.sink, sig, handler)

        sh("new-sample", self.on_new_sample)
        sh("new-preroll", self.on_new_preroll)

    def on_new_sample(self, _bus) -> int:
        sample = self.sink.emit("pull-sample")
        buf = sample.get_buffer()
        size = buf.get_size()
        log("on_new_sample size=%s", size)
        if size:
            data = buf.extract_dup(0, size)
            self.frames += 1
            client_info = self.extra_client_info
            client_info["frame"] = self.frames
            client_info["csc"] = CSC_ALIAS.get(self.pixel_format, self.pixel_format)
            self.extra_client_info = {}
            self.emit("new-image", self.encoding, data, client_info)
            if SAVE_TO_FILE:
                if not self.file:
                    gen = generation.increase()
                    filename = "gstreamer-" + str(gen) + f".{self.encoding}"
                    self.file = open(filename, "wb")
                    log.info(f"saving gstreamer {self.encoding} stream to {filename!r}")
                self.file.write(data)
        return GST_FLOW_OK

    def on_new_preroll(self, _appsink) -> int:
        log("new-preroll")
        return GST_FLOW_OK

    def refresh(self) -> bool:
        return True

    def clean(self) -> None:
        self.stop()

    def get_type(self) -> str:
        return f"{self.capture_element}-{self.pixel_format}"


GObject.type_register(CaptureAndEncode)


def capture_and_encode(capture_element: str, encoding: str,
                       full_csc_modes: typedict, w: int, h: int, framerate=0) -> CaptureAndEncode | None:
    encoder_spec = choose_video_encoder(encoding, full_csc_modes)
    if not encoder_spec:
        log(f"unable to find a GStreamer video encoder with csc modes={full_csc_modes}")
        return None
    assert encoder_spec.codec_type.startswith("gstreamer-")
    encoder = encoder_spec.codec_type[len("gstreamer-"):]
    encoding = encoder_spec.encoding
    csc_mode = encoder_spec.input_colorspace
    return CaptureAndEncode(capture_element, encoding, encoder, csc_mode, w, h, framerate)


def selftest(_full=False) -> None:
    log("gstreamer encoder selftest: %s", get_info())
    GLib = gi_import("GLib")
    from xpra.gtk.util import get_root_size
    w, h = get_root_size()
    c = Capture(width=w, height=h)
    loop = GLib.MainLoop()

    def check() -> bool:
        i = c.get_image()
        if i:
            c.stop()
            return False
        return True

    GLib.timeout_add(500, check)
    GLib.timeout_add(2000, c.stop)
    GLib.timeout_add(2500, loop.quit)
    c.start()
    loop.run()


if __name__ == "__main__":
    selftest()
