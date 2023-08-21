# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import Queue, Empty, Full
from typing import Dict, Any
from gi.repository import GObject  # @UnresolvedImport

from xpra.util import typedict
from xpra.gst_common import (
    import_gst, GST_FLOW_OK, get_element_str,\
    get_default_appsink_attributes, get_all_plugin_names,
    get_caps_str,
    )
from xpra.gtk_common.gobject_util import n_arg_signal
from xpra.gst_pipeline import Pipeline
from xpra.codecs.codec_constants import get_profile
from xpra.codecs.gstreamer.codec_common import (
    get_version, get_type, get_info,
    init_module, cleanup_module,
    get_video_encoder_caps, get_video_encoder_options,
    get_gst_encoding,
    )
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger

Gst = import_gst()
log = Logger("encoder", "gstreamer")


log(f"capture: {get_type()} {get_version()}, {init_module}, {cleanup_module}")


class Capture(Pipeline):
    """
    Uses a GStreamer pipeline to capture the screen
    """
    __gsignals__ = Pipeline.__generic_signals__.copy()
    __gsignals__["new-image"] = n_arg_signal(3)

    def __init__(self, element : str="ximagesrc", pixel_format : str="BGRX",
                 width : int=0, height : int=0):
        super().__init__()
        self.capture_element = element.split(" ")[0]
        self.pixel_format : str = pixel_format
        self.width : int = width
        self.height : int = height
        self.frames : int = 0
        self.framerate : int  = 10
        self.image : Queue[ImageWrapper] = Queue(maxsize=1)
        self.sink = None
        self.extra_client_info = {}
        self.create_pipeline(element)
        assert width>0 and height>0

    def create_pipeline(self, capture_element:str="ximagesrc") -> None:
        #CAPS = f"video/x-raw,width={self.width},height={self.height},format=(string){self.pixel_format},framerate={self.framerate}/1,interlace=progressive"
        elements = [
            capture_element,
            #f"video/x-raw,framerate={self.framerate}/1",
            "videoconvert",
            #"videorate",
            #"videoscale ! video/x-raw,width=800,height=600 ! autovideosink
            "appsink name=sink emit-signals=true max-buffers=10 drop=true sync=false async=false qos=false",
            ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")
        self.sink   = self.pipeline.get_by_name("sink")
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
            rowstride = self.width*bytesperpixel
            image = ImageWrapper(x=0, y=0, width=self.width, height=self.height, pixels=data, pixel_format=self.pixel_format,
                                 depth=24, rowstride=rowstride, bytesperpixel=bytesperpixel, planes=ImageWrapper.PACKED)
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
                client_info = {"frame" : self.frames}
                self.emit("new-image", self.pixel_format, image, client_info)
        return GST_FLOW_OK

    def on_new_preroll(self, _appsink) -> int:
        log("new-preroll")
        return GST_FLOW_OK

    def get_image(self, x:int=0, y:int=0, width:int=0, height:int=0):
        log("get_image%s", (x, y, width, height))
        if self.state=="stopped":
            return None
        try:
            return self.image.get(timeout=5)
        except Empty:
            return None

    def refresh(self) -> bool:
        return not self.image.empty()

    def clean(self) -> None:
        self.stop()

    def get_type(self) -> str:
        return self.capture_element

GObject.type_register(Capture)


class CaptureAndEncode(Capture):
    """
    Uses a GStreamer pipeline to capture the screen
    and encode it to a video stream
    """

    def create_pipeline(self, capture_element:str="ximagesrc") -> None:
        #encode_element:str="x264enc pass=4 speed-preset=1 tune=4 byte-stream=true quantizer=51 qp-max=51 qp-min=50"):
        #encode_element="x264enc threads=8 pass=4 speed-preset=1 tune=zerolatency byte-stream=true quantizer=51 qp-max=51 qp-min=50"):
        #encode_element="vp8enc deadline=1 min-quantizer=60 max-quantizer=63 cq-level=61"):
        #encode_element="vp9enc deadline=1 error-resilient=1 min-quantizer=60 end-usage=2"):
        #desktopcast does this:
        #https://github.com/seijikun/desktopcast/blob/9ae61739cedce078d197011f770f8e94d9a9a8b2/src/stream_server.rs#LL162C18-L162C18
        #" ! videoconvert ! queue leaky=2 ! x264enc threads={} tune=zerolatency speed-preset=2 bframes=0 ! video/x-h264,profile=high ! queue ! rtph264pay name=pay0 pt=96",

        #we are overloading "pixel_format" as "encoding":
        encoding = self.pixel_format
        encoder = {
            "jpeg"  : "jpegenc",
            "h264"  : "x264enc",
            "vp8"   : "vp8enc",
            "vp9"   : "vp9enc",
            "av1"   : "av1enc",
            }.get(encoding)
        if not encoder:
            raise ValueError(f"no encoder defined for {encoding}")
        if encoder not in get_all_plugin_names():
            raise RuntimeError(f"encoder {encoder} is not available")
        options = typedict({
            "speed" : 100,
            "quality" : 100,
            })
        self.profile = get_profile(options, encoding, csc_mode="YUV444P", default_profile="high" if encoder=="x264enc" else "")
        eopts = get_video_encoder_options(encoder, self.profile, options)
        vcaps = get_video_encoder_caps(encoder)
        self.extra_client_info : Dict[str,Any] = vcaps.copy()
        if self.profile:
            vcaps["profile"] = self.profile
            self.extra_client_info["profile"] = self.profile
        gst_encoding = get_gst_encoding(encoding)  #ie: "hevc" -> "video/x-h265"
        elements = [
            capture_element,   #ie: ximagesrc or pipewiresrc
            #"videorate",
            #"video/x-raw,framerate=20/1",
            #"queue leaky=2 max-size-buffers=1",
            "videoconvert",
            "queue leaky=2",
            get_element_str(encoder, eopts),
            get_caps_str(gst_encoding, vcaps),
            #"appsink name=sink emit-signals=true max-buffers=1 drop=false sync=false async=true qos=true",
            get_element_str("appsink", get_default_appsink_attributes()),
            ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")
        self.sink : Gst.Element = self.pipeline.get_by_name("sink")
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
            self.extra_client_info = {}
            self.emit("new-image", self.pixel_format, data, client_info)
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
    from gi.repository import GLib  # @UnresolvedImport
    from xpra.gtk_common.gtk_util import get_root_size
    w, h = get_root_size()
    c = Capture(width=w, height=h)
    loop = GLib.MainLoop()
    def check():
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
