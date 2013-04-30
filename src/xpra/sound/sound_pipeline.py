#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.signal_object import SignalObject
from xpra.sound.gstreamer_util import gst
from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_SOUND_DEBUG")


class SoundPipeline(SignalObject):

    __generic_signals__ = [
        "state-changed",
        "bitrate-changed",
        "error"
        ]

    def __init__(self, codec):
        SignalObject.__init__(self)
        self.add_signals(SoundPipeline.__generic_signals__)
        self.codec = codec
        self.codec_description = codec
        self.codec_mode = ""
        self.bus = None
        self.bus_message_handler_id = None
        self.bitrate = -1
        self.pipeline = None
        self.state = "stopped"

    def setup_pipeline_and_bus(self, elements):
        debug("pipeline elements=%s", elements)
        pipeline_str = " ! ".join([x for x in elements if x is not None])
        debug("pipeline=%s", pipeline_str)
        self.pipeline = gst.parse_launch(pipeline_str)
        self.bus = self.pipeline.get_bus()
        self.bus_message_handler_id = self.bus.connect("message", self.on_message)
        self.bus.add_signal_watch()

    def do_get_state(self, state):
        if not self.pipeline:
            return  "stopped"
        if state==gst.STATE_PLAYING:
            return  "active"
        if state==gst.STATE_NULL:
            return  "stopped"
        return  "unknown"

    def get_state(self):
        return self.state

    def update_bitrate(self, new_bitrate):
        if new_bitrate==self.bitrate:
            return
        self.bitrate = new_bitrate
        log("new bitrate: %s", self.bitrate)
        #self.emit("bitrate-changed", new_bitrate)

    def get_bitrate(self):
        return self.bitrate

    def start(self):
        debug("SoundPipeline.start()")
        self.state = "active"
        self.pipeline.set_state(gst.STATE_PLAYING)
        debug("SoundPipeline.start() done")

    def stop(self):
        debug("SoundPipeline.stop()")
        self.state = "stopped"
        self.pipeline.set_state(gst.STATE_NULL)
        debug("SoundPipeline.stop() done")

    def cleanup(self):
        debug("SoundPipeline.cleanup()")
        SignalObject.cleanup(self)
        self.stop()
        self.bus.remove_signal_watch()
        if self.bus_message_handler_id:
            self.bus.disconnect(self.bus_message_handler_id)
        self.bus = None
        self.pipeline = None
        self.codec = None
        self.bitrate = -1
        self.state = None
        debug("SoundPipeline.cleanup() done")

    def on_message(self, bus, message):
        #debug("on_message(%s, %s)", bus, message)
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.pipeline.set_state(gst.STATE_NULL)
            log.info("sound source EOS")
            self.state = "stopped"
            self.emit("state-changed", self.state)
        elif t == gst.MESSAGE_ERROR:
            self.pipeline.set_state(gst.STATE_NULL)
            err, details = message.parse_error()
            log.error("sound source pipeline error: %s / %s", err, details)
            self.state = "error"
            self.emit("state-changed", self.state)
        elif t == gst.MESSAGE_TAG:
            if message.structure.has_field("bitrate"):
                new_bitrate = int(message.structure["bitrate"])
                self.update_bitrate(new_bitrate)
            elif message.structure.has_field("codec"):
                desc = message.structure["codec"]
                if self.codec_description!=desc:
                    log.info("codec: %s", desc)
                    self.codec_description = desc
            elif message.structure.has_field("audio-codec"):
                desc = message.structure["audio-codec"]
                if self.codec_description!=desc:
                    log.info("using audio codec: %s", desc)
                    self.codec_description = desc
            elif message.structure.has_field("mode"):
                mode = message.structure["mode"]
                if self.codec_mode!=mode:
                    log("mode: %s", mode)
                    self.codec_mode = mode
            else:
                log.info("unknown tag message: %s", message)
        elif t == gst.MESSAGE_STREAM_STATUS:
            debug("stream status: %s", message)
        elif t in (gst.MESSAGE_LATENCY, gst.MESSAGE_ASYNC_DONE, gst.MESSAGE_NEW_CLOCK):
            debug("%s", message)
        elif t == gst.MESSAGE_STATE_CHANGED:
            if isinstance(message.src, gst.Pipeline):
                _, new_state, _ = message.parse_state_changed()
                debug("new-state=%s", gst.element_state_get_name(new_state))
                self.state = self.do_get_state(new_state)
                self.emit("state-changed", self.state)
            else:
                debug("state changed: %s", message)
        elif t == gst.MESSAGE_DURATION:
            d = message.parse_duration()
            debug("duration changed: %s", d)
        elif t == gst.MESSAGE_LATENCY:
            log.info("Latency message from %s: %s", message.src, message)
        elif t == gst.MESSAGE_WARNING:
            w = message.parse_warning()
            log.warn("pipeline warning: %s", w[0].message)
            log.info("pipeline warning: %s", w[1:])
        else:
            log.info("unhandled bus message type %s: %s / %s", t, message, message.structure)
