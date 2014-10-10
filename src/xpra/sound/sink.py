#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os, time

from xpra.sound.sound_pipeline import SoundPipeline, gobject, one_arg_signal
from xpra.sound.pulseaudio_util import has_pa
from xpra.sound.gstreamer_util import plugin_str, get_decoder_parser, get_queue_time, MP3, CODECS, gst, QUEUE_LEAK, MS_TO_NS

from xpra.os_util import thread
from xpra.log import Logger
log = Logger("sound")


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

SINK_SHARED_DEFAULT_ATTRIBUTES = {"sync" : False,
                                  "async" : True}
SINK_DEFAULT_ATTRIBUTES = {
                           "pulsesink"  : {"client" : "Xpra"}
                           }

DEFAULT_SINK = os.environ.get("XPRA_SOUND_SINK", DEFAULT_SINK)
if DEFAULT_SINK not in SINKS:
    log.error("invalid default sound sink: '%s' is not in %s, using %s instead", DEFAULT_SINK, SINKS, SINKS[0])
    DEFAULT_SINK = SINKS[0]
QUEUE_SILENT = 0
QUEUE_TIME = get_queue_time(450)


def sink_has_device_attribute(sink):
    return sink not in ("autoaudiosink", "jackaudiosink", "directsoundsink")


class SoundSink(SoundPipeline):

    __gsignals__ = SoundPipeline.__generic_signals__.copy()
    __gsignals__.update({
        "underrun"  : one_arg_signal,
        "overrun"   : one_arg_signal,
        "eos"       : one_arg_signal,
        })

    def __init__(self, sink_type=DEFAULT_SINK, options={}, codec=MP3, decoder_options={}):
        assert sink_type in SINKS, "invalid sink: %s" % sink_type
        decoder, parser = get_decoder_parser(codec)
        SoundPipeline.__init__(self, codec)
        self.sink_type = sink_type
        decoder_str = plugin_str(decoder, decoder_options)
        pipeline_els = []
        pipeline_els.append("appsrc"+
                            " name=src"+
                            " max-bytes=32768"+
                            " emit-signals=0"+
                            " block=0"+
                            " is-live=0"+
                            " stream-type=stream"+
                            " format=4")
        pipeline_els.append(parser)
        pipeline_els.append(decoder_str)
        pipeline_els.append("audioconvert")
        pipeline_els.append("audioresample")
        queue_el =  ["queue",
                    "name=queue",
                    "max-size-buffers=0",
                    "max-size-bytes=0",
                    "max-size-time=%s" % QUEUE_TIME,
                    "leaky=%s" % QUEUE_LEAK]
        if QUEUE_SILENT:
            queue_el.append("silent=%s" % QUEUE_SILENT)
        pipeline_els.append(" ".join(queue_el))
        sink_attributes = SINK_SHARED_DEFAULT_ATTRIBUTES.copy()
        sink_attributes.update(SINK_DEFAULT_ATTRIBUTES.get(sink_type, {}))
        sink_str = plugin_str(sink_type, sink_attributes)
        pipeline_els.append(sink_str)
        self.setup_pipeline_and_bus(pipeline_els)
        self.src = self.pipeline.get_by_name("src")
        self.queue = self.pipeline.get_by_name("queue")
        self.overruns = 0
        self.queue_state = "starting"
        if QUEUE_SILENT==0:
            self.queue.connect("overrun", self.queue_overrun)
            self.queue.connect("underrun", self.queue_underrun)
            self.queue.connect("running", self.queue_running)
            self.queue.connect("pushing", self.queue_pushing)

    def __repr__(self):
        return "SoundSink('%s' - %s)" % (self.pipeline_str, self.state)

    def queue_pushing(self, *args):
        ltime = int(self.queue.get_property("current-level-time")/MS_TO_NS)
        log("sound sink queue pushing: level=%s", ltime)
        self.queue_state = "pushing"

    def queue_running(self, *args):
        ltime = int(self.queue.get_property("current-level-time")/MS_TO_NS)
        log("sound sink queue running: level=%s", ltime)
        self.queue_state = "running"

    def queue_underrun(self, *args):
        ltime = int(self.queue.get_property("current-level-time")/MS_TO_NS)
        log("sound sink queue underrun: level=%s", ltime)
        self.queue_state = "underrun"

    def queue_overrun(self, *args):
        ltime = int(self.queue.get_property("current-level-time")/MS_TO_NS)
        self.queue_state = "overrun"
        #no overruns for the first 2 seconds:
        elapsed = time.time()-self.start_time
        if elapsed<2.0 or ltime<(QUEUE_TIME/MS_TO_NS/2*75/100):
            log("sound sink queue overrun ignored: level=%s, elapsed time=%.1f", ltime, elapsed)
            return
        log("sound sink queue overrun: level=%s", ltime)
        self.overruns += 1
        self.emit("overrun", ltime)

    def cleanup(self):
        SoundPipeline.cleanup(self)
        self.sink_type = ""
        self.src = None

    def eos(self):
        log("eos()")
        if self.src:
            self.src.emit('end-of-stream')
        self.cleanup()

    def get_info(self):
        info = SoundPipeline.get_info(self)
        if QUEUE_TIME>0:
            clt = self.queue.get_property("current-level-time")
            info["queue.used_pct"] = int(min(QUEUE_TIME, clt)*100.0/QUEUE_TIME)
            info["queue.overruns"] = self.overruns
            info["queue.state"] = self.queue_state
        return info

    def add_data(self, data, metadata=None):
        #debug("sound sink: adding %s bytes to %s, metadata: %s, level=%s", len(data), self.src, metadata, int(self.queue.get_property("current-level-time")/MS_TO_NS))
        if not self.src:
            return
        buf = gst.new_buffer(data)
        d = 10*MS_TO_NS
        if metadata:
            ts = metadata.get("timestamp")
            if ts is not None:
                buf.timestamp = ts
            d = metadata.get("duration")
            if d is not None:
                buf.duration = d
        log("add_data(..) queue_state=%s", self.queue_state)
        if self.push_buffer(buf):
            self.buffer_count += 1
            self.byte_count += len(data)
            ltime = int(self.queue.get_property("current-level-time")/MS_TO_NS)
            log("sound sink: pushed %s bytes, new buffer level: %sms", len(data), ltime)

    def push_buffer(self, buf):
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
            return False
        return True

