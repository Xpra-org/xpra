#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
from time import monotonic

from xpra.gstreamer.common import get_element_str, plugin_str
from xpra.gstreamer.pipeline import Pipeline
from xpra.util.gobject import one_arg_signal
from xpra.log import Logger

log = Logger("audio", "gstreamer")

SILENCE_FLOOR_DB = -120.0
LEVEL_PRECISION = 1


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
        pipeline_els = [
            plugin_str("pulsesrc", {"device": device}),
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
