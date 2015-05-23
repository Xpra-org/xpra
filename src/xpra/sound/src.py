#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import time

from xpra.os_util import SIGNAMES
from xpra.sound.sound_pipeline import SoundPipeline, gobject
from xpra.gtk_common.gobject_util import n_arg_signal
from xpra.sound.gstreamer_util import plugin_str, get_encoder_formatter, get_source_plugins, get_queue_time, normv, \
                                MP3, CODECS, CODEC_ORDER, QUEUE_LEAK, ENCODER_DEFAULT_OPTIONS, ENCODER_NEEDS_AUDIOCONVERT
from xpra.log import Logger
log = Logger("sound")


AUDIORESAMPLE = False
QUEUE_TIME = get_queue_time(0)


class SoundSource(SoundPipeline):

    __gsignals__ = SoundPipeline.__generic_signals__.copy()
    __gsignals__.update({
        "new-buffer"    : n_arg_signal(2),
        })

    def __init__(self, src_type=None, src_options={}, codecs=CODECS, codec_options={}, volume=1.0):
        if not src_type:
            from xpra.sound.pulseaudio_util import get_pa_device_options
            monitor_devices = get_pa_device_options(True, False)
            log.info("found pulseaudio monitor devices: %s", monitor_devices)
            if len(monitor_devices)==0:
                log.warn("could not detect any pulseaudio monitor devices - will use a test source")
                src_type = "audiotestsrc"
                default_src_options = {"wave":2, "freq":100, "volume":0.4}
            else:
                monitor_device = monitor_devices.items()[0][0]
                log.info("using pulseaudio source device: %s", monitor_device)
                src_type = "pulsesrc"
                default_src_options = {"device" : monitor_device}
            src_options = default_src_options
            src_options.update(src_options)
        assert src_type in get_source_plugins(), "invalid source plugin '%s', valid options are: %s" % (src_type, ",".join(get_source_plugins()))
        matching = [x for x in CODEC_ORDER if (x in codecs and x in CODECS)]
        log("SoundSource(..) found matching codecs %s", matching)
        assert len(matching)>0, "no matching codecs between arguments %s and supported list %s" % (codecs, CODECS)
        codec = matching[0]
        encoder, fmt = get_encoder_formatter(codec)
        SoundPipeline.__init__(self, codec)
        self.src_type = src_type
        source_str = plugin_str(src_type, src_options)
        #FIXME: this is ugly and relies on the fact that we don't pass any codec options to work!
        encoder_str = plugin_str(encoder, codec_options or ENCODER_DEFAULT_OPTIONS.get(encoder, {}))
        pipeline_els = [source_str]
        if encoder in ENCODER_NEEDS_AUDIOCONVERT:
            pipeline_els += ["audioconvert"]
        if AUDIORESAMPLE:
            pipeline_els += [
                         "audioresample",
                         "audio/x-raw-int,rate=44100,channels=2"]
        pipeline_els.append("volume name=volume volume=%s" % volume)
        if QUEUE_TIME>0:
            queue_el =  ["queue",
                         "name=queue",
                         "max-size-buffers=0",
                         "max-size-bytes=0",
                         "max-size-time=%s" % QUEUE_TIME,
                         "leaky=%s" % QUEUE_LEAK]
            pipeline_els.append(" ".join(queue_el))
        pipeline_els += [encoder_str,
                        fmt,
                        "appsink name=sink"]
        self.setup_pipeline_and_bus(pipeline_els)
        self.volume = self.pipeline.get_by_name("volume")
        self.sink = self.pipeline.get_by_name("sink")
        self.sink.set_property("emit-signals", True)
        self.sink.set_property("max-buffers", 10)       #0?
        self.sink.set_property("drop", False)
        self.sink.set_property("sync", True)            #False?
        self.sink.set_property("qos", False)
        try:
            #Gst 1.0:
            self.sink.connect("new-sample", self.on_new_sample)
            self.sink.connect("new-preroll", self.on_new_preroll1)
        except:
            #Gst 0.10:
            self.sink.connect("new-buffer", self.on_new_buffer)
            self.sink.connect("new-preroll", self.on_new_preroll0)

    def __repr__(self):
        return "SoundSource('%s' - %s)" % (self.pipeline_str, self.state)

    def cleanup(self):
        SoundPipeline.cleanup(self)
        self.src_type = ""
        self.sink = None


    def on_new_preroll1(self, appsink):
        sample = appsink.emit('pull-preroll')
        log('new preroll1: %s', sample)
        return self.emit_buffer1(sample)

    def on_new_sample(self, bus):
        #Gst 1.0
        sample = self.sink.emit("pull-sample")
        return self.emit_buffer1(sample)

    def emit_buffer1(self, sample):
        buf = sample.get_buffer()
        #info = sample.get_info()
        size = buf.get_size()
        data = buf.extract_dup(0, size)
        return self.do_emit_buffer(data, {"timestamp"  : normv(buf.pts),
                                   "duration"   : normv(buf.duration),
                                   })


    def on_new_preroll0(self, appsink):
        buf = appsink.emit('pull-preroll')
        log('new preroll0: %s bytes', len(buf))
        return self.emit_buffer0(buf)

    def on_new_buffer(self, bus):
        #pygst 0.10
        buf = self.sink.emit("pull-buffer")
        return self.emit_buffer0(buf)


    def emit_buffer0(self, buf, metadata={}):
        """ convert pygst structure into something more generic for the wire """
        #none of the metadata is really needed at present, but it may be in the future:
        #metadata = {"caps"      : buf.get_caps().to_string(),
        #            "size"      : buf.size,
        #            "timestamp" : buf.timestamp,
        #            "duration"  : buf.duration,
        #            "offset"    : buf.offset,
        #            "offset_end": buf.offset_end}
        return self.do_emit_buffer(buf.data, {
                                       "caps"      : buf.get_caps().to_string(),
                                       "timestamp" : normv(buf.timestamp),
                                       "duration"  : normv(buf.duration)
                                       })


    def do_emit_buffer(self, data, metadata={}):
        self.buffer_count += 1
        self.byte_count += len(data)
        metadata["time"] = int(time.time()*1000)
        self.idle_emit("new-buffer", data, metadata)
        self.emit_info()
        return 0


