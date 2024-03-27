# This file is part of Xpra.
# Copyright (C) 2023-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import Queue, Empty, Full
from collections.abc import Iterable
from typing import Any

from xpra.os_util import gi_import
from xpra.util.env import envbool
from xpra.util.str_fn import csv
from xpra.util.objects import typedict, AtomicInteger
from xpra.gstreamer.common import (
    import_gst, GST_FLOW_OK, get_element_str,
    get_default_appsink_attributes, get_all_plugin_names,
    get_caps_str,
)
from xpra.gtk.gobject import n_arg_signal
from xpra.gstreamer.pipeline import Pipeline
from xpra.codecs.constants import get_profile, CSC_ALIAS
from xpra.codecs.gstreamer.common import (
    get_version, get_type, get_info,
    init_module, cleanup_module,
    get_video_encoder_caps, get_video_encoder_options,
    get_gst_encoding, get_encoder_info, get_gst_rgb_format,
)
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger

Gst = import_gst()
log = Logger("encoder", "gstreamer")

GObject = gi_import("GObject")

log(f"capture: {get_type()} {get_version()}, {init_module}, {cleanup_module}")

SAVE_TO_FILE = envbool("XPRA_SAVE_TO_FILE")

generation = AtomicInteger()


class Capture(Pipeline):
    """
    Uses a GStreamer pipeline to capture the screen
    """
    __gsignals__ = Pipeline.__generic_signals__.copy()
    __gsignals__["new-image"] = n_arg_signal(3)

    def __init__(self, element: str = "ximagesrc", pixel_format: str = "BGRX",
                 width: int = 0, height: int = 0):
        super().__init__()
        self.capture_element = element.split(" ")[0]
        self.pixel_format: str = pixel_format
        self.width: int = width
        self.height: int = height
        self.frames: int = 0
        self.framerate: int = 10
        self.image: Queue[ImageWrapper] = Queue(maxsize=1)
        self.sink = None
        self.capture = None
        self.extra_client_info = {}
        self.create_pipeline(element)
        assert width > 0 and height > 0

    def create_pipeline(self, capture_element: str = "ximagesrc") -> None:
        elements = [
            f"{capture_element} name=capture",  # ie: ximagesrc or pipewiresrc
            # f"video/x-raw,framerate={self.framerate}/1",
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

    def get_image(self, x: int = 0, y: int = 0, width: int = 0, height: int = 0):
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


ENCODER_ELEMENTS: dict[str, str] = {
    "jpeg": ("jpegenc", ),
    "h264": ("openh264enc", "x264enc"),
    "vp8": ("vp8enc", ),
    "vp9": ("vp9enc", ),
    "av1": ("av1enc", ),
}


def choose_encoder(plugins: Iterable[str]) -> str:
    # for now, just use the first one available:
    for plugin in plugins:
        if plugin in get_all_plugin_names():
            return plugin
    return ""


def choose_video_encoder(encodings: Iterable[str]) -> str:
    log(f"choose_video_encoder({encodings})")
    for encoding in encodings:
        plugins = ENCODER_ELEMENTS.get(encoding, ())
        element = choose_encoder(plugins)
        if not element:
            log(f"skipped {encoding!r} due to missing: {csv(plugins)}")
            continue
        log(f"selected {encoding!r}")
        return encoding
    return ""


def choose_csc(modes: Iterable[str], quality=100) -> str:
    prefer = "YUV420P" if quality < 80 else "YUV444P"
    if not modes or prefer in modes:
        return prefer
    return modes[0]


class CaptureAndEncode(Capture):
    """
    Uses a GStreamer pipeline to capture the screen
    and encode it to a video stream
    """

    def create_pipeline(self, capture_element: str = "ximagesrc") -> None:
        # we are overloading "pixel_format" as "encoding":
        encoding = self.pixel_format
        elements = ENCODER_ELEMENTS.get(encoding)
        if not elements:
            raise ValueError(f"no encoders defined for {encoding!r}")
        encoder = choose_encoder(elements)
        if not encoder:
            raise RuntimeError(f"no encoders found for {encoding!r}")
        options = typedict({
            "speed": 100,
            "quality": 100,
        })
        einfo = get_encoder_info(encoder)
        log(f"{encoder}: {einfo=}")
        self.csc_mode = choose_csc(einfo.get("format", ()), options.intget("quality", 100))
        self.profile = get_profile(options, encoding, csc_mode=self.csc_mode,
                                   default_profile="high" if encoder == "x264enc" else "")
        eopts = get_video_encoder_options(encoder, self.profile, options)
        vcaps = get_video_encoder_caps(encoder)
        self.extra_client_info: dict[str, Any] = vcaps.copy()
        if self.profile:
            vcaps["profile"] = self.profile
            self.extra_client_info["profile"] = self.profile
        gst_encoding = get_gst_encoding(encoding)  # ie: "hevc" -> "video/x-h265"
        elements = [
            f"{capture_element} name=capture",  # ie: ximagesrc or pipewiresrc
            "queue leaky=2 max-size-buffers=1",
            "videoconvert",
            "video/x-raw,format=%s" % get_gst_rgb_format(self.csc_mode),
            get_element_str(encoder, eopts),
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
            client_info["csc"] = CSC_ALIAS.get(self.csc_mode, self.csc_mode)
            self.extra_client_info = {}
            self.emit("new-image", self.pixel_format, data, client_info)
        if SAVE_TO_FILE:
            if not self.file:
                encoding = self.pixel_format
                gen = generation.increase()
                filename = "gstreamer-" + str(gen) + f".{encoding}"
                self.file = open(filename, "wb")
                log.info(f"saving gstreamer {encoding} stream to {filename!r}")
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


def selftest(_full=False) -> None:
    log("gstreamer encoder selftest: %s", get_info())
    glib = gi_import("GLib")
    from xpra.gtk.util import get_root_size
    w, h = get_root_size()
    c = Capture(width=w, height=h)
    loop = glib.MainLoop()

    def check():
        i = c.get_image()
        if i:
            c.stop()
            return False
        return True

    glib.timeout_add(500, check)
    glib.timeout_add(2000, c.stop)
    glib.timeout_add(2500, loop.quit)
    c.start()
    loop.run()


if __name__ == "__main__":
    selftest()
