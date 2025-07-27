#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from time import monotonic
from collections.abc import Sequence
from typing import Any, NoReturn

from xpra.os_util import gi_import
from xpra.util.system import SIGNAMES
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool, envfloat
from xpra.audio.audio_pipeline import AudioPipeline
from xpra.util.gobject import n_arg_signal
from xpra.gstreamer.common import normv, has_plugins, plugin_str, GST_FLOW_OK, \
    get_default_appsink_attributes, get_element_str
from xpra.audio.gstreamer_util import (
    get_source_plugins, get_encoder_elements,
    get_encoder_default_options,
    get_encoders, get_queue_time,
    MP3, CODEC_ORDER, MUXER_DEFAULT_OPTIONS,
    MS_TO_NS, GST_QUEUE_LEAK_DOWNSTREAM,
)
from xpra.net.compression import compressed_wrapper
from xpra.scripts.config import InitExit
from xpra.log import Logger

GLib = gi_import("GLib")
GObject = gi_import("GObject")

log = Logger("audio")
gstlog = Logger("gstreamer")

JITTER = envint("XPRA_SOUND_SOURCE_JITTER", 0)
SOURCE_QUEUE_TIME = get_queue_time(50, "SOURCE_")

BUFFER_TIME = envint("XPRA_SOUND_SOURCE_BUFFER_TIME", 0)  # ie: 64
LATENCY_TIME = envint("XPRA_SOUND_SOURCE_LATENCY_TIME", 0)  # ie: 32
BUNDLE_METADATA = envbool("XPRA_SOUND_BUNDLE_METADATA", True)
LOG_CUTTER = envbool("XPRA_SOUND_LOG_CUTTER", False)
CUTTER_THRESHOLD = envfloat("XPRA_CUTTER_THRESHOLD", 0.0001)
CUTTER_PRE_LENGTH = envint("XPRA_CUTTER_PRE_LENGTH", 100)
CUTTER_RUN_LENGTH = envint("XPRA_CUTTER_RUN_LENGTH", 1000)


