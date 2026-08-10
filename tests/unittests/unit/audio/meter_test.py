#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.gstreamer.common import has_plugins
from xpra.audio.common import SILENCE_FLOOR_DB
from xpra.audio.meter import AudioLevelMeter, normalize_levels
from xpra.audio import wrapper as audio_wrapper
from xpra.audio.wrapper import MeterSubprocessWrapper


class TestAudioLevelMeter(unittest.TestCase):

    def test_normalize_levels(self):
        assert normalize_levels((-12.54, float("-inf"), -200)) == [
            -12.5, SILENCE_FLOOR_DB, SILENCE_FLOOR_DB,
        ]

    def test_level_message(self):
        if not has_plugins("pulsesrc", "level", "fakesink"):
            raise unittest.SkipTest("audio level meter plugins are missing")
        with patch("xpra.audio.meter.get_source_channels", return_value=2):
            meter = AudioLevelMeter("Xpra-Speaker.monitor", 250)
        try:
            emitted = []
            meter.idle_emit = lambda signal, sample: emitted.append((signal, sample))
            assert "pulsesrc" in meter.pipeline_str
            assert 'device="Xpra-Speaker.monitor"' in meter.pipeline_str
            assert "interval=250000000" in meter.pipeline_str
            assert "audio/x-raw,channels=2" in meter.pipeline_str
            assert "fakesink" in meter.pipeline_str
            meter.do_parse_element_message(None, "level", {
                "rms": (-20.0, -21.0),
                "peak": (-3.0, float("-inf")),
            })
            sample = meter.info["level"]
            assert sample["interval"] == 250
            assert sample["unit"] == "dBFS"
            assert sample["rms"] == [-20.0, -21.0]
            assert sample["peak"] == [-3.0, SILENCE_FLOOR_DB]
            assert isinstance(sample["time"], int)
            assert len(emitted) == 1

            # Changes below the reporting precision must not generate traffic.
            meter.do_parse_element_message(None, "level", {
                "rms": (-20.01, -21.04),
                "peak": (-3.04, float("-inf")),
            })
            assert len(emitted) == 1

            meter.do_parse_element_message(None, "level", {
                "rms": (-20.2, -21.0),
                "peak": (-3.0, float("-inf")),
            })
            assert len(emitted) == 2

            silence = {"rms": (float("-inf"),) * 2, "peak": (float("-inf"),) * 2}
            meter.do_parse_element_message(None, "level", silence)
            meter.do_parse_element_message(None, "level", silence)
            assert len(emitted) == 3
            assert emitted[-1][1]["rms"] == [SILENCE_FLOOR_DB] * 2
            assert emitted[-1][1]["peak"] == [SILENCE_FLOOR_DB] * 2
        finally:
            meter.cleanup()

    def test_subprocess_command(self):
        wrapper = MeterSubprocessWrapper("Xpra-Speaker.monitor", 250)
        assert wrapper.command[-5:] == [
            "_audio_meter", "-", "-", "Xpra-Speaker.monitor", "250",
        ]

    def test_subprocess_command_dispatch(self):
        instances = []

        class FakeMeter:
            def __init__(self, *args):
                self.args = args
                self.started = False
                self.stopped = False
                instances.append(self)

            def start(self):
                self.started = True

            def stop(self):
                self.stopped = True

        with patch.object(audio_wrapper, "import_gst", return_value=object()), \
                patch.object(audio_wrapper, "AudioMeter", FakeMeter):
            assert audio_wrapper.run_audio(
                "_audio_meter", ["-", "-", "Xpra-Speaker.monitor", "250"],
            ) == 0
        assert len(instances) == 1
        assert instances[0].args == ("Xpra-Speaker.monitor", 250)
        assert instances[0].started
        assert instances[0].stopped


def main():
    unittest.main()


if __name__ == "__main__":
    main()
