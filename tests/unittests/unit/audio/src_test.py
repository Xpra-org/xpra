#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.audio import src as audio_src
from xpra.gstreamer.common import import_gst, has_plugins


def _elements(channels: int, src_type="pulsesrc") -> list[str]:
    src_options = {"device": "test.monitor"} if src_type == "pulsesrc" else {}
    with patch.object(audio_src, "_get_source_channels", lambda *_args: channels):
        return audio_src.get_source_pipeline_elements(src_type, src_options, "opusenc", "oggmux", {})


class TestSourcePipelineElements(unittest.TestCase):
    """Tests for the capture pipeline element list. No GStreamer needed."""

    def test_caps_filter_added_for_stereo(self):
        assert "audio/x-raw,channels=2" in _elements(2)

    def test_no_caps_filter_when_unknown(self):
        assert not [x for x in _elements(0) if x.startswith("audio/x-raw")]

    def test_removesilence_skipped_for_multichannel(self):
        # `removesilence` pad templates are fixed at channels=1,
        # so it must never appear alongside a multi-channel caps filter:
        for channels in (2, 6):
            els = _elements(channels)
            assert "removesilence" not in els, f"removesilence must be skipped for {channels} channels: {els}"

    def test_removesilence_used_for_mono(self):
        if not has_plugins("removesilence"):
            raise unittest.SkipTest("removesilence plugin is not installed")
        for channels in (0, 1):
            assert "removesilence" in _elements(channels), f"removesilence missing for {channels} channels"


class TestSourcePipelineParses(unittest.TestCase):
    """Verify the generated pipeline strings actually link."""

    def setUp(self):
        gst = import_gst()
        if not gst:
            raise unittest.SkipTest("GStreamer is not available")
        if not has_plugins("pulsesrc", "audioconvert", "volume", "opusenc", "oggmux", "appsink"):
            raise unittest.SkipTest("some required GStreamer plugins are missing")
        self.gst = gst

    def _parse(self, channels: int) -> None:
        pipeline_str = " ! ".join(_elements(channels))
        try:
            # parse only: the elements are created but never set to PLAYING,
            # so this does not need a running PulseAudio server
            self.gst.parse_launch(pipeline_str)
        except Exception as e:
            raise AssertionError(f"failed to parse pipeline for {channels} channels: {e}\n{pipeline_str}") from None

    def test_parse_mono(self):
        self._parse(0)
        self._parse(1)

    def test_parse_stereo(self):
        # regression test: `audio/x-raw,channels=2 ! removesilence` cannot link,
        # which used to kill the whole capture pipeline on stereo PulseAudio sources
        self._parse(2)

    def test_parse_surround(self):
        self._parse(6)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
