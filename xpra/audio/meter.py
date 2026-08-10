#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
from time import monotonic

from xpra.audio.common import SILENCE_FLOOR_DB
from xpra.gstreamer.common import get_element_str, plugin_str
from xpra.gstreamer.pipeline import Pipeline
from xpra.util.env import envint
from xpra.util.gobject import one_arg_signal
from xpra.log import Logger

log = Logger("audio", "gstreamer")

LEVEL_PRECISION = 1

# the meter only needs one sample batch per `interval`,
# so we can use a much larger latency than the default (10ms)
# and a large ring buffer, which makes overruns much less likely:
LATENCY_TIME = envint("XPRA_AUDIO_METER_LATENCY_TIME", 0)
BUFFER_TIME = envint("XPRA_AUDIO_METER_BUFFER_TIME", 0)

# dropping samples is harmless for a level meter,
# the only consequence is that some levels are calculated from fewer samples:
IGNORED_WARNINGS = ("Can't record audio fast enough", )


def get_source_channels(device: str) -> int:
    try:
        from xpra.audio.pulseaudio.util import get_source_channels as query_source_channels
        return query_source_channels(device)
    except Exception as e:
        log("failed to query source channels for %r: %s", device, e)
        return 0


def normalize_levels(values) -> list[float]:
    """Convert GStreamer's value array to finite, serializable dBFS values."""
    levels = []
    for value in values or ():
        level = float(value)
        if not math.isfinite(level) or level < SILENCE_FLOOR_DB:
            level = SILENCE_FLOOR_DB
        levels.append(round(level, LEVEL_PRECISION))
    return levels


class AudioLevelMeter(Pipeline):
    __gsignals__ = Pipeline.__generic_signals__.copy()
    __gsignals__["level"] = one_arg_signal

    def __init__(self, device: str, interval: int):
        super().__init__()
        self.device = device
        self.interval = interval
        self.last_level: tuple[tuple[float, ...], tuple[float, ...]] | None = None
        self.overruns = 0
        # in microseconds:
        latency_time = (LATENCY_TIME or interval) * 1000
        buffer_time = (BUFFER_TIME * 1000) or (latency_time * 4)
        pipeline_els = [
            plugin_str("pulsesrc", {
                "device": device,
                "latency-time": latency_time,
                "buffer-time": buffer_time,
                # we don't need this pipeline to drive the clock:
                "provide-clock": False,
            }),
            "audioconvert",
        ]
        if channels := get_source_channels(device):
            pipeline_els.append(f"audio/x-raw,channels={channels}")
        pipeline_els += [
            get_element_str("level", {
                "name": "level",
                "interval": interval * 1000000,
                "post-messages": True,
            }),
            get_element_str("fakesink", {"sync": False}),
        ]
        self.setup_pipeline_and_bus(pipeline_els)

    def handle_warning(self, warning) -> None:
        if warning and warning[0].message in IGNORED_WARNINGS:
            self.overruns += 1
            self.info["overruns"] = self.overruns
            log("ignoring harmless audio meter warning: %s", warning[0].message)
            return
        super().handle_warning(warning)

    def do_parse_element_message(self, _message, name, props=None) -> None:
        if name != "level" or not props:
            return
        rms = normalize_levels(props.get("rms"))
        peak = normalize_levels(props.get("peak"))
        level = (tuple(rms), tuple(peak))
        if level == self.last_level:
            return
        self.last_level = level
        sample = {
            "time": int(monotonic() * 1000),
            "interval": self.interval,
            "unit": "dBFS",
            "rms": rms,
            "peak": peak,
        }
        self.info["level"] = sample
        self.idle_emit("level", sample)
        log("audio level=%s", sample)
