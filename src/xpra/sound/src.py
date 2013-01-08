#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os
import gobject
gobject.threads_init()

from xpra.sound.pulseaudio_util import has_pa
from xpra.sound.gstreamer_util import plugin_str, get_encoders, MP3, CODECS
import gst
from wimpiggy.util import AutoPropGObjectMixin, one_arg_signal
from wimpiggy.log import Logger
log = Logger()

DEBUG_SOUND = os.environ.get("XPRA_SOUND_DEBUG", "0")=="1"
if DEBUG_SOUND:
    debug = log.info
else:
    debug = log.debug


BITRATES = [8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
DEFAULT_BITRATE=24

SOURCES = ["autoaudiosrc"]
if has_pa():
    SOURCES.append("pulsesrc")
if sys.platform.startswith("darwin"):
    SOURCES.append("osxaudiosrc")
elif sys.platform.startswith("win"):
    SOURCES.append("directsoundsrc")
if os.name=="posix":
    SOURCES += ["alsasrc", "jackaudiosrc",
                "osssrc", "oss4src",
                "osxaudiosrc", "jackaudiosrc"]
SOURCES.append("audiotestsrc")

def source_has_device_attribute(source):
    return source not in ("autoaudiosrc", "jackaudiosink", "directsoundsrc")


class SoundSource(AutoPropGObjectMixin, gobject.GObject):

    __gsignals__ = {
        "new-buffer": one_arg_signal,
        "state-change": one_arg_signal,
        }

    def __init__(self, src_type="autoaudiosrc", src_options={}, codec=MP3, encoder_options={}):
        assert src_type in SOURCES
        encoders = get_encoders(codec)
        assert len(encoders)>0, "no encoders found for %s" % codec
        super(gobject.GObject, self).__init__()
        super(AutoPropGObjectMixin, self).__init__()
        self.codec = codec
        self.data = ""
        self.src_type = src_type
        self.bitrate = -1
        source_str = plugin_str(src_type, src_options)
        encoder = encoders[0]
        encoder_str = plugin_str(encoder, encoder_options)
        pipeline_els = [source_str,
                        "volume name=volume",
                        "audioconvert",
                        encoder_str,
                        "appsink name=sink"]
        pipeline_str = " ! ".join(pipeline_els)
        debug("soundsource pipeline=%s", pipeline_str)
        self.pipeline = gst.parse_launch(pipeline_str)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)
        self.sink = self.pipeline.get_by_name("sink")
        debug("sink %s", self.sink)
        self.state = "stopped"
        self.volume = self.pipeline.get_by_name("volume")
        self.sink.set_property("emit-signals", True)
        self.sink.set_property("drop", False)
        self.sink.set_property("sync", False)
        self.sink.connect("new-buffer", self.on_new_buffer)
        self.sink.connect("new-preroll", self.on_new_preroll)
        #self.sink.set_property("max-buffers", 1)

    def do_get_state(self):
        if not self.pipeline:
            return  "stopped"
        state = self.pipeline.get_state()
        if len(state)==3:
            if state[1]==gst.STATE_PLAYING:
                return  "active"
            if state[1]==gst.STATE_NULL:
                return  "stopped"
        return  "unknown"

    def get_state(self):
        return  self.state_may_have_changed()

    def state_may_have_changed(self, *args):
        new_state = self.do_get_state()
        if new_state!=self.state:
            log.info("new sound source pipeline state: %s", new_state)
            self.state = new_state
            self.emit("state-change", self.get_state())
        return new_state

    def get_bitrate(self):
        return self.bitrate

    def start(self):
        self.pipeline.set_state(gst.STATE_PLAYING)

    def stop(self):
        self.pipeline.set_state(gst.STATE_NULL)

    def cleanup(self):
        self.codec = None
        self.data = ""
        self.src_type = ""
        self.pipeline = None
        self.volume = None
        self.sink = None
        self.bitrate = -1
        self.state = None

    def set_mute(self, mute):
        self.volume.set_property('mute', mute)

    def set_volume(self, volume):
        assert volume>=0 and volume<=100
        self.volume.set_property('volume', float(volume)/100.0)

    def on_new_preroll(self, appsink):
        buf = appsink.emit('pull-preroll')
        debug('new preroll: %s bytes', len(buf))
        self.emit("new-buffer", str(buf))

    def on_new_buffer_list(self, appsink):
        buf = appsink.emit('pull-buffer-list')
        debug('new buffer list', len(buf))

    def on_new_buffer(self, bus, *args):
        buf = self.sink.emit("pull-buffer")
        debug("new-buffer: %s bytes", len(buf))
        self.emit("new-buffer", str(buf))

    def on_message(self, bus, message):
        debug("on_message(%s, %s)", bus, message)
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.pipeline.set_state(gst.STATE_NULL)
            log.info("sound source EOS")
            self.state_may_have_changed()
        elif t == gst.MESSAGE_ERROR:
            self.pipeline.set_state(gst.STATE_NULL)
            err, details = message.parse_error()
            log.error("sound source pipeline error: %s / %s", err, details)
            self.state_may_have_changed()
        elif t == gst.MESSAGE_TAG:
            if message.structure.has_field("bitrate"):
                self.bitrate = int(message.structure["bitrate"])
                log.info("bitrate: %s", self.bitrate)
            if message.structure.has_field("codec"):
                log.info("codec: %s", message.structure["codec"])
            else:
                log.info("unknown tag message: %s", message)
        elif t == gst.MESSAGE_STREAM_STATUS:
            debug("stream status: %s", message)
            self.state_may_have_changed()
        elif t in (gst.MESSAGE_LATENCY, gst.MESSAGE_ASYNC_DONE, gst.MESSAGE_NEW_CLOCK):
            debug("%s", message)
        elif t == gst.MESSAGE_STATE_CHANGED:
            if isinstance(message.src, gst.Pipeline):
                _, new, _ = message.parse_state_changed()
                debug("new-state=%s", gst.element_state_get_name(new))
            else:
                debug("state changed: %s", message)
            self.state_may_have_changed()
        else:
            log.info("unhandled bus message type %s: %s / %s", t, message, message.structure)
            

