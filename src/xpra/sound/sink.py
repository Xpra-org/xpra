#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os
import gobject
gobject.threads_init()

from xpra.sound.sound_pipeline import SoundPipeline, debug
from xpra.sound.pulseaudio_util import has_pa
from xpra.sound.gstreamer_util import plugin_str, get_decoders, MP3, CODECS, gst
from wimpiggy.util import one_arg_signal, no_arg_signal
from wimpiggy.log import Logger
log = Logger()

QUEUE_TIME = int(os.environ.get("XPRA_SOUND_QUEUE_TIME", "20"))*1000000

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


class SoundSink(SoundPipeline):

    __gsignals__ = {
        "underrun": one_arg_signal,
        "eos": no_arg_signal
        }

    def __init__(self, sink_type="autoaudiosink", options={}, codec=MP3, decoder_options={}):
        assert sink_type in SINKS, "invalid sink: %s" % sink_type
        decoders = get_decoders(codec)
        assert len(decoders)>0, "no decoders found for %s" % codec
        SoundPipeline.__init__(self, codec)
        self.data_needed = 0
        self.sink_type = sink_type
        decoder = decoders[0]
        decoder_str = plugin_str(decoder, decoder_options)
        pipeline_els = ["appsrc name=src",
                        decoder_str]
        if QUEUE_TIME>0:
            pipeline_els.append("queue max-size-time=%s" % QUEUE_TIME)
        pipeline_els += ["volume name=volume",
                         "audioconvert",
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

    def cleanup(self):
        SoundPipeline.cleanup(self)
        self.sink_type = ""
        self.volume = None
        self.src = None

    def eos(self):
        debug("eos()")
        self.src.emit('end-of-stream')
        self.cleanup()

    def set_volume(self, volume):
        assert volume>=0 and volume<=10
        self.volume.set_property("volume", volume)

    def add_data(self, data):
        debug("add_data(%s bytes)", len(data))
        if self.src:
            self.src.emit("push-buffer", gst.Buffer(data))


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
    def eos(*args):
        print("eos")
        gobject.idle_add(gtk.main_quit)
    ss.connect("eos", eos)
    ss.start()

    import signal
    def deadly_signal(*args):
        gtk.main_quit()
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    def check_for_end(*args):
        if not ss.pipeline:
            log.info("pipeline closed")
            gtk.main_quit()
        return True
    gobject.timeout_add(1000, check_for_end)

    import gtk
    gtk.main()


if __name__ == "__main__":
    main()
