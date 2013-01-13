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
from xpra.sound.gstreamer_util import plugin_str, get_encoders, MP3, CODECS
from wimpiggy.util import n_arg_signal
from wimpiggy.log import Logger
log = Logger()


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


DEFAULT_SRC = os.environ.get("XPRA_SOUND_DEFAULT_SRC", SOURCES[0])
if DEFAULT_SRC not in SOURCES:
    log.error("invalid default sound source: '%s' is not in %s, using %s instead", DEFAULT_SRC, SOURCES, SOURCES[0])
    DEFAULT_SRC = SOURCES[0]


class SoundSource(SoundPipeline):

    __gsignals__ = {
        "new-buffer": n_arg_signal(2),
        }

    def __init__(self, src_type=DEFAULT_SRC, src_options={}, codec=MP3, encoder_options={}):
        assert src_type in SOURCES
        encoders = get_encoders(codec)
        assert len(encoders)>0, "no encoders found for %s" % codec
        SoundPipeline.__init__(self, codec)
        self.src_type = src_type
        source_str = plugin_str(src_type, src_options)
        encoder = encoders[0]
        encoder_str = plugin_str(encoder, encoder_options)
        pipeline_els = [source_str]
        pipeline_els += ["audioconvert",
                         "audioresample",
                        encoder_str,
                        "appsink name=sink"]
        self.setup_pipeline_and_bus(pipeline_els)
        self.sink = self.pipeline.get_by_name("sink")
        self.sink.set_property("emit-signals", True)
        self.sink.set_property("max-buffers", 10)
        self.sink.set_property("drop", False)
        self.sink.set_property("sync", True)
        self.sink.set_property("qos", False)
        self.sink.connect("new-buffer", self.on_new_buffer)
        self.sink.connect("new-preroll", self.on_new_preroll)

    def cleanup(self):
        SoundPipeline.cleanup(self)
        self.src_type = ""
        self.sink = None

    def on_new_preroll(self, appsink):
        buf = appsink.emit('pull-preroll')
        debug('new preroll: %s bytes', len(buf))
        self.emit_buffer(buf)

    def on_new_buffer(self, bus):
        buf = self.sink.emit("pull-buffer")
        self.emit_buffer(buf)

    def emit_buffer(self, buf):
        """ convert pygst structure into something more generic for the wire """
        #none of the metadata is really needed at present, but it may be in the future:
        #metadata = {"caps"      : buf.get_caps().to_string(),
        #            "size"      : buf.size,
        #            "timestamp" : buf.timestamp,
        #            "duration"  : buf.duration,
        #            "offset"    : buf.offset,
        #            "offset_end": buf.offset_end}
        metadata = {}
        self.emit("new-buffer", buf.data, metadata)

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

    from threading import Lock
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
    lock = Lock()
    def new_buffer(ss, data):
        try:
            lock.acquire()
            if f:
                f.write(data)
        finally:
            lock.release()
    ss.connect("new-buffer", new_buffer)
    ss.start()

    import signal
    def deadly_signal(*args):
        gobject.idle_add(gtk.main_quit)
    signal.signal(signal.SIGINT, deadly_signal)
    signal.signal(signal.SIGTERM, deadly_signal)

    import gtk
    gtk.main()

    f.flush()
    log.info("wrote %s bytes to %s", f.tell(), filename)
    try:
        lock.acquire()
        f.close()
        f = None
    finally:
        lock.release()


if __name__ == "__main__":
    main()
