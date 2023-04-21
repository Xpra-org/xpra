# This file is part of Xpra.
# Copyright (C) 2014-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import Queue, Empty

from xpra.util import typedict, envint
from xpra.gst_common import import_gst, GST_FLOW_OK
from xpra.gst_pipeline import Pipeline
from xpra.log import Logger

Gst = import_gst()
log = Logger("encoder", "gstreamer")

FRAME_QUEUE_TIMEOUT = envint("XPRA_GSTREAMER_FRAME_QUEUE_TIMEOUT", 1)
FRAME_QUEUE_INITIAL_TIMEOUT = envint("XPRA_GSTREAMER_FRAME_QUEUE_INITIAL_TIMEOUT", 3)


def get_version():
    return (5, 0)

def get_type():
    return "gstreamer"

def get_info():
    return {"version"   : get_version()}

def init_module():
    log("gstreamer.init_module()")

def cleanup_module():
    log("gstreamer.cleanup_module()")


class VideoPipeline(Pipeline):
    __generic_signals__ : dict = Pipeline.__generic_signals__.copy()
    """
    Dispatch video encoding or decoding to a gstreamer pipeline
    """
    def init_context(self, encoding, width, height, colorspace, options=None):
        options = typedict(options or {})
        self.encoding = encoding
        self.width = width
        self.height = height
        self.colorspace = colorspace
        self.frames = 0
        self.frame_queue = Queue()
        self.pipeline_str = ""
        self.create_pipeline(options)
        self.src    = self.pipeline.get_by_name("src")
        self.src.set_property("format", Gst.Format.TIME)
        #self.src.set_caps(Gst.Caps.from_string(CAPS))
        self.sink   = self.pipeline.get_by_name("sink")
        def sh(sig, handler):
            self.element_connect(self.sink, sig, handler)
        sh("new-sample", self.on_new_sample)
        sh("new-preroll", self.on_new_preroll)
        self.start()

    def create_pipeline(self, options):
        raise NotImplementedError()

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.NEED_CONTEXT and self.pipeline_str.find("vaapi")>=0:
            log("vaapi is requesting a context")
            return GST_FLOW_OK
        return super().on_message(bus, message)

    def on_new_preroll(self, _appsink):
        log("new-preroll")
        return GST_FLOW_OK

    def process_buffer(self, buf):
        r = self.src.emit("push-buffer", buf)
        if r!=GST_FLOW_OK:
            log.error("Error: unable to push image buffer")
            return None
        timeout = FRAME_QUEUE_INITIAL_TIMEOUT if self.frames==0 else FRAME_QUEUE_TIMEOUT
        try:
            return self.frame_queue.get(timeout=timeout)
        except Empty:
            log.error(f"Error: frame queue timeout after {timeout}s")
            try:
                log.error(f" on %r of size %s", type(buf).__qualname__, buf.get_size())
            except AttributeError:
                pass
            for k,v in self.get_info().items():
                log.error(f" {k:<16}: {v}")
            return None


    def get_info(self) -> dict:
        info = get_info()
        if self.colorspace is None:
            return info
        info.update({
            "frames"    : self.frames,
            "width"     : self.width,
            "height"    : self.height,
            "encoding"  : self.encoding,
            "colorspace": self.colorspace,
            "version"   : get_version(),
            })
        return info

    def __repr__(self):
        if self.colorspace is None:
            return "gstreamer(uninitialized)"
        return f"gstreamer({self.colorspace} - {self.width}x{self.height})"

    def is_ready(self) -> bool:
        return self.colorspace is not None

    def is_closed(self) -> bool:
        return self.colorspace is None


    def get_encoding(self) -> str:
        return self.encoding

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "gstreamer"

    def clean(self):
        super().cleanup()
        self.width = 0
        self.height = 0
        self.colorspace = None
        self.encoding = ""
        self.dst_formats = []
        self.frames = 0


    def do_emit_info(self):
        self.emit_info_timer = 0
