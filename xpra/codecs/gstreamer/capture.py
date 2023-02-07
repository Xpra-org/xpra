# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import Queue, Empty, Full
from gi.repository import GObject  # @UnresolvedImport

from xpra.gst_common import  import_gst
from xpra.gtk_common.gobject_util import one_arg_signal
from xpra.gst_pipeline import Pipeline, GST_FLOW_OK
from xpra.codecs.gstreamer.codec_common import (
    get_version, get_type, get_info,
    init_module, cleanup_module,
    )
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.log import Logger

Gst = import_gst()
log = Logger("encoder", "gstreamer")


assert get_version and get_type and init_module and cleanup_module


class Capture(Pipeline):
    """
    Uses a GStreamer pipeline to capture the screen
    """
    __gsignals__ = Pipeline.__generic_signals__.copy()
    __gsignals__["new-image"] = one_arg_signal

    def __init__(self, element : str="ximagesrc", pixel_format : str="BGRX",
                 width : int=0, height : int=0):
        super().__init__()
        self.pixel_format : str = pixel_format
        self.width : int = width
        self.height : int = height
        self.frames : int = 0
        self.framerate : int  = 10
        self.image = Queue(maxsize=1)
        self.create_pipeline(element)
        assert width>0 and height>0

    def create_pipeline(self, capture_element:str="ximagesrc"):
        #CAPS = f"video/x-raw,width={self.width},height={self.height},format=(string){self.pixel_format},framerate={self.framerate}/1,interlace=progressive"
        elements = [
            capture_element,   #ie: ximagesrc
            #f"video/x-raw,framerate={self.framerate}/1",
            "videoconvert",
            #"videorate",
            #"videoscale ! video/x-raw,width=800,height=600 ! autovideosink
            "appsink name=sink emit-signals=true max-buffers=10 drop=true sync=false async=false qos=false",
            ]
        if not self.setup_pipeline_and_bus(elements):
            raise RuntimeError("failed to setup gstreamer pipeline")
        self.sink   = self.pipeline.get_by_name("sink")
        self.sink.connect("new-sample", self.on_new_sample)
        self.sink.connect("new-preroll", self.on_new_preroll)

    def on_new_sample(self, _bus):
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
                self.emit("new-image", self.frames)
        return GST_FLOW_OK

    def on_new_preroll(self, _appsink):
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

    def refresh(self):
        return not self.image.empty()

    def clean(self):
        self.stop()


GObject.type_register(Capture)


def selftest(full=False):
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
