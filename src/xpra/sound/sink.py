#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os
import gobject

from xpra.sound.sound_pipeline import SoundPipeline, debug
from xpra.sound.pulseaudio_util import has_pa
from xpra.sound.gstreamer_util import plugin_str, get_decoder_parser, MP3, CODECS, gst
from wimpiggy.util import one_arg_signal, no_arg_signal
from wimpiggy.log import Logger
log = Logger()

SINKS = ["autoaudiosink"]
DEFAULT_SINK = SINKS[0]
if has_pa():
    SINKS.append("pulsesink")
if sys.platform.startswith("darwin"):
    SINKS.append("osxaudiosink")
    DEFAULT_SINK = "osxaudiosink"
elif sys.platform.startswith("win"):
    SINKS.append("directsoundsink")
    DEFAULT_SINK = "directsoundsink"
if os.name=="posix":
    SINKS += ["alsasink", "osssink", "oss4sink", "jackaudiosink"]

GST_QUEUE_NO_LEAK             = 0
GST_QUEUE_LEAK_UPSTREAM       = 1
GST_QUEUE_LEAK_DOWNSTREAM     = 2

QUEUE_LEAK = int(os.environ.get("XPRA_SOUND_QUEUE_LEAK", GST_QUEUE_NO_LEAK))
QUEUE_TIME = int(os.environ.get("XPRA_SOUND_QUEUE_TIME", "80"))*1000000
DEFAULT_SINK = os.environ.get("XPRA_SOUND_SINK", DEFAULT_SINK)
if DEFAULT_SINK not in SINKS:
    log.error("invalid default sound sink: '%s' is not in %s, using %s instead", DEFAULT_SINK, SINKS, SINKS[0])
    DEFAULT_SINK = SINKS[0]

VOLUME = True
QUEUE = True


def sink_has_device_attribute(sink):
    return sink not in ("autoaudiosink", "jackaudiosink", "directsoundsink")


class SoundSink(SoundPipeline):

    __gsignals__ = {
        "underrun": one_arg_signal,
        "eos": no_arg_signal
        }

    def __init__(self, sink_type=DEFAULT_SINK, options={}, codec=MP3, decoder_options={}):
        assert sink_type in SINKS, "invalid sink: %s" % sink_type
        decoder, parser = get_decoder_parser(codec)
        SoundPipeline.__init__(self, codec)
        self.sink_type = sink_type
        decoder_str = plugin_str(decoder, decoder_options)
        pipeline_els = []
        pipeline_els.append("appsrc name=src")
        pipeline_els.append(parser)
        pipeline_els.append(decoder_str)
        if VOLUME:
            pipeline_els.append("volume name=volume")
        pipeline_els.append("audioconvert")
        pipeline_els.append("audioresample")
        if QUEUE:
            if QUEUE_TIME>0:
                pipeline_els.append("queue name=queue max-size-time=%s leaky=%s" % (QUEUE_TIME, QUEUE_LEAK))
            else:
                pipeline_els.append("queue leaky=%s" % QUEUE_LEAK)
        pipeline_els.append(sink_type)
        self.setup_pipeline_and_bus(pipeline_els)
        self.volume = self.pipeline.get_by_name("volume")
        self.src = self.pipeline.get_by_name("src")
        self.src.set_property('emit-signals', True)
        self.src.set_property('stream-type', 'stream')
        self.src.set_property('block', False)
        self.src.set_property('format', 4)
        self.src.set_property('is-live', True)
        if QUEUE:
            self.queue = self.pipeline.get_by_name("queue")
            def overrun(*args):
                debug("sound sink queue overrun")
            def underrun(*args):
                debug("sound sink queue underrun")
            self.queue.connect("overrun", overrun)
            self.queue.connect("underrun", underrun)
        else:
            self.queue = None
        self.src.connect("need-data", self.need_data)
        self.src.connect("enough-data", self.on_enough_data)

    def cleanup(self):
        SoundPipeline.cleanup(self)
        self.sink_type = ""
        self.volume = None
        self.src = None

    def set_queue_delay(self, ms):
        assert self.queue
        assert ms>0
        self.queue.set_property("max-size-time", ms*1000000)
        log("queue delay set to %s, current-level-time=%s", ms, int(self.queue.get_property("current-level-time")/1000/1000))

    def set_mute(self, mute):
        self.volume.set_property('mute', mute)

    def is_muted(self):
        return bool(self.volume.get_property("mute"))

    def get_volume(self):
        assert self.volume
        return  self.volume.get_property("volume")

    def set_volume(self, volume):
        assert self.volume
        assert volume>=0 and volume<=100
        self.volume.set_property('volume', float(volume)/10.0)

    def eos(self):
        debug("eos()")
        if self.src:
            self.src.emit('end-of-stream')
        self.cleanup()

    def add_data(self, data, metadata=None):
        debug("sound sink: adding %s bytes, %s", len(data), metadata)
        if self.src:
            buf = gst.Buffer(data)
            #buf.size = size
            #buf.timestamp = timestamp
            #buf.duration = duration
            #buf.offset = offset
            #buf.offset_end = offset_end
            #buf.set_caps(gst.caps_from_string(caps))
            r = self.src.emit("push-buffer", buf)
            if r!=gst.FLOW_OK:
                log.error("push-buffer error: %s", r)
                self.emit('error', "push-buffer error: %s" % r)

    def need_data(self, src_arg, needed):
        debug("need_data: %s bytes in %s", needed, src_arg)

    def on_enough_data(self, *args):
        debug("on_enough_data(%s)", args)


gobject.type_register(SoundSink)


def main():
    import os.path
    if len(sys.argv) not in (2, 3):
        print("usage: %s filename [codec]" % sys.argv[0])
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
        codec = None
        parts = filename.split(".")
        if len(parts)>1:
            extension = parts[-1]
            if extension.lower() in CODECS:
                codec = extension.lower()
                print("guessed codec %s from file extension %s" % (codec, extension))
        if codec is None:
            print("assuming this is an mp3 file...")
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
        gobject.idle_add(gobject_mainloop.quit)
    ss.connect("eos", eos)
    ss.start()

    gobject_mainloop = gobject.MainLoop()
    gobject.threads_init()

    import signal
    def deadly_signal(*args):
        gobject.idle_add(gobject_mainloop.quit)
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    def check_for_end(*args):
        if not ss.pipeline:
            log.info("pipeline closed")
            gobject_mainloop.quit()
        return True
    gobject.timeout_add(1000, check_for_end)

    gobject_mainloop.run()


if __name__ == "__main__":
    main()