class AudioSource(AudioPipeline):
    __gsignals__ = AudioPipeline.__generic_signals__.copy()
    __gsignals__ |= {
        "new-buffer": n_arg_signal(3),
    }

    def __init__(self, src_type: str, src_options: dict[str, int | float | str],
                 codecs: Sequence[str], codec_options: dict, volume=1.0):
        if not src_type:
            try:
                from xpra.audio.pulseaudio.util import get_pa_device_options
                monitor_devices = get_pa_device_options(True, False)
                log.info("found pulseaudio monitor devices: %s", monitor_devices)
            except ImportError as e:
                log.warn("Warning: pulseaudio is not available!")
                log.warn(" %s", e)
                monitor_devices = []
            if not monitor_devices:
                log.warn("could not detect any pulseaudio monitor devices")
                log.warn(" a test source will be used instead")
                src_type = "audiotestsrc"
                default_src_options = {"wave": 2, "freq": 100, "volume": 0.4}
            else:
                monitor_device = monitor_devices.items()[0][0]
                log.info("using pulseaudio source device:")
                log.info(" '%s'", monitor_device)
                src_type = "pulsesrc"
                default_src_options = {"device": monitor_device}
            src_options = default_src_options
        if src_type not in get_source_plugins():
            raise InitExit(1, "invalid source plugin '%s', valid options are: %s" % (src_type,
                                                                                     ",".join(get_source_plugins())))
        matching = [x for x in CODEC_ORDER if (x in codecs and x in get_encoders())]
        log("AudioSource(..) found matching codecs %s", matching)
        if not matching:
            raise InitExit(1, "no matching codecs between arguments '%s' and supported list '%s'" % (
                csv(codecs), csv(get_encoders().keys())))
        codec = matching[0]
        encoder, fmt, stream_compressor = get_encoder_elements(codec)
        super().__init__(codec)
        self.queue = None
        self.caps = None
        self.volume = None
        self.sink = None
        self.src = None
        self.src_type = src_type
        self.timestamp = None
        self.min_timestamp = 0
        self.max_timestamp = 0
        self.pending_metadata = []
        self.buffer_latency = True
        self.jitter_queue = None
        self.container_format = (fmt or "").replace("mux", "").replace("pay", "")
        self.stream_compressor = stream_compressor
        src_options["name"] = "src"
        source_str = plugin_str(src_type, src_options)
        # FIXME: this is ugly and relies on the fact that we don't pass any codec options to work!
        pipeline_els = [source_str]
        log("has plugin(timestamp)=%s", has_plugins("timestamp"))
        if has_plugins("timestamp"):
            pipeline_els.append("timestamp name=timestamp")
        if SOURCE_QUEUE_TIME > 0:
            pipeline_els.append(get_element_str("queue", {
                "name": "queue",
                "min-threshold-time": 0,
                "max-size-buffers": 0,
                "max-size-bytes": 0,
                "max-size-time": SOURCE_QUEUE_TIME * MS_TO_NS,
                "leaky": GST_QUEUE_LEAK_DOWNSTREAM,
            }))
        # if encoder in ENCODER_NEEDS_AUDIOCONVERT or src_type in SOURCE_NEEDS_AUDIOCONVERT:
        pipeline_els += ["audioconvert"]
        if has_plugins("removesilence"):
            pipeline_els += [
                "removesilence",
                "audioconvert",
                "audioresample"
            ]
        pipeline_els.append(get_element_str("volume", {"name": "volume", "volume": volume}))
        if encoder:
            encoder_str = plugin_str(encoder, codec_options or get_encoder_default_options(encoder))
            pipeline_els.append(encoder_str)
        if fmt:
            fmt_str = plugin_str(fmt, MUXER_DEFAULT_OPTIONS.get(fmt, {}))
            pipeline_els.append(fmt_str)
        pipeline_els.append(get_element_str("appsink", get_default_appsink_attributes()))
        if not self.setup_pipeline_and_bus(pipeline_els):
            return
        self.timestamp = self.pipeline.get_by_name("timestamp")
        self.volume = self.pipeline.get_by_name("volume")
        self.sink = self.pipeline.get_by_name("sink")
        if SOURCE_QUEUE_TIME > 0:
            self.queue = self.pipeline.get_by_name("queue")
        if self.queue:
            try:
                self.queue.set_property("silent", True)
            except Exception as e:
                log("cannot make queue silent: %s", e)
        self.sink.set_property("enable-last-sample", False)
        self.skipped_caps = set()
        if JITTER > 0:
            from queue import SimpleQueue
            self.jitter_queue = SimpleQueue()
        self.sink.connect("new-sample", self.on_new_sample)
        self.sink.connect("new-preroll", self.on_new_preroll)
        self.src = self.pipeline.get_by_name("src")
        for x in ("actual-buffer-time", "actual-latency-time"):
            try:
                gstlog("initial %s: %s", x, self.src.get_property(x))
            except Exception as e:
                gstlog("no %s property on %s: %s", x, self.src, e)
                self.buffer_latency = False
        # if the env vars have been set, try to honour the settings:
        global BUFFER_TIME, LATENCY_TIME
        if BUFFER_TIME > 0:
            if BUFFER_TIME < LATENCY_TIME:
                log.warn("Warning: latency (%ims) must be lower than the buffer time (%ims)", LATENCY_TIME, BUFFER_TIME)
            else:
                log("latency tuning for %s, will try to set buffer-time=%i, latency-time=%i",
                    src_type, BUFFER_TIME, LATENCY_TIME)
                self.set_time("buffer-time", BUFFER_TIME)
                self.set_time("latency-time", LATENCY_TIME)
        self.init_file(codec)

    def set_time(self, attr, v) -> None:
        try:
            cval = self.src.get_property(attr)
            gstlog("default: %s=%i", attr, cval // 1000)
            if v >= 0:
                self.src.set_property(attr, v * 1000)
                gstlog("overriding with: %s=%i", attr, v)
        except Exception as e:
            log.warn("source %s does not support '%s': %s", self.src_type, attr, e)

    def __repr__(self):  # pylint: disable=arguments-differ
        return "AudioSource('%s' - %s)" % (self.pipeline_str, self.state)

    def cleanup(self) -> None:
        super().cleanup()
        self.src_type = ""
        self.sink = None
        self.caps = None

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        if self.queue:
            info["queue"] = {"cur": self.queue.get_property("current-level-time") // MS_TO_NS}
        if CUTTER_THRESHOLD > 0 and (self.min_timestamp or self.max_timestamp):
            info["cutter.min-timestamp"] = self.min_timestamp
            info["cutter.max-timestamp"] = self.max_timestamp
        if self.buffer_latency:
            for x in ("actual-buffer-time", "actual-latency-time"):
                v = self.src.get_property(x)
                if v >= 0:
                    info[x] = v
        if self.src_type != "autoaudiosrc":
            info["src"] = self.get_element_properties(
                self.src,
                "actual-buffer-time", "actual-latency-time",
                "buffer-time", "latency-time",
                "provide-clock",
            )
            info["src"]["type"] = self.src_type
        return info

    def do_parse_element_message(self, _message, name, props=None) -> None:
        if name == "cutter" and props:
            above = props.get("above")
            ts = props.get("timestamp", 0)
            if above is False:
                self.max_timestamp = ts
                self.min_timestamp = 0
            elif above is True:
                self.max_timestamp = 0
                self.min_timestamp = ts
            log_fn = gstlog.info if LOG_CUTTER else gstlog.debug
            log_fn("cutter message, above=%s, min-timestamp=%s, max-timestamp=%s",
                   above, self.min_timestamp, self.max_timestamp)

    @staticmethod
    def on_new_preroll(_appsink) -> int:
        gstlog('new preroll')
        return GST_FLOW_OK

    def on_new_sample(self, _bus) -> int:
        sample = self.sink.emit("pull-sample")
        buf = sample.get_buffer()
        pts = normv(buf.pts)
        if self.min_timestamp > 0 and pts < self.min_timestamp:
            gstlog("cutter: skipping buffer with pts=%s (min-timestamp=%s)", pts, self.min_timestamp)
            return GST_FLOW_OK
        if self.max_timestamp and pts > self.max_timestamp:
            gstlog("cutter: skipping buffer with pts=%s (max-timestamp=%s)", pts, self.max_timestamp)
            return GST_FLOW_OK
        size = buf.get_size()
        data = buf.extract_dup(0, size)
        duration = normv(buf.duration)
        metadata = {
            "timestamp": pts,
            "duration": duration,
        }
        if self.timestamp:
            delta = self.timestamp.get_property("delta")
            ts = (pts + delta) // 1000000  # ns to ms
            now = monotonic()
            latency = int(1000 * now) - ts
            # log.info("emit_buffer: delta=%i, pts=%i, ts=%s, time=%s, latency=%ims",
            #    delta, pts, ts, now, (latency//1000000))
            ts_info = {
                "ts": ts,
                "latency": latency,
            }
            metadata.update(ts_info)
            self.info.update(ts_info)
        if pts == -1 and duration == -1 and BUNDLE_METADATA and len(self.pending_metadata) < 10:
            self.pending_metadata.append(data)
            return GST_FLOW_OK
        return self._emit_buffer(data, metadata)

    def _emit_buffer(self, data: bytes, metadata: dict) -> int:
        if self.stream_compressor and data:
            cdata = compressed_wrapper("audio", data, level=9, can_inline=True,
                                       lz4=self.stream_compressor == "lz4")
            if len(cdata) < len(data) * 90 // 100:
                log("compressed using %s from %i bytes down to %i bytes", self.stream_compressor, len(data), len(cdata))
                metadata["compress"] = self.stream_compressor
                data = cdata
            else:
                log("skipped inefficient %s stream compression: %i bytes down to %i bytes",
                    self.stream_compressor, len(data), len(cdata))
        if self.state == "stopped":
            # don't bother
            return GST_FLOW_OK
        if JITTER > 0:
            # will actually emit the buffer after a random delay
            if self.jitter_queue.empty():
                # queue was empty, schedule a timer to flush it
                from random import randint
                jitter = randint(1, JITTER)
                GLib.timeout_add(jitter, self.flush_jitter_queue)
                log("emit_buffer: will flush jitter queue in %ims", jitter)
            for x in self.pending_metadata:
                self.jitter_queue.put((x, {}))
            self.pending_metadata = []
            self.jitter_queue.put((data, metadata))
            return GST_FLOW_OK
        log("emit_buffer data=%s, len=%i, metadata=%s", type(data), len(data), metadata)
        return self.do_emit_buffer(data, metadata)

    def flush_jitter_queue(self) -> None:
        while not self.jitter_queue.empty():
            d, m = self.jitter_queue.get(False)
            self.do_emit_buffer(d, m)

    def do_emit_buffer(self, data: bytes, metadata: dict) -> int:
        self.inc_buffer_count()
        self.inc_byte_count(len(data))
        for x in self.pending_metadata:
            self.inc_buffer_count()
            self.inc_byte_count(len(x))
        metadata["time"] = int(monotonic() * 1000)
        self.save_to_file(*(self.pending_metadata + [data]))
        self.idle_emit("new-buffer", data, metadata, self.pending_metadata)
        self.pending_metadata = []
        self.emit_info()
        return GST_FLOW_OK


GObject.type_register(AudioSource)


def main() -> int:
    from xpra.platform import program_context
    with program_context("Xpra-Audio-Source"):
        if "-v" in sys.argv:
            log.enable_debug()
            sys.argv.remove("-v")

        if len(sys.argv) not in (2, 3):
            log.error("usage: %s filename [codec] [--encoder=rencode]", sys.argv[0])
            return 1
        filename = sys.argv[1]
        if filename == "-":
            from xpra.util.io import disable_stdout_buffering
            disable_stdout_buffering()
        elif os.path.exists(filename):
            log.error("file %s already exists", filename)
            return 1
        codec = None

        encoders = get_encoders()
        if len(sys.argv) == 3:
            codec = sys.argv[2]
            if codec not in encoders:
                log.error("invalid codec: %s, codecs supported: %s", codec, encoders)
                return 1
        else:
            parts = filename.split(".")
            if len(parts) > 1:
                extension = parts[-1]
                if extension.lower() in encoders:
                    codec = extension.lower()
                    log.info("guessed codec %s from file extension %s", codec, extension)
            if codec is None:
                codec = MP3
                log.info("using default codec: %s", codec)

        # in case we're running against pulseaudio,
        # try to set up the env:
        try:
            from xpra.platform.paths import get_icon_filename
            f = get_icon_filename("xpra.png")
            from xpra.audio.pulseaudio.util import add_audio_tagging_env
            add_audio_tagging_env(icon_path=f)
        except Exception as e:
            log.warn("failed to setup pulseaudio tagging: %s", e)

        from threading import Lock
        if filename == "-":
            output = sys.stdout
        else:
            output = open(filename, "wb")

        ss = AudioSource("", src_options={}, codecs=[codec], codec_options={})
        lock = Lock()

        def new_buffer(_audiosource, data, metadata, packet_metadata) -> None:
            log.info("new buffer: %s bytes (%s), metadata=%s", len(data), type(data), metadata)
            with lock:
                for x in packet_metadata:
                    output.write(x)
                output.write(data)
                output.flush()

        glib_mainloop = GLib.MainLoop()

        ss.connect("new-buffer", new_buffer)
        ss.start()

        import signal

        def deadly_signal(sig, _frame) -> None:
            log.warn("got deadly signal %s", SIGNAMES.get(sig, sig))
            GLib.idle_add(ss.stop)
            GLib.idle_add(glib_mainloop.quit)

            def force_quit(_sig, _frame) -> NoReturn:
                sys.exit()

            signal.signal(signal.SIGINT, force_quit)
            signal.signal(signal.SIGTERM, force_quit)

        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)

        try:
            glib_mainloop.run()
        except Exception as e:
            log.error("main loop error: %s", e)
        ss.stop()

        output.flush()
        if output != sys.stdout:
            log.info("wrote %s bytes to %s", output.tell(), filename)
        with lock:
            output.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
