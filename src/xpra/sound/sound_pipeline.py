#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import gobject
gobject.threads_init()

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
        "state-change": one_arg_signal,
        }

    def __init__(self, codec):
        super(gobject.GObject, self).__init__()
        super(AutoPropGObjectMixin, self).__init__()
        self.codec = codec
        self.bitrate = -1
        self.pipeline = None
        self.state = None

    def do_get_state(self):
        if not self.pipeline:
            return  "stopped"
        log.info("do_get_state calling pipeline")
        state = self.pipeline.get_state()
        log.info("state=%s", state)
        if len(state)==3:
            if state[1]==gst.STATE_PLAYING:
                return  "active"
            if state[1]==gst.STATE_NULL:
                return  "stopped"
        return  "unknown"

    def get_state(self):
        self.state_may_have_changed()
        return self.state

    def state_may_have_changed(self, *args):
        new_state = self.do_get_state()
        log.info("state=%s, new_state=%s", self.state, new_state)
        if new_state!=self.state:
            log.info("new sound source pipeline state: %s", new_state)
            self.state = new_state
            self.emit("state-change", new_state)
        return False

    def get_bitrate(self):
        return self.bitrate

    def start(self):
        self.pipeline.set_state(gst.STATE_PLAYING)

    def stop(self):
        self.pipeline.set_state(gst.STATE_NULL)

    def cleanup(self):
        self.codec = None
        self.pipeline = None
        self.bitrate = -1
        self.state = None

    def on_message(self, bus, message):
        #debug("on_message(%s, %s)", bus, message)
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.pipeline.set_state(gst.STATE_NULL)
            log.info("sound source EOS")
            gobject.idle_add(self.state_may_have_changed)
        elif t == gst.MESSAGE_ERROR:
            self.pipeline.set_state(gst.STATE_NULL)
            err, details = message.parse_error()
            log.error("sound source pipeline error: %s / %s", err, details)
            gobject.idle_add(self.state_may_have_changed)
        elif t == gst.MESSAGE_TAG:
            if message.structure.has_field("bitrate"):
                self.bitrate = int(message.structure["bitrate"])
                log.info("bitrate: %s", self.bitrate)
            elif message.structure.has_field("codec"):
                log.info("codec: %s", message.structure["codec"])
            else:
                log.info("unknown tag message: %s", message)
        elif t == gst.MESSAGE_STREAM_STATUS:
            debug("stream status: %s", message)
            gobject.idle_add(self.state_may_have_changed)
        elif t in (gst.MESSAGE_LATENCY, gst.MESSAGE_ASYNC_DONE, gst.MESSAGE_NEW_CLOCK):
            debug("%s", message)
        elif t == gst.MESSAGE_STATE_CHANGED:
            if isinstance(message.src, gst.Pipeline):
                _, new, _ = message.parse_state_changed()
                debug("new-state=%s", gst.element_state_get_name(new))
            else:
                debug("state changed: %s", message)
            gobject.idle_add(self.state_may_have_changed)
        else:
            log.info("unhandled bus message type %s: %s / %s", t, message, message.structure)


gobject.type_register(SoundPipeline)
