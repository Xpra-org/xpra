# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time

from xpra.sound.gstreamer_util import gst
from xpra.log import Logger
log = Logger("sound")

from xpra.gtk_common.gobject_compat import import_gobject
from xpra.gtk_common.gobject_util import one_arg_signal
gobject = import_gobject()


class SoundPipeline(gobject.GObject):

    __generic_signals__ = {
        "state-changed"     : one_arg_signal,
        "bitrate-changed"   : one_arg_signal,
        "error"             : one_arg_signal,
        "new-stream"        : one_arg_signal,
        }

    def __init__(self, codec):
        gobject.GObject.__init__(self)
        self.codec = codec
        self.codec_description = codec
        self.codec_mode = ""
        self.bus = None
        self.bus_message_handler_id = None
        self.bitrate = -1
        self.pipeline = None
        self.pipeline_str = ""
        self.start_time = 0
        self.state = "stopped"
        self.buffer_count = 0
        self.byte_count = 0

    def idle_emit(self, sig, *args):
        gobject.idle_add(self.emit, sig, *args)

    def get_info(self):
        info = {"codec"             : self.codec,
                "codec_description" : self.codec_description,
                "state"             : self.get_state(),
                "buffers"           : self.buffer_count,
                "bytes"             : self.byte_count,
                "pipeline"          : self.pipeline_str,
                "volume"            : self.get_volume(),
                "pid"               : os.getpid(),
                }
        if self.codec_mode:
            info["codec_mode"] = self.codec_mode
        if self.bitrate>0:
            info["speaker.bitrate"] = self.bitrate
        return info

    def setup_pipeline_and_bus(self, elements):
        log("pipeline elements=%s", elements)
        self.pipeline_str = " ! ".join([x for x in elements if x is not None])
        log("pipeline=%s", self.pipeline_str)
        self.start_time = time.time()
        self.pipeline = gst.parse_launch(self.pipeline_str)
        self.bus = self.pipeline.get_bus()
        self.bus_message_handler_id = self.bus.connect("message", self.on_message)
        self.bus.add_signal_watch()

    def do_get_state(self, state):
        if not self.pipeline:
            return  "stopped"
        return {gst.STATE_PLAYING   : "active",
                gst.STATE_PAUSED    : "paused",
                gst.STATE_NULL      : "stopped",
                gst.STATE_READY     : "ready"}.get(state, "unknown")

    def get_state(self):
        return self.state

    def update_bitrate(self, new_bitrate):
        if new_bitrate==self.bitrate:
            return
        self.bitrate = new_bitrate
        log("new bitrate: %s", self.bitrate)
        #self.emit("bitrate-changed", new_bitrate)


    def set_volume(self, volume=100):
        if self.volume:
            self.volume.set_property("volume", volume/100.0)

    def get_volume(self):
        if self.volume:
            return int(self.volume.get_property("volume")*100)
        return 0


    def start(self):
        log("SoundPipeline.start()")
        self.idle_emit("new-stream", self.codec)
        self.state = "active"
        self.pipeline.set_state(gst.STATE_PLAYING)
        log("SoundPipeline.start() done")

    def stop(self):
        if not self.pipeline:
            return
        log("SoundPipeline.stop()")
        #uncomment this to see why we end up calling stop()
        #import traceback
        #for x in traceback.format_stack():
        #    for s in x.split("\n"):
        #        v = s.replace("\r", "").replace("\n", "")
        #        if v:
        #            log(v)
        self.state = "stopped"
        self.pipeline.set_state(gst.STATE_NULL)
        self.volume = None
        log("SoundPipeline.stop() done")

    def cleanup(self):
        self.stop()
        if not self.bus:
            return
        log("SoundPipeline.cleanup()")
        self.bus.remove_signal_watch()
        if self.bus_message_handler_id:
            self.bus.disconnect(self.bus_message_handler_id)
        self.bus = None
        self.pipeline = None
        self.codec = None
        self.bitrate = -1
        self.state = None
        log("SoundPipeline.cleanup() done")

    def on_message(self, bus, message):
        #log("on_message(%s, %s)", bus, message)
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.pipeline.set_state(gst.STATE_NULL)
            log.info("sound source EOS")
            self.state = "stopped"
            self.idle_emit("state-changed", self.state)
        elif t == gst.MESSAGE_ERROR:
            self.pipeline.set_state(gst.STATE_NULL)
            err, details = message.parse_error()
            log.error("sound source pipeline error: %s / %s", err, details)
            self.state = "error"
            self.idle_emit("state-changed", self.state)
        elif t == gst.MESSAGE_TAG:
            try:
                #Gst 0.10:
                assert message.structure is not None, "test for pygst / 0.10"
                self.parse_message0(message)
            except:
                #Gst 1.0:
                self.parse_message1(message)
        elif t == gst.MESSAGE_STREAM_STATUS:
            log("stream status: %s", message)
        elif t == gst.MESSAGE_STREAM_START:
            log("stream start: %s", message)
        elif t in (gst.MESSAGE_LATENCY, gst.MESSAGE_ASYNC_DONE, gst.MESSAGE_NEW_CLOCK):
            log("%s", message)
        elif t == gst.MESSAGE_STATE_CHANGED:
            if isinstance(message.src, gst.Pipeline):
                _, new_state, _ = message.parse_state_changed()
                log("new-state=%s", gst.element_state_get_name(new_state))
                self.state = self.do_get_state(new_state)
                self.idle_emit("state-changed", self.state)
            else:
                log("state changed: %s", message)
        elif t == gst.MESSAGE_DURATION:
            d = message.parse_duration()
            try:
                v = d[1]
                if v>0:
                    log("duration changed: %s", v)
            except:
                log("duration changed: %s", d)
        elif t == gst.MESSAGE_LATENCY:
            log.info("Latency message from %s: %s", message.src, message)
        elif t == gst.MESSAGE_INFO:
            log.info("Sound pipeline message: %s", message)
        elif t == gst.MESSAGE_WARNING:
            w = message.parse_warning()
            log.warn("pipeline warning: %s", w[0].message)
            log.info("pipeline warning: %s", w[1:])
        else:
            log.info("unhandled bus message type %s: %s", t, message)

    def parse_message0(self, message):
        #message parsing code for GStreamer 0.10
        structure = message.structure
        found = False
        if structure.has_field("bitrate"):
            new_bitrate = int(structure["bitrate"])
            self.update_bitrate(new_bitrate)
            found = True
        if structure.has_field("codec"):
            desc = structure["codec"]
            if self.codec_description!=desc:
                log.info("codec: %s", desc)
                self.codec_description = desc
            found = True
        if structure.has_field("audio-codec"):
            desc = structure["audio-codec"]
            if self.codec_description!=desc:
                log.info("using audio codec: %s", desc)
                self.codec_description = desc
            found = True
        if structure.has_field("mode"):
            mode = structure["mode"]
            if self.codec_mode!=mode:
                log("mode: %s", mode)
                self.codec_mode = mode
            found = True
        if not found:
            #these, we know about, so we just log them:
            for x in ("minimum-bitrate", "maximum-bitrate", "channel-mode"):
                if structure.has_field(x):
                    v = structure[x]
                    log("tag message: %s = %s", x, v)
                    return      #handled
            log.info("unknown sound pipeline tag message %s: %s", message, structure)

    def parse_message1(self, message):
        #message parsing code for GStreamer 1.x
        taglist = message.parse_tag()
        tags = [taglist.nth_tag_name(x) for x in range(taglist.n_tags())]
        log("bus message with tags=%s", tags)
        if "bitrate" in tags:
            new_bitrate = taglist.get_uint("bitrate")
            if new_bitrate[0] is True:
                self.update_bitrate(new_bitrate[1])
        if "codec" in tags:
            desc = taglist.get_string("codec")
            if desc[0] is True and self.codec_description!=desc[1]:
                log.info("codec: %s", desc[1])
                self.codec_description = desc[1]
        if "audio-codec" in tags:
            desc = taglist.get_string("audio-codec")
            if desc[0] is True and self.codec_description!=desc[1]:
                log.info("using audio codec: %s", desc[1])
                self.codec_description = desc[1]
        if "mode" in tags:
            mode = taglist.get_string("mode")
            if mode[0] is True and self.codec_mode!=mode[1]:
                log("mode: %s", mode[1])
                self.codec_mode = mode[1]
        if len([x for x in tags if x in ("bitrate", "codec", "audio-codec", "mode")])==0:
            #no match yet
            if len([x for x in tags if x in ("minimum-bitrate", "maximum-bitrate", "channel-mode")])==0:
                structure = message.get_structure()
                log.info("unknown sound pipeline tag message: %s", structure.to_string())
