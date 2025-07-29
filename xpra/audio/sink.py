#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from time import monotonic
from collections import deque
from collections.abc import Sequence
from threading import Lock
from typing import Any, Literal, NoReturn

from xpra.audio.audio_pipeline import AudioPipeline
from xpra.gstreamer.common import (
    normv, make_buffer, plugin_str,
    get_default_appsrc_attributes, get_element_str,
    GST_FLOW_OK,
)
from xpra.audio.gstreamer_util import (
    get_decoder_elements, has_plugins,
    get_queue_time, get_decoders,
    get_default_sink_plugin, get_sink_plugins,
    MP3, CODEC_ORDER, QUEUE_LEAK,
    GST_QUEUE_NO_LEAK, MS_TO_NS, DEFAULT_SINK_PLUGIN_OPTIONS,
)
from xpra.util.gobject import one_arg_signal
from xpra.net.compression import decompress_by_name
from xpra.scripts.config import InitExit
from xpra.common import SizedBuffer
from xpra.os_util import gi_import
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool
from xpra.util.thread import start_thread
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("audio")
gstlog = Logger("gstreamer")

GObject = gi_import("GObject")

SINK_SHARED_DEFAULT_ATTRIBUTES: dict[str, Any] = {
    "sync": False,
}
NON_AUTO_SINK_ATTRIBUTES: dict[str, Any] = {
    "async": True,
    "qos": True,
}

SINK_DEFAULT_ATTRIBUTES: dict[str, dict[str, str]] = {
    "pulsesink": {"client-name": "Xpra"},
}

QUEUE_SILENT = envbool("XPRA_QUEUE_SILENT", False)
QUEUE_TIME = get_queue_time(450)

UNMUTE_DELAY = envint("XPRA_UNMUTE_DELAY", 1000)
GRACE_PERIOD = envint("XPRA_SOUND_GRACE_PERIOD", 2000)
# percentage: from 0 for no margin, to 200% which triples the buffer target
MARGIN = max(0, min(200, envint("XPRA_SOUND_MARGIN", 50)))
# how high we push up the min-level to prevent underruns:
UNDERRUN_MIN_LEVEL = max(0, envint("XPRA_SOUND_UNDERRUN_MIN_LEVEL", 150))
CLOCK_SYNC = envbool("XPRA_CLOCK_SYNC", False)


def uncompress_data(data: bytes, metadata: dict) -> SizedBuffer:
    if not data or not metadata:
        return data
    compress = metadata.get("compress")
    if not compress:
        return data
    if compress != "lz4":
        raise ValueError(f"unsupported compresssion {compress!r}")
    v = decompress_by_name(data, compress)
    # log("decompressed %s data: %i bytes into %i bytes", compress, len(data), len(v))
    return v