gobject.type_register(SoundSource)


def main():
    import glib
    from xpra.platform import init, clean
    init("Xpra-Sound-Source")
    try:
        import os.path
        if "-v" in sys.argv:
            log.enable_debug()
            sys.argv.remove("-v")

        if len(sys.argv) not in (2, 3):
            log.error("usage: %s filename [codec] [--encoder=rencode]", sys.argv[0])
            return 1
        filename = sys.argv[1]
        if filename=="-":
            from xpra.os_util import disable_stdout_buffering
            disable_stdout_buffering()
        elif os.path.exists(filename):
            log.error("file %s already exists", filename)
            return 1
        codec = None

        if len(sys.argv)==3:
            codec = sys.argv[2]
            if codec not in CODECS:
                log.error("invalid codec: %s, codecs supported: %s", codec, CODECS)
                return 1
        else:
            parts = filename.split(".")
            if len(parts)>1:
                extension = parts[-1]
                if extension.lower() in CODECS:
                    codec = extension.lower()
                    log.info("guessed codec %s from file extension %s", codec, extension)
            if codec is None:
                codec = MP3
                log.info("using default codec: %s", codec)

        #in case we're running against pulseaudio,
        #try to setup the env:
        try:
            from xpra.platform.paths import get_icon_filename
            f = get_icon_filename("xpra.png")
            from xpra.sound.pulseaudio_util import add_audio_tagging_env
            add_audio_tagging_env(f)
        except Exception as e:
            log.warn("failed to setup pulseaudio tagging: %s", e)

        from threading import Lock
        if filename=="-":
            f = sys.stdout
        else:
            f = open(filename, "wb")
        ss = SoundSource(codecs=[codec])
        lock = Lock()
        def new_buffer(ss, data, metadata):
            log.info("new buffer: %s bytes (%s), metadata=%s", len(data), type(data), metadata)
            with lock:
                if f:
                    f.write(data)
                    f.flush()

        glib_mainloop = glib.MainLoop()

        ss.connect("new-buffer", new_buffer)
        ss.start()

        import signal
        def deadly_signal(sig, frame):
            log.warn("got deadly signal %s", SIGNAMES.get(sig, sig))
            glib.idle_add(ss.stop)
            glib.idle_add(glib_mainloop.quit)
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)

        try:
            glib_mainloop.run()
        except Exception as e:
            log.error("main loop error: %s", e)
        ss.stop()

        f.flush()
        if f!=sys.stdout:
            log.info("wrote %s bytes to %s", f.tell(), filename)
        with lock:
            f.close()
            f = None
        return 0
    finally:
        clean()


if __name__ == "__main__":
    sys.exit(main())
