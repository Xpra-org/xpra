# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# must be done before importing gobject!
# pylint: disable=wrong-import-position

from time import monotonic
from types import ModuleType
from typing import Any
from collections.abc import Callable

from xpra.gstreamer.common import GST_FLOW_OK, import_gst

from xpra.os_util import gi_import
from xpra.util.env import first_time
from xpra.common import noerr
from xpra.util.objects import AtomicInteger
from xpra.gtk.gobject import one_arg_signal
from xpra.log import Logger

log = Logger("gstreamer")

Gst: ModuleType = import_gst()
if not Gst:
    raise ImportError("GStreamer bindings not found")
GLib = gi_import("GLib")
GObject = gi_import("GObject")


class Pipeline(GObject.GObject):

    generation = AtomicInteger()

    __generic_signals__: dict[str, tuple] = {
        "state-changed": one_arg_signal,
        "error": one_arg_signal,
        "new-stream": one_arg_signal,
        "info": one_arg_signal,
    }

    def __init__(self):
        super().__init__()
        self.bus = None
        self.bitrate: int = -1
        self.pipeline: Gst.Pipeline | None = None
        self.pipeline_str = ""
        self.element_handlers: dict[Any, list[int]] = {}
        self.start_time: float = 0
        self.state: str = "stopped"
        self.info: dict[str, Any] = {}
        self.emit_info_timer: int = 0
        self.file = None

    def element_connect(self, element, sig: str, handler: Callable) -> None:
        """ keeps track of signal ids so we can cleanup later """
        sid = element.connect(sig, handler)
        self.element_handlers.setdefault(element, []).append(sid)

    def elements_disconnect(self) -> None:
        handlers = self.element_handlers
        if not handlers:
            return
        self.element_handlers = {}
        for element, sids in handlers.items():
            for sid in sids:
                element.disconnect(sid)

    def update_state(self, state: str) -> None:
        log("update_state(%s)", state)
        self.state = state
        self.info["state"] = state

    def save_to_file(self, *buffers) -> None:
        f = self.file
        if f and buffers:
            for x in buffers:
                f.write(x)
            f.flush()

    def idle_emit(self, sig, *args) -> None:
        GLib.idle_add(self.emit, sig, *args)

    def emit_info(self) -> None:
        if self.emit_info_timer:
            return
        self.emit_info_timer = GLib.timeout_add(200, self.do_emit_info)

    def do_emit_info(self) -> None:
        self.emit_info_timer = 0
        if self.pipeline:
            info = self.get_info()
            # reset info:
            self.info = {}
            self.emit("info", info)

    def cancel_emit_info_timer(self) -> None:
        eit = self.emit_info_timer
        if eit:
            self.emit_info_timer = 0
            GLib.source_remove(eit)

    def get_info(self) -> dict[str, Any]:
        return self.info.copy()

    def setup_pipeline_and_bus(self, elements) -> bool:
        log("pipeline elements=%s", elements)
        self.pipeline_str = " ! ".join([x for x in elements if x is not None])
        log("pipeline=%s", self.pipeline_str)
        self.start_time = monotonic()
        try:
            self.pipeline = Gst.parse_launch(self.pipeline_str)
        except Exception as e:
            self.pipeline = None
            log.error("Error setting up the pipeline:")
            log.estr(e)
            log.error(" GStreamer pipeline for:")
            for i, x in enumerate(elements):
                sep = " ! \\" if i < (len(elements)-1) else ""
                log.error(f"  {x}{sep}")
            self.cleanup()
            return False
        self.bus = self.pipeline.get_bus()
        self.element_connect(self.bus, "message", self.on_message)
        self.bus.add_signal_watch()
        self.info["pipeline"] = self.pipeline_str
        return True

    def do_get_state(self, state) -> str:
        if not self.pipeline:
            return "stopped"
        return {
            Gst.State.PLAYING: "active",
            Gst.State.PAUSED: "paused",
            Gst.State.NULL: "stopped",
            Gst.State.READY: "ready",
        }.get(state, "unknown")

    def get_state(self) -> str:
        return self.state

    def start(self) -> bool:
        if not self.pipeline:
            log.error("Error: cannot start without a pipeline")
            return False
        self.update_state("active")
        self.pipeline.set_state(Gst.State.PLAYING)
        self.emit_info()
        return True

    def stop(self) -> None:
        p = self.pipeline
        self.pipeline = None
        if not p:
            return
        log("Pipeline.stop() state=%s", self.state)
        # uncomment this to see why we end up calling stop()
        # import traceback
        # for x in traceback.format_stack():
        #    for s in x.split("\n"):
        #        v = s.replace("\r", "").replace("\n", "")
        #        if v:
        #            log(v)
        self.update_state("stopped")
        p.set_state(Gst.State.NULL)
        log("Pipeline.stop() done")

    def cleanup(self) -> None:
        log("Pipeline.cleanup()")
        self.cancel_emit_info_timer()
        self.elements_disconnect()
        self.stop()
        b = self.bus
        self.bus = None
        log("Pipeline.cleanup() bus=%s", b)
        if not b:
            return
        b.remove_signal_watch()
        self.pipeline = None
        self.state = "destroyed"
        self.info = {}
        f = self.file
        if f:
            self.file = None
            noerr(f.close)
        log("Pipeline.cleanup() done")

    def gstloginfo(self, msg, *args) -> None:
        if self.state != "stopped":
            log.info(msg, *args)
        else:
            log(msg, *args)

    def gstlogwarn(self, msg, *args) -> None:
        if self.state != "stopped":
            log.warn(msg, *args)
        else:
            log(msg, *args)

    def onstart(self) -> None:
        """ this is overriden in some subclasses """

    def parse_tag_message(self, message) -> None:
        """ this is overriden in some subclasses """

    def on_message(self, _bus, message) -> int:
        log("on_message: %s", message)
        p = self.pipeline
        if not p:
            return GST_FLOW_OK
        t = message.type
        if t == Gst.MessageType.EOS:
            p.set_state(Gst.State.NULL)
            self.gstloginfo("EOS")
            self.update_state("stopped")
            self.idle_emit("state-changed", self.state)
        elif t == Gst.MessageType.ERROR:
            p.set_state(Gst.State.NULL)
            err, details = message.parse_error()
            log.error("Gstreamer pipeline error: %s", err.message)
            for earg in err.args:
                if earg != err.message:
                    log(" %s", earg)
            try:
                # prettify (especially on win32):
                p = details.find("\\Source\\")
                if p > 0:
                    details = details[p+len("\\Source\\"):]
                for d in details.split(": "):
                    for dl in d.splitlines():
                        if dl.strip():
                            log.error(" %s", dl.strip())
            except Exception:
                log.estr(details)
            self.update_state("error")
            self.idle_emit("error", str(err))
            # exit
            self.cleanup()
        elif t == Gst.MessageType.TAG:
            try:
                self.parse_tag_message(message)
            except Exception as e:
                self.gstlogwarn("Warning: failed to parse gstreamer message:")
                self.gstlogwarn(" %s: %s", type(e), e)
        elif t == Gst.MessageType.ELEMENT:
            try:
                self.parse_element_message(message)
            except Exception as e:
                self.gstlogwarn("Warning: failed to parse gstreamer element message:")
                self.gstlogwarn(" %s: %s", type(e), e)
        elif t == Gst.MessageType.STREAM_STATUS:
            log("stream status: %s", message)
        elif t == Gst.MessageType.STREAM_START:
            log("stream start: %s", message)
            self.onstart()
        elif t in (Gst.MessageType.ASYNC_DONE, Gst.MessageType.NEW_CLOCK):
            log("%s", message)
        elif t == Gst.MessageType.STATE_CHANGED:
            _, new_state, _ = message.parse_state_changed()
            log("state-changed on %s: %s", message.src, Gst.Element.state_get_name(new_state))
            state = self.do_get_state(new_state)
            if isinstance(message.src, Gst.Pipeline):
                self.update_state(state)
                self.idle_emit("state-changed", state)
        elif t == Gst.MessageType.DURATION_CHANGED:
            log("duration changed: %s", message)
        elif t == Gst.MessageType.LATENCY:
            log("latency message from %s: %s", message.src, message)
        elif t == Gst.MessageType.INFO:
            self.gstloginfo("pipeline message: %s", message)
        elif t == Gst.MessageType.WARNING:
            w = message.parse_warning()
            self.gstlogwarn("pipeline warning: %s", w[0].message)
            for x in w[1:]:
                for l in x.split(":"):
                    if l:
                        if l.startswith("\n"):
                            l = l.strip("\n")+" "
                            for lp in l.split(". "):
                                lp = lp.strip()
                                if lp:
                                    self.gstlogwarn(" %s", lp)
                        else:
                            self.gstlogwarn("                  %s", l.strip("\n\r"))
        elif t in (Gst.MessageType.NEED_CONTEXT, Gst.MessageType.HAVE_CONTEXT):
            log("context message: %s", message)
        elif t == Gst.MessageType.QOS:
            qos = message.parse_qos()
            log.warn(f"qos={qos}")
        else:
            self.gstlogwarn("unhandled bus message type %s: %s", t, message)
        self.emit_info()
        return GST_FLOW_OK

    def parse_element_message(self, message) -> None:
        structure = message.get_structure()
        props = {
            "seqnum": int(message.seqnum),
        }
        for i in range(structure.n_fields()):
            name = structure.nth_field_name(i)
            props[name] = structure.get_value(name)
        self.do_parse_element_message(message, message.src.get_name(), props)

    def do_parse_element_message(self, message, name, props=None) -> None:
        log("do_parse_element_message%s", (message, name, props))

    def get_element_properties(self, element, *properties, ignore_missing=False) -> dict[str, Any]:
        info = {}
        for x in properties:
            try:
                v = element.get_property(x)
                if v >= 0:
                    info[x] = v
            except TypeError as e:
                if not ignore_missing and first_time("gst-property-%s" % x):
                    log("'%s' not found in %r", x, self)
                    log.warn("Warning: %s", e)
            except Exception as e:
                log.warn("Warning: %s (%s)", e, type(e))
        return info
