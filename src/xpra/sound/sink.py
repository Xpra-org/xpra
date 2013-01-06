#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os
import gobject
gobject.threads_init()

from xpra.sound.pulseaudio_util import has_pa
from xpra.sound.gstreamer_util import plugin_str, get_decoders, MP3, CODECS
import gst
from wimpiggy.util import AutoPropGObjectMixin, one_arg_signal, no_arg_signal
from wimpiggy.log import Logger
log = Logger()

DEBUG_SOUND = os.environ.get("XPRA_DEBUG_SOUND", "0")=="1"
if DEBUG_SOUND:
    debug = log.info
else:
    debug = log.debug


SINKS = ["autoaudiosink"]
if has_pa():
    SINKS.append("pulsesink")
if sys.platform.startswith("darwin"):
    SINKS.append("osxaudiosink")
elif sys.platform.startswith("win"):
    SINKS.append("directsoundsink")
if os.name=="posix":
    SINKS += ["alsasink", "osssink", "oss4sink", "jackaudiosink"]

def sink_has_device_attribute(sink):
    return sink not in ("autoaudiosink", "jackaudiosink", "directsoundsink")


class SoundSink(AutoPropGObjectMixin, gobject.GObject):

    __gsignals__ = {
        "underrun": one_arg_signal,
        "eos": no_arg_signal
        }

    def __init__(self, sink_type="autoaudiosink", options={}, codec=MP3, decoder_options={}):
        assert sink_type in SINKS, "invalid sink: %s" % sink_type
        decoders = get_decoders(codec)
        assert len(decoders)>0, "no decoders found for %s" % codec
        super(gobject.GObject, self).__init__()
        super(AutoPropGObjectMixin, self).__init__()
        self.codec = codec
        self.data = ""
        self.data_needed = 0
        self.sink_type = sink_type
        decoder = decoders[0]
        decoder_str = plugin_str(decoder, decoder_options)
        pipeline_els = ["appsrc name=src",
                        decoder_str,
                        "volume name=volume",
                        sink_type]
        pipeline_str = " ! ".join(pipeline_els)
        debug("soundsink pipeline=%s", pipeline_str)
        self.pipeline = gst.parse_launch(pipeline_str)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)
        self.src = self.pipeline.get_by_name("src")
        debug("src %s", self.src)
        self.volume = self.pipeline.get_by_name("volume")
        self.src.connect("need-data", self.need_data)
        self.src.connect("enough-data", self.on_enough_data)
        self.src.set_property("emit-signals", True)
        #src.set_property("drop", False)
        #src.set_property("sync", False)
        #src.set_property("max-buffers", 1)

    def start(self):
        assert self.pipeline
        self.pipeline.set_state(gst.STATE_PLAYING)

    def stop(self):
        assert self.pipeline
        self.pipeline.set_state(gst.STATE_NULL)

    def cleanup(self):
        self.codec = None
        self.data = ""
        self.sink_type = ""
        self.pipeline = None
        self.volume = None
        self.src = None

    def eos(self):
        debug("eos()")
        self.src.emit('end-of-stream')

    def set_volume(self, volume):
        assert volume>=0 and volume<=10
        self.volume.set_property("volume", volume)

    def add_data(self, data):
        debug("add_data(%s bytes) we already have %s bytes", len(data), len(self.data))
        self.data += data
        if self.data_needed>0:
            self.push_buffer()

    def need_data(self, src_arg, needed):
        debug("need_data: %s bytes, we have %s", needed, len(self.data))
        self.data_needed = needed
        if len(self.data)>0:
            self.push_buffer()

    def push_buffer(self):
        needed = self.data_needed
        if len(self.data)<needed:
            chunk = self.data
            self.data = ""
            self.data_needed = needed-len(self.data)
        else:
            chunk = self.data[:self.data_needed]
            self.data = self.data[self.data_needed:]
            self.data_needed = 0
        debug("push_buffer() adding %s bytes, %s still needed", len(chunk), self.data_needed)
        self.src.emit("push-buffer", gst.Buffer(chunk))

    def on_message(self, bus, message):
        debug("bus message: %s", message)
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.pipeline.set_state(gst.STATE_NULL)
        elif t == gst.MESSAGE_ERROR:
            self.pipeline.set_state(gst.STATE_NULL)
            err, details = message.parse_error()
            log.error("Pipeline error: %s / %s", err, details)

    def on_enough_data(self, *args):
        debug("on_enough_data(%s)", args)

gobject.type_register(SoundSink)


def main():
    import os.path
    if len(sys.argv) not in (2, 3):
        print("usage: %s mp3filename [codec]" % sys.argv[0])
        sys.exit(1)
        return
    filename = sys.argv[1]
    if not os.path.exists(filename):
        print("file %s does not exist" % filename)
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
    f = open(filename, "rb")
    data = f.read()
    f.close()
    print("loaded %s bytes from %s" % (len(data), filename))
    ss = SoundSink(codec=codec)
    ss.add_data(data)
    ss.start()

    import signal
    def deadly_signal(*args):
        gtk.main_quit()
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    def check_for_end(*args):
        if not(ss.data):
            log.info("no more data")
            gtk.main_quit()
        return True
    gobject.timeout_add(1000, check_for_end)

    import gtk
    gtk.main()


if __name__ == "__main__":
    main()
