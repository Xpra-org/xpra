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
        }

    def __init__(self, src_type="autoaudiosrc", src_options={}, codec=MP3, encoder_options={}):
        assert src_type in SOURCES
        bitrate = encoder_options.get("bitrate", DEFAULT_BITRATE)
        assert bitrate in BITRATES, "invalid bitrate %s" % bitrate
        encoders = get_encoders(codec)
        assert len(encoders)>0, "no encoders found for %s" % codec
        super(gobject.GObject, self).__init__()
        super(AutoPropGObjectMixin, self).__init__()
        self.codec = codec
        self.data = ""
        self.src_type = src_type
        source_str = plugin_str(src_type, src_options)
        encoder = encoders[0]
        encoder_str = plugin_str(encoder, encoder_options)
        pipeline_els = [source_str,
                        "volume name=volume",
                        "audioconvert",
                        encoder_str,
                        "appsink name=sink"]
        pipeline_str = " ! ".join(pipeline_els)
        log("soundsource pipeline=%s", pipeline_str)
        self.pipeline = gst.parse_launch(pipeline_str)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)
        self.sink = self.pipeline.get_by_name("sink")
        log("sink %s", self.sink)
        self.volume = self.pipeline.get_by_name("volume")
        self.sink.set_property("emit-signals", True)
        self.sink.set_property("drop", False)
        self.sink.set_property("sync", False)
        self.sink.connect("new-buffer", self.on_new_buffer)
        self.sink.connect("new-preroll", self.on_new_preroll)
        #self.sink.set_property("max-buffers", 1)

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

    def set_volume(self, volume):
        assert volume>=0 and volume<=10
        self.volume.set_property("volume", volume)

    def on_new_preroll(self, appsink):
        buf = appsink.emit('pull-preroll')
        log.info('new preroll: %s bytes', len(buf))
        self.emit("new-buffer", str(buf))
        return True

    def on_new_buffer_list(self, appsink):
        buf = appsink.emit('pull-buffer-list')
        log.info('new buffer list', len(buf))
        return True

    def on_new_buffer(self, bus, *args):
        buf = self.sink.emit("pull-buffer")
        log("new-buffer: %s bytes", len(buf))
        self.emit("new-buffer", str(buf))
        return True

    def on_message(self, bus, message):
        log("on_message(%s, %s)", bus, message)
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.pipeline.set_state(gst.STATE_NULL)
        elif t == gst.MESSAGE_ERROR:
            self.pipeline.set_state(gst.STATE_NULL)
            err, debug = message.parse_error()
            log.error("Pipeline error: %s / %s", err, debug)

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
    log("found pulseaudio monitor devices: %s", monitor_devices)
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
