#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import sleep
from threading import Event, Thread
from unittest.mock import patch

from xpra.util.objects import typedict
from xpra.audio.common import SILENCE_FLOOR_DB
from xpra.server.source.audio import AudioConnection
from xpra.server.subsystem.audio import (
    AUDIO_LEVEL_DEVICE, AUDIO_LEVEL_INTERVAL, AUDIO_SIGNAL_DELAY, AudioServer,
)


class FakePulse:
    def __init__(self):
        self.enabled = True
        self.init_done = Event()
        self.init_done.set()
        self.pid = 123
        self.proc = None


class FakeServer:
    _closing = False

    def __init__(self):
        self.subsystems = {"pulseaudio": FakePulse()}
        self.sources = []
        self.timers = {}
        self.next_timer = 1

    @staticmethod
    def idle_add(callback, *args):
        return callback(*args)

    def timeout_add(self, delay, callback, *args):
        timer = self.next_timer
        self.next_timer += 1
        self.timers[timer] = (delay, callback, args)
        return timer

    def source_remove(self, timer):
        self.timers.pop(timer, None)

    def get_sources_by_type(self, subsystem_type=object, exclude=None):
        return tuple(source for source in self.sources
                     if isinstance(source, subsystem_type) and source != exclude)

    def fire_timer(self, timer):
        _delay, callback, args = self.timers.pop(timer)
        callback(*args)


class FakeSource(AudioConnection):
    def __init__(self):
        self.levels = []
        self.signals = []

    def send_audio_level(self, level):
        self.levels.append(level)

    def send_audio_signal(self, signal):
        self.signals.append(signal)


class FakeMeter:
    process = None

    def __init__(self):
        self.callbacks = {}
        self.started = False
        self.cleaned = False

    def connect(self, signal, callback):
        self.callbacks[signal] = callback

    def start(self):
        self.started = True

    def cleanup(self):
        self.cleaned = True


class TestAudioServerMeter(unittest.TestCase):

    def setUp(self):
        self.owner = FakeServer()
        self.server = AudioServer(self.owner)
        self.server.supports_speaker = True
        self.server.audio_properties = typedict({"initialized": True})
        self.server.meter_state = "pending"
        self.source = FakeSource()
        self.owner.sources.append(self.source)

    def test_meter_requires_speaker_support(self):
        self.server.supports_speaker = False
        self.server.init_meter()
        assert self.server.meter_state == "disabled"
        assert self.server.meter_start_timer == 0

    def test_no_info_without_audio_properties(self):
        self.server.audio_properties = typedict()
        assert self.server.get_info(None) == {}

    def test_cleanup_prevents_late_start(self):
        self.server.cleanup_meter()
        self.server.init_meter()
        assert self.server.meter_start_timer == 0
        self.server.start_meter()
        assert self.server.meter is None

    def test_cleanup_interrupts_pulseaudio_wait(self):
        pulse = self.owner.subsystems["pulseaudio"]
        pulse.init_done.clear()
        thread = Thread(target=self.server.init_meter, daemon=True)
        thread.start()
        sleep(0.2)
        self.server.cleanup_meter()
        thread.join(1)
        assert not thread.is_alive(), "the pulseaudio wait was not interrupted by cleanup"
        assert self.server.meter_start_timer == 0
        assert self.server.meter_state == "stopped"

    def test_meter_is_scheduled_after_pulseaudio_init(self):
        self.server.init_meter()
        assert self.server.meter_start_timer == 1

        pulse = self.owner.subsystems["pulseaudio"]
        pulse.pid = 0
        self.server.meter_start_timer = 0
        self.server.init_meter()
        assert self.server.meter_state == "unavailable"

        pulse.enabled = False
        self.server.init_meter()
        assert self.server.meter_state == "disabled"

    def test_start_and_level_info(self):
        meter = FakeMeter()
        with patch("xpra.audio.wrapper.start_audio_meter", return_value=meter) as start:
            self.server.start_meter()
        start.assert_called_once_with(AUDIO_LEVEL_DEVICE, AUDIO_LEVEL_INTERVAL)
        assert meter.started
        assert set(meter.callbacks) == {"level", "state-changed", "error", "exit"}

        sample = {
            "time": 1234,
            "interval": AUDIO_LEVEL_INTERVAL,
            "unit": "dBFS",
            "rms": [-20.0, -21.0],
            "peak": [-3.0, -4.0],
        }
        self.server.meter_level(meter, sample)
        info = self.server.get_info(None)["audio"]
        assert info["meter"]["state"] == "active"
        assert info["meter"]["interval"] == AUDIO_LEVEL_INTERVAL
        assert info["level"] | {"time": 1234} == sample
        assert info["level"]["time"] >= 0
        assert self.source.levels == [info["level"]]

        self.server.meter_error(meter, "test error")
        info = self.server.get_info(None)["audio"]
        assert info["meter"]["state"] == "error"
        assert "level" not in info
        assert self.server.meter is None
        assert meter.cleaned

    def test_start_failure_cleans_meter(self):
        class FailingMeter(FakeMeter):
            def start(self):
                self.started = True
                raise RuntimeError("test failure")

        meter = FailingMeter()
        with patch("xpra.audio.wrapper.start_audio_meter", return_value=meter):
            self.server.start_meter()
        assert meter.started
        assert meter.cleaned
        assert self.server.meter is None
        assert self.server.meter_state == "error"

    def test_signal_edge_detection(self):
        meter = FakeMeter()
        self.server.meter = meter

        silence = {"peak": [SILENCE_FLOOR_DB], "rms": [SILENCE_FLOOR_DB]}
        active = {"peak": [-30.0], "rms": [-50.0]}

        self.server.meter_level(meter, silence)
        assert self.server.signal_timer == 0
        assert self.source.signals == []

        # A short-lived edge is cancelled before the delay expires.
        self.server.meter_level(meter, active)
        timer = self.server.signal_timer
        assert self.owner.timers[timer][0] == AUDIO_SIGNAL_DELAY == 2000
        self.server.meter_level(meter, active)
        assert self.server.signal_timer == timer
        self.server.meter_level(meter, silence)
        assert timer not in self.owner.timers
        assert self.source.signals == []

        self.server.meter_level(meter, active)
        self.owner.fire_timer(self.server.signal_timer)
        assert self.source.signals == [True]

        self.server.meter_level(meter, silence)
        self.owner.fire_timer(self.server.signal_timer)
        assert self.source.signals == [True, False]

    def test_cleanup(self):
        meter = FakeMeter()
        self.server.meter = meter
        self.server.meter_start_timer = 1
        self.server.cleanup_meter()
        assert meter.cleaned
        assert self.server.meter is None
        assert self.server.meter_start_timer == 0
        assert self.server.meter_state == "stopped"


def main():
    unittest.main()


if __name__ == "__main__":
    main()
