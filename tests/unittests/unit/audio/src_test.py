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

    def test_no_removesilence(self):
        # `removesilence` pad templates are fixed at channels=1, and it is a no-op
        # with the default properties, so it must never be added to the pipeline:
        for channels in (0, 1, 2, 6):
            els = _elements(channels)
            assert "removesilence" not in els, f"removesilence must not be used ({channels} channels): {els}"

    def test_cutter_is_leaky_and_precedes_the_encoder(self):
        if not has_plugins("cutter"):
            raise unittest.SkipTest("cutter plugin is not installed")
        els = _elements(2)
        cutters = [i for i, el in enumerate(els) if el.startswith("cutter ")]
        assert len(cutters) == 1, f"expected exactly one cutter element: {els}"
        cutter = els[cutters[0]]
        # it must drop the silent buffers itself, rather than at the appsink
        # where they would already be encoded and muxed:
        assert "leaky=True" in cutter, f"cutter must be leaky: {cutter!r}"
        encoders = [i for i, el in enumerate(els) if el.startswith("opusenc")]
        assert encoders, f"no encoder in the pipeline: {els}"
        assert cutters[0] < encoders[0], f"cutter must come before the encoder: {els}"

    def test_cutter_disabled_by_threshold(self):
        with patch.object(audio_src, "CUTTER_THRESHOLD", 0):
            els = _elements(2)
        assert not [el for el in els if el.startswith("cutter")], f"cutter must be disabled: {els}"


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


class TestCutterRuns(unittest.TestCase):
    """Run the generated pipeline for real, with a test source instead of pulsesrc."""

    def setUp(self):
        gst = import_gst()
        if not gst:
            raise unittest.SkipTest("GStreamer is not available")
        if not has_plugins("cutter", "audiotestsrc", "opusenc", "oggmux"):
            raise unittest.SkipTest("some required GStreamer plugins are missing")
        self.gst = gst

    def _run(self, channels: int) -> list[bool]:
        els = _elements(channels)
        # `wave=ticks` alternates between clicks and silence, so `cutter` has something to cut.
        # the tick interval has to exceed CUTTER_RUN_LENGTH for the silence to be reported,
        # and 200 buffers is ~4.6s, long enough for a couple of transitions:
        els[0] = "audiotestsrc num-buffers=200 wave=ticks tick-interval=2000000000"
        els[-1] = "fakesink name=sink"
        # the source queue is `leaky=downstream` with a 50ms limit, which is fine for a live
        # `pulsesrc` but throws most of the stream away when a test source runs flat out:
        els = [el for el in els if not el.startswith("queue ")]
        pipeline = self.gst.parse_launch(" ! ".join(els))
        bus = pipeline.get_bus()
        pipeline.set_state(self.gst.State.PLAYING)
        above = []
        try:
            wanted = self.gst.MessageType.ERROR | self.gst.MessageType.EOS | self.gst.MessageType.ELEMENT
            while True:
                msg = bus.timed_pop_filtered(10 * self.gst.SECOND, wanted)
                assert msg, f"timed out waiting for EOS ({channels} channels)"
                if msg.type == self.gst.MessageType.ERROR:
                    raise AssertionError(f"pipeline error ({channels} channels): {msg.parse_error()[0]}")
                if msg.type == self.gst.MessageType.EOS:
                    return above
                structure = msg.get_structure()
                if structure and structure.get_name() == "cutter":
                    # this is the message name `do_parse_element_message` keys off:
                    above.append(structure.get_value("above"))
        finally:
            pipeline.set_state(self.gst.State.NULL)

    def test_cutter_runs_and_reports_silence(self):
        for channels in (0, 2):
            above = self._run(channels)
            assert above, f"cutter posted no messages ({channels} channels)"
            assert False in above, f"cutter never detected any silence ({channels} channels): {above}"


def main():
    unittest.main()


if __name__ == '__main__':
    main()