gobject.type_register(SoundSink)


def main():
    from xpra.platform import init, clean
    init("Sound-Record")
    try:
        args = sys.argv
        log.enable_debug()
        import os.path
        if len(args) not in (2, 3):
            print("usage: %s [-v|--verbose] filename [codec]" % sys.argv[0])
            return 1
        filename = args[1]
        if not os.path.exists(filename):
            print("file %s does not exist" % filename)
            return 2
        if len(args)==3:
            codec = args[2]
            if codec not in CODECS:
                print("invalid codec: %s" % codec)
                return 2
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

        log.enable_debug()
        with open(filename, "rb") as f:
            data = f.read()
        print("loaded %s bytes from %s" % (len(data), filename))
        #force no leak since we push all the data at once
        global QUEUE_LEAK, GST_QUEUE_NO_LEAK, QUEUE_SILENT
        QUEUE_LEAK = GST_QUEUE_NO_LEAK
        QUEUE_SILENT = 1
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
            qtime = int(ss.queue.get_property("current-level-time")/MS_TO_NS)
            if qtime<=0:
                log.info("underrun (end of stream)")
                thread.start_new_thread(ss.stop, ())
                gobject.timeout_add(500, gobject_mainloop.quit)
                return False
            return True
        gobject.timeout_add(1000, check_for_end)

        gobject_mainloop.run()
        return 0
    finally:
        clean()


if __name__ == "__main__":
    sys.exit(main())
