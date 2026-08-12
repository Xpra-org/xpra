#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch


class TestStartReceivingAudio(unittest.TestCase):

    def test_configured_sink(self):
        from xpra.audio import wrapper

        with patch.object(wrapper, "SinkSubprocessWrapper") as sink_wrapper, \
                patch("xpra.audio.gstreamer_util.get_sink_device_name",
                      return_value="Built-in Audio Analog Stereo"):
            result = wrapper.start_receiving_audio(
                "opus", "pulsesink:device=device-name,sync=false",
            )

        assert result == sink_wrapper.return_value
        sink_wrapper.assert_called_once_with(
            "pulsesink", "opus", 1.0,
            {"device": "device-name", "sync": "false"},
            "Built-in Audio Analog Stereo",
        )

    def test_default_sink(self):
        from xpra.audio import wrapper

        with patch.object(wrapper, "SinkSubprocessWrapper") as sink_wrapper:
            wrapper.start_receiving_audio("opus")

        sink_wrapper.assert_called_once_with("auto", "opus", 1.0, {}, "")


class TestSubprocessWrapperInfo(unittest.TestCase):

    def test_capture_info(self):
        from xpra.audio.wrapper import SourceSubprocessWrapper
        src = SourceSubprocessWrapper("pulsesrc", {}, ["opus"], 1.0, {"device": "monitor"})
        info = src.get_info()
        assert info["description"] == "audio capture"
        assert info["state"] == "stopped"
        assert "_audio_record" in info["command"]
        assert "device=monitor" in info["command"]

    def test_playback_info(self):
        from xpra.audio.wrapper import SinkSubprocessWrapper
        sink = SinkSubprocessWrapper("pulsesink", "opus", 1.0, {}, "Some Device")
        info = sink.get_info()
        assert info["description"] == "audio playback"
        assert "_audio_play" in info["command"]

    def test_state_and_description_from_info_packets(self):
        from xpra.audio.wrapper import SourceSubprocessWrapper
        src = SourceSubprocessWrapper("pulsesrc", {}, ["opus"], 1.0, {})
        # the pipeline does not emit `state-changed` when it becomes active,
        # the state can only be picked up from the info packets:
        src.info_update(None, {"state": "active", "codec_description": "opus", "pipeline": "pulsesrc ! opusenc"})
        assert src.get_state() == "active"
        info = src.get_info()
        assert info["state"] == "active"
        assert info["pipeline"] == "pulsesrc ! opusenc"
        # info packets only carry the values which have changed,
        # so the codec description must not be cleared by the next one:
        src.info_update(None, {"bitrate": 24000})
        assert src.codec_description == "opus"
        assert src.get_info()["codec_description"] == "opus"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