class AudioSink(AudioPipeline):
    __gsignals__ = AudioPipeline.__generic_signals__.copy()
    __gsignals__ |= {
        "eos": one_arg_signal,
    }

    def __init__(self, sink_type: str, sink_options: dict, codecs: Sequence[str], codec_options: dict, volume=1.0):
        if not sink_type:
            sink_type = get_default_sink_plugin()
        if sink_type not in get_sink_plugins():
            raise InitExit(1, "invalid sink: %s" % sink_type)
        matching = [x for x in CODEC_ORDER if (x in codecs and x in get_decoders())]
        log("AudioSink(..) found matching codecs %s", matching)
        if not matching:
            raise InitExit(1, "no matching codecs between arguments '%s' and supported list '%s'" % (
                csv(codecs), csv(get_decoders().keys())))
        codec = matching[0]
        decoder, parser, stream_compressor = get_decoder_elements(codec)
        super().__init__(codec)
        self.container_format = (parser or "").replace("demux", "").replace("depay", "")
        self.sink_type = sink_type
        self.stream_compressor = stream_compressor
        log("container format=%s, stream_compressor=%s, sink type=%s",
            self.container_format, self.stream_compressor, self.sink_type)
        self.levels = deque(maxlen=100)
        self.volume = None
        self.src = None
        self.sink = None
        self.queue = None
        self.normal_volume = volume
        self.target_volume = volume
        self.volume_timer = 0
        self.overruns = 0
        self.underruns = 0
        self.overrun_events = deque(maxlen=100)
        self.queue_state = "starting"
        self.last_data = None
        self.last_underrun = 0
        self.last_overrun = 0
        self.refill = True
        self.last_max_update = monotonic()
        self.last_min_update = monotonic()
        self.level_lock = Lock()
        pipeline_els = [get_element_str("appsrc", get_default_appsrc_attributes())]
        if parser:
            pipeline_els.append(parser)
        if decoder:
            decoder_str = plugin_str(decoder, codec_options)
            pipeline_els.append(decoder_str)
        pipeline_els.append("audioconvert")
        pipeline_els.append("audioresample")
        if QUEUE_TIME > 0:
            pipeline_els.append(get_element_str("queue", {
                "name": "queue",
                "min-threshold-time": 0,
                "max-size-buffers": 0,
                "max-size-bytes": 0,
                "max-size-time": QUEUE_TIME,
                "leaky": QUEUE_LEAK,
            }))
        pipeline_els.append(get_element_str("volume", {"name": "volume", "volume": 0}))
        if CLOCK_SYNC:
            if not has_plugins("clocksync"):
                log.warn("Warning: cannot enable clocksync, element not found")
            else:
                pipeline_els.append("clocksync")
        sink_attributes = SINK_SHARED_DEFAULT_ATTRIBUTES.copy()
        # anything older than this may cause problems (ie: centos 6.x)
        # because the attributes may not exist
        sink_attributes.update(SINK_DEFAULT_ATTRIBUTES.get(sink_type, {}))
        get_options_cb = DEFAULT_SINK_PLUGIN_OPTIONS.get(sink_type.replace("sink", ""))
        if get_options_cb:
            v = get_options_cb()
            log("%s()=%s", get_options_cb, v)
            sink_attributes.update(v)
        if sink_options:
            sink_attributes.update(sink_options)
        sink_attributes["name"] = "sink"
        if sink_type != "autoaudiosink":
            sink_attributes.update(NON_AUTO_SINK_ATTRIBUTES)
        sink_str = plugin_str(sink_type, sink_attributes)
        pipeline_els.append(sink_str)
        if not self.setup_pipeline_and_bus(pipeline_els):
            return
        self.volume = self.pipeline.get_by_name("volume")
        self.src = self.pipeline.get_by_name("src")
        self.sink = self.pipeline.get_by_name("sink")
        self.queue = self.pipeline.get_by_name("queue")
        if self.queue:
            if QUEUE_SILENT:
                self.queue.set_property("silent", False)
            else:
                self.queue.connect("overrun", self.queue_overrun)
                self.queue.connect("underrun", self.queue_underrun)
                self.queue.connect("running", self.queue_running)
                self.queue.connect("pushing", self.queue_pushing)
        self.init_file(codec)

    def __repr__(self):  # pylint: disable=arguments-differ
        return "AudioSink('%s' - %s)" % (self.pipeline_str, self.state)

    def cleanup(self) -> None:
        super().cleanup()
        self.cancel_volume_timer()
        self.sink_type = ""
        self.src = None

    def start(self) -> bool:
        if not super().start():
            return False
        GLib.timeout_add(UNMUTE_DELAY, self.start_adjust_volume)
        return True

    def start_adjust_volume(self, interval: int = 100) -> bool:
        if self.volume_timer != 0:
            GLib.source_remove(self.volume_timer)
        self.volume_timer = GLib.timeout_add(interval, self.adjust_volume)
        return False

    def cancel_volume_timer(self) -> None:
        if self.volume_timer != 0:
            GLib.source_remove(self.volume_timer)
            self.volume_timer = 0

    def adjust_volume(self) -> bool:
        if not self.volume:
            self.volume_timer = 0
            return False
        cv = self.volume.get_property("volume")
        delta = self.target_volume - cv
        from math import sqrt, copysign
        change = copysign(sqrt(abs(delta)), delta) / 15.0
        gstlog("adjust_volume current volume=%.2f, change=%.2f", cv, change)
        self.volume.set_property("volume", max(0, cv + change))
        if abs(delta) < 0.01:
            self.volume_timer = 0
            return False
        return True

    def queue_pushing(self, *_args) -> Literal[True]:
        gstlog("queue_pushing")
        self.queue_state = "pushing"
        self.emit_info()
        return True

    def queue_running(self, *_args) -> Literal[True]:
        gstlog("queue_running")
        self.queue_state = "running"
        self.emit_info()
        return True

    def queue_underrun(self, *_args) -> Literal[True]:
        now = monotonic()
        if self.queue_state == "starting" or 1000 * (now - self.start_time) < GRACE_PERIOD:
            gstlog("ignoring underrun during startup")
            return True
        self.underruns += 1
        gstlog("queue_underrun")
        self.queue_state = "underrun"
        if now - self.last_underrun > 5:
            # only count underruns when we're back to no min time:
            qmin = self.queue.get_property("min-threshold-time") // MS_TO_NS
            clt = self.queue.get_property("current-level-time") // MS_TO_NS
            gstlog("queue_underrun level=%3i, min=%3i", clt, qmin)
            if qmin == 0 and clt < 10:
                self.last_underrun = now
                self.refill = True
                self.set_max_level()
                self.set_min_level()
        self.emit_info()
        return True

    def get_level_range(self, mintime=2, maxtime=10) -> int:
        now = monotonic()
        filtered = [v for t, v in tuple(self.levels) if mintime <= (now - t) <= maxtime]
        if len(filtered) >= 10:
            maxl = max(filtered)
            minl = min(filtered)
            # range of the levels recorded:
            return maxl - minl
        return 0

    def queue_overrun(self, *_args) -> Literal[True]:
        now = monotonic()
        if self.queue_state == "starting" or 1000 * (now - self.start_time) < GRACE_PERIOD:
            gstlog("ignoring overrun during startup")
            return True
        clt = self.queue.get_property("current-level-time") // MS_TO_NS
        log("queue_overrun level=%ims", clt)
        now = monotonic()
        # grace period of recording overruns:
        # (because when we record an overrun, we lower the max-time,
        # which causes more overruns!)
        if now - self.last_overrun > 2:
            self.last_overrun = now
            self.set_max_level()
            self.overrun_events.append(now)
        self.overruns += 1
        return True

    def set_min_level(self) -> None:
        if not self.queue:
            return
        now = monotonic()
        elapsed = now - self.last_min_update
        lrange = self.get_level_range()
        log("set_min_level() lrange=%i, elapsed=%i", lrange, elapsed)
        if elapsed < 1:
            # not more than once a second
            return
        if self.refill:
            # need to have a gap between min and max,
            # so we cannot go higher than mst-50:
            mst = self.queue.get_property("max-size-time") // MS_TO_NS
            mrange = max(lrange + 100, UNDERRUN_MIN_LEVEL)
            mtt = min(mst - 50, mrange)
            gstlog("set_min_level mtt=%3i, max-size-time=%3i, lrange=%s, mrange=%s (UNDERRUN_MIN_LEVEL=%s)",
                   mtt, mst, lrange, mrange, UNDERRUN_MIN_LEVEL)
        else:
            mtt = 0
        cmtt = self.queue.get_property("min-threshold-time") // MS_TO_NS
        if cmtt == mtt:
            return
        if not self.level_lock.acquire(False):
            gstlog("cannot get level lock for setting min-threshold-time")
            return
        try:
            self.queue.set_property("min-threshold-time", mtt * MS_TO_NS)
            gstlog("set_min_level min-threshold-time=%s", mtt)
            self.last_min_update = now
        finally:
            self.level_lock.release()

    def set_max_level(self) -> None:
        if not self.queue:
            return
        now = monotonic()
        elapsed = now - self.last_max_update
        if elapsed < 1:
            # not more than once a second
            return
        lrange = self.get_level_range(mintime=0)
        log("set_max_level lrange=%3i, elapsed=%is", lrange, int(elapsed))
        cmst = self.queue.get_property("max-size-time") // MS_TO_NS
        # overruns in the last minute:
        olm = len([x for x in tuple(self.overrun_events) if now - x < 60])
        # increase target if we have more than 5 overruns in the last minute:
        target_mst = lrange * (100 + MARGIN + min(100, olm * 20)) // 100
        # from 100% down to 0% in 2 seconds after underrun:
        pct = max(0, int((self.last_overrun + 2 - now) * 50))
        # use this last_overrun percentage value to temporarily decrease the target
        # (causes overruns that drop packets and lower the buffer level)
        target_mst = max(50, int(target_mst - pct * lrange // 100))
        mst = (cmst + target_mst) // 2
        if self.refill:
            # temporarily raise max level during underruns,
            # so set_min_level has more room for manoeuver:
            mst += UNDERRUN_MIN_LEVEL
        # cap it at 1 second:
        mst = min(mst, 1000)
        log("set_max_level overrun count=%-2i, margin=%3i, pct=%2i, cmst=%3i, target=%3i, mst=%3i",
            olm, MARGIN, pct, cmst, target_mst, mst)
        if abs(cmst - mst) <= max(50, lrange // 2):
            # not enough difference
            return
        if not self.level_lock.acquire(False):
            gstlog("cannot get level lock for setting max-size-time")
            return
        try:
            self.queue.set_property("max-size-time", mst * MS_TO_NS)
            log("set_max_level max-size-time=%s", mst)
            self.last_max_update = now
        finally:
            self.level_lock.release()

    def eos(self) -> int:
        gstlog("eos()")
        if self.src:
            self.src.emit('end-of-stream')
        self.cleanup()
        return GST_FLOW_OK

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        if QUEUE_TIME > 0 and self.queue:
            clt = self.queue.get_property("current-level-time")
            qmax = self.queue.get_property("max-size-time")
            qmin = self.queue.get_property("min-threshold-time")
            info["queue"] = {
                "min": qmin // MS_TO_NS,
                "max": qmax // MS_TO_NS,
                "cur": clt // MS_TO_NS,
                "pct": min(QUEUE_TIME, clt) * 100 // qmax,
                "overruns": self.overruns,
                "underruns": self.underruns,
                "state": self.queue_state,
            }
        info["sink"] = self.get_element_properties(
            self.sink,
            "buffer-time", "latency-time",
            # "next_sample", "eos_rendering",
            "async", "blocksize",
            "enable-last-sample",
            "max-bitrate", "max-lateness",
            # "processing-deadline",
            "qos", "render-delay", "sync",
            "throttle-time", "ts-offset",
            ignore_missing=True
        )
        return info

    def can_push_buffer(self) -> bool:
        if not self.src:
            log("no source, dropping buffer")
            return False
        if self.state in ("stopped", "error"):
            log("pipeline is %s, dropping buffer", self.state)
            return False
        return True

    def add_data(self, data: bytes, metadata: dict, packet_metadata=()) -> None:
        if not self.can_push_buffer():
            return
        data = uncompress_data(data, metadata)
        for x in packet_metadata:
            self.do_add_data(x, {})
        if self.do_add_data(data, metadata):
            self.rec_queue_level(data)
            self.set_max_level()
            self.set_min_level()
            # drop back down quickly if the level has reached min:
            if self.refill:
                clt = self.queue.get_property("current-level-time") // MS_TO_NS
                qmin = self.queue.get_property("min-threshold-time") // MS_TO_NS
                gstlog("add_data: refill=%s, level=%i, min=%i", self.refill, clt, qmin)
                if 0 < qmin < clt:
                    self.refill = False
        self.emit_info()

    def do_add_data(self, data, metadata: dict) -> bool:
        # having a timestamp causes problems with the queue and overruns:
        log("do_add_data(%s bytes, %s) queue_state=%s", len(data), metadata, self.queue_state)
        self.save_to_file(data)
        buf = make_buffer(data)
        if metadata:
            # having a timestamp causes problems with the queue and overruns:
            # ts = metadata.get("timestamp")
            # if ts is not None:
            #    buf.timestamp = normv(ts)
            #    log.info("timestamp=%s", ts)
            d = metadata.get("duration")
            if d is not None:
                d = normv(d)
                if d > 0:
                    buf.duration = normv(d)
        if self.push_buffer(buf) == GST_FLOW_OK:
            self.inc_buffer_count()
            self.inc_byte_count(len(data))
            return True
        return False

    def rec_queue_level(self, data) -> None:
        q = self.queue
        if not q:
            return
        clt = q.get_property("current-level-time") // MS_TO_NS
        log("pushed %5i bytes, new buffer level: %3ims, queue state=%s", len(data), clt, self.queue_state)
        now = monotonic()
        self.levels.append((now, clt))

    def push_buffer(self, buf) -> int:
        # buf.size = size
        # buf.timestamp = timestamp
        # buf.duration = duration
        # buf.offset = offset
        # buf.offset_end = offset_end
        # buf.set_caps(gst.caps_from_string(caps))
        r = self.src.emit("push-buffer", buf)
        if r == GST_FLOW_OK:
            return r
        if self.queue_state != "error":
            log.error("Error pushing buffer: %s", r)
            self.update_state("error")
            self.emit('error', "push-buffer error: %s" % r)
        return 1


GObject.type_register(AudioSink)


def main() -> int:
    from xpra.platform import program_context
    with program_context("Audio-Record"):
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
        decoders = get_decoders()
        if len(args) == 3:
            codec = args[2]
            if codec not in decoders:
                print("invalid codec: %s" % codec)
                print("only supported: %s" % str(decoders.keys()))
                return 2
            codecs = [codec]
        else:
            codec = None
            parts = filename.split(".")
            if len(parts) > 1:
                extension = parts[-1]
                if extension.lower() in decoders:
                    codec = extension.lower()
                    print("guessed codec %s from file extension %s" % (codec, extension))
            if codec is None:
                print("assuming this is an mp3 file...")
                codec = MP3
            codecs = [codec]

        log.enable_debug()
        with open(filename, "rb") as f:
            data = f.read()
        print("loaded %s bytes from %s" % (len(data), filename))
        # force no leak since we push all the data at once
        from xpra.audio import gstreamer_util
        gstreamer_util.QUEUE_LEAK = GST_QUEUE_NO_LEAK
        gstreamer_util.QUEUE_SILENT = True

        ss = AudioSink("", sink_options={}, codecs=codecs, codec_options={})

        def eos(*eos_args) -> None:
            print("eos%s" % (eos_args,))
            GLib.idle_add(glib_mainloop.quit)

        ss.connect("eos", eos)
        ss.start()

        glib_mainloop = GLib.MainLoop()

        import signal

        def deadly_signal(*_args) -> None:
            GLib.idle_add(ss.stop)
            GLib.idle_add(glib_mainloop.quit)

            def force_quit(_sig, _frame) -> NoReturn:
                sys.exit()

            signal.signal(signal.SIGINT, force_quit)
            signal.signal(signal.SIGTERM, force_quit)

        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)

        def check_for_end(*_args) -> bool:
            qtime = ss.queue.get_property("current-level-time") // MS_TO_NS
            if qtime <= 0:
                log.info("underrun (end of stream)")
                start_thread(ss.stop, "stop", daemon=True)
                GLib.timeout_add(500, glib_mainloop.quit)
                return False
            return True

        GLib.timeout_add(1000, check_for_end)
        GLib.idle_add(ss.add_data, data)

        glib_mainloop.run()
        return 0


if __name__ == "__main__":
    sys.exit(main())