gobject.type_register(SoundSource)


def main():
    import os.path
    if len(sys.argv) not in (2, 3):
        print("usage: %s mp3filename" % sys.argv[0])
        sys.exit(1)
        return
    filename = sys.argv[1]
    if os.path.exists(filename):
        print("file %s already exists" % filename)
        sys.exit(2)
        return
    if len(sys.argv)==3:
        codec = sys.argv[2]
        if codec not in CODECS:
            print("invalid codec: %s" % codec)
            sys.exit(2)
            return
    else:
        codec = MP3

    import logging
    logging.basicConfig(format="%(asctime)s %(message)s")
    logging.root.setLevel(logging.INFO)
    f = open(filename, "wb")
    from xpra.sound.pulseaudio_util import get_pa_device_options
    monitor_devices = get_pa_device_options(True, False)
    log.info("found pulseaudio monitor devices: %s", monitor_devices)
    if len(monitor_devices)==0:
        log.warn("could not detect any pulseaudio monitor devices - will use a test source")
        ss = SoundSource("audiotestsrc", src_options={"wave":2, "freq":100, "volume":0.4}, codec=codec)
    else:
        monitor_device = monitor_devices.items()[0][0]
        log.info("using pulseaudio source device: %s", monitor_device)
        ss = SoundSource("pulsesrc", {"device" : monitor_device}, codec, {})
    def new_buffer(ss, data):
        f.write(data)
    ss.connect("new-buffer", new_buffer)
    ss.start()

    import signal
    def deadly_signal(*args):
        gtk.main_quit()
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    import gtk
    gtk.main()

    log.info("wrote %s bytes to %s", f.tell(), filename)
    f.close()


if __name__ == "__main__":
    main()
