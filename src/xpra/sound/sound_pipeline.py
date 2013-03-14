#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import gobject

from xpra.sound.gstreamer_util import gst
from wimpiggy.util import AutoPropGObjectMixin, one_arg_signal
from wimpiggy.log import Logger
log = Logger()

DEBUG_SOUND = os.environ.get("XPRA_SOUND_DEBUG", "0")=="1"
if DEBUG_SOUND:
    debug = log.info
else:
    debug = log.debug


class SoundPipeline(AutoPropGObjectMixin, gobject.GObject):

    __gsignals__ = {
        "state-changed": one_arg_signal,
        "bitrate-changed": one_arg_signal,
        }

    def __init__(self, codec):
        super(gobject.GObject, self).__init__()
        super(AutoPropGObjectMixin, self).__init__()
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
        self.state = "active"
        self.pipeline.set_state(gst.STATE_PLAYING)

    def stop(self):
        self.state = "stopped"
        self.pipeline.set_state(gst.STATE_NULL)

    def cleanup(self):
        self.stop()
        self.bus.remove_signal_watch()
        if self.bus_message_handler_id:
            self.bus.disconnect(self.bus_message_handler_id)
        self.bus = None
        self.pipeline = None
        self.codec = None
        self.bitrate = -1
        self.state = None

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


gobject.type_register(SoundPipeline)
