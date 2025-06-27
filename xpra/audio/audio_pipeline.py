# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# must be done before importing gobject!
# pylint: disable=wrong-import-position

import os
from typing import Any

from xpra.os_util import gi_import
from xpra.util.objects import AtomicInteger
from xpra.util.system import register_SIGUSR_signals
from xpra.gstreamer.common import import_gst, GST_FLOW_OK
from xpra.gstreamer.pipeline import Pipeline
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("audio")
gstlog = Logger("gstreamer")

SAVE_AUDIO = os.environ.get("XPRA_SAVE_AUDIO", "")

KNOWN_TAGS = {"bitrate", "codec", "audio-codec", "mode", "container-format", "encoder", "description", "language-code",
              "minimum-bitrate", "maximum-bitrate", "channel-mode"}


class AudioPipeline(Pipeline):
    generation = AtomicInteger()
    __generic_signals__ = Pipeline.__generic_signals__.copy()

    def __init__(self, codec: str):
        super().__init__()
        self.stream_compressor = None
        self.codec = codec
        self.codec_description = ""
        self.codec_mode = ""
        self.container_format = ""
        self.container_description = ""
        self.bitrate = -1
        self.start_time = 0
        self.buffer_count = 0
        self.byte_count = 0
        self.emit_info_timer = 0
        self.volume = None
        self.info: dict[str, Any] = {
            "codec": self.codec,
            "state": self.state,
        }

    def init_file(self, codec: str) -> None:
        gen = self.generation.increase()
        log("init_file(%s) generation=%s, SAVE_AUDIO=%s", codec, gen, SAVE_AUDIO)
        if SAVE_AUDIO:
            parts = codec.split("+")
            if len(parts) > 1:
                filename = SAVE_AUDIO + str(gen) + "-" + parts[0] + ".%s" % parts[1]
            else:
                filename = SAVE_AUDIO + str(gen) + ".%s" % codec
            self.file = open(filename, 'wb')
            log.info(f"saving {codec} stream to {filename!r}")

    def update_bitrate(self, new_bitrate: int) -> None:
        if new_bitrate == self.bitrate:
            return
        self.bitrate = new_bitrate
        log("new bitrate: %s", self.bitrate)
        self.info["bitrate"] = new_bitrate

    def inc_buffer_count(self, inc: int = 1) -> None:
        self.buffer_count += inc
        self.info["buffer_count"] = self.buffer_count

    def inc_byte_count(self, count: int) -> None:
        self.byte_count += count
        self.info["bytes"] = self.byte_count

    def set_volume(self, volume: int = 100) -> None:
        if self.volume:
            self.volume.set_property("volume", volume / 100.0)
            self.info["volume"] = volume

    def get_volume(self) -> int:
        if self.volume:
            return int(self.volume.get_property("volume") * 100)
        return GST_FLOW_OK

    def start(self) -> bool:
        if not super().start():
            return False
        register_SIGUSR_signals(GLib.idle_add)
        log("AudioPipeline.start() codec=%s", self.codec)
        self.idle_emit("new-stream", self.codec)
        self.update_state("active")
        gst = import_gst()
        self.pipeline.set_state(gst.State.PLAYING)
        if self.stream_compressor:
            self.info["stream-compressor"] = self.stream_compressor
        self.emit_info()
        # we may never get the stream start,
        # so we synthesize a codec event to get the log message in all cases:
        parts = self.codec.split("+")
        GLib.timeout_add(1000, self.new_codec_description, parts[0])
        if len(parts) > 1 and parts[1] != self.stream_compressor:
            GLib.timeout_add(1000, self.new_container_description, parts[1])
        elif self.container_format:
            GLib.timeout_add(1000, self.new_container_description, self.container_format)
        if self.stream_compressor:
            def logsc() -> bool:
                self.gstloginfo(f"using stream compression {self.stream_compressor}")
                return False

            GLib.timeout_add(1000, logsc)
        log("AudioPipeline.start() done")
        return True

    def stop(self) -> None:
        if self.pipeline and self.state not in ("starting", "stopped", "ready", None):
            log.info("stopping")
        super().stop()

    def cleanup(self) -> None:
        super().cleanup()
        self.codec = ""
        self.bitrate = -1
        self.volume = None

    def onstart(self) -> None:
        # we don't always get the "audio-codec" message…
        # so print the codec from here instead (and assume gstreamer is using what we told it to)
        # after a delay, just in case we do get the real "audio-codec" message!
        GLib.timeout_add(500, self.new_codec_description, self.codec.split("+")[0])

    def on_message(self, bus, message) -> int:
        try:
            return super().on_message(bus, message)
        finally:
            self.emit_info()

    def parse_message(self, message) -> None:
        # message parsing code for GStreamer 1.x
        taglist = message.parse_tag()
        tags = [taglist.nth_tag_name(x) for x in range(taglist.n_tags())]
        gstlog("bus message with tags=%s", tags)
        if not tags:
            # ignore it
            return
        if "bitrate" in tags:
            new_bitrate = taglist.get_uint("bitrate")
            if new_bitrate[0] is True:
                self.update_bitrate(new_bitrate[1])
                gstlog("bitrate: %s", new_bitrate[1])
        if "codec" in tags:
            desc = taglist.get_string("codec")
            if desc[0] is True:
                self.new_codec_description(desc[1])
        if "audio-codec" in tags:
            desc = taglist.get_string("audio-codec")
            if desc[0] is True:
                self.new_codec_description(desc[1])
                gstlog("audio-codec: %s", desc[1])
        if "mode" in tags:
            mode = taglist.get_string("mode")
            if mode[0] is True and self.codec_mode != mode[1]:
                gstlog("mode: %s", mode[1])
                self.codec_mode = mode[1]
                self.info["codec_mode"] = self.codec_mode
        if "container-format" in tags:
            cf = taglist.get_string("container-format")
            if cf[0] is True:
                self.new_container_description(cf[1])
        for x in ("encoder", "description", "language-code"):
            if x in tags:
                desc = taglist.get_string(x)
                gstlog("%s: %s", x, desc[1])
        if not set(tags).intersection(KNOWN_TAGS):
            structure = message.get_structure()
            self.gstloginfo("unknown audio pipeline tag message: %s, tags=%s", structure.to_string(), tags)

    def new_codec_description(self, desc) -> None:
        log("new_codec_description(%s) current codec description=%s", desc, self.codec_description)
        if not desc:
            return
        dl = desc.lower()
        if dl == "wav" and self.codec_description:
            return
        cdl = self.codec_description.lower()
        if not cdl or (cdl != dl and dl.find(cdl) < 0 and cdl.find(dl) < 0):
            self.gstloginfo("using '%s' audio codec", dl)
        self.codec_description = dl
        self.info["codec_description"] = dl

    def new_container_description(self, desc) -> None:
        log("new_container_description(%s) current container description=%s", desc, self.container_description)
        if not desc:
            return
        cdl = self.container_description.lower()
        dl = {
            "mka": "matroska",
            "mpeg4": "iso fmp4",
        }.get(desc.lower(), desc.lower())
        if not cdl or (cdl != dl and dl.find(cdl) < 0 and cdl.find(dl) < 0):
            self.gstloginfo("using '%s' container format", dl)
        self.container_description = dl
        self.info["container_description"] = dl
