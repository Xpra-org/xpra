#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch


class TestAudioSinkOptions(unittest.TestCase):

    @staticmethod
    def make_sink(sink_type: str):
        from xpra.audio.sink import AudioSink

        with patch("xpra.audio.sink.get_default_sink_plugin", return_value="pulsesink"), \
                patch("xpra.audio.sink.get_sink_plugins", return_value=["autoaudiosink", "pulsesink"]), \
                patch("xpra.audio.sink.get_decoders", return_value={"opus": object()}), \
                patch("xpra.audio.sink.CODEC_ORDER", ("opus",)), \
                patch("xpra.audio.sink.get_decoder_elements", return_value=("", "", "")), \
                patch("xpra.audio.sink.DEFAULT_SINK_PLUGIN_OPTIONS", {}), \
                patch.object(AudioSink, "setup_pipeline_and_bus", return_value=False):
            return AudioSink(sink_type, {}, ["opus"], {})

    def test_auto_sink_and_options(self):
        from xpra.audio.sink import AudioSink

        pipeline_elements = []

        def capture_pipeline(_sink, elements) -> bool:
            pipeline_elements.extend(elements)
            return False

        with patch("xpra.audio.sink.get_default_sink_plugin", return_value="fakesink") as default_sink, \
                patch("xpra.audio.sink.get_sink_plugins", return_value=["fakesink"]), \
                patch("xpra.audio.sink.get_decoders", return_value={"opus": object()}), \
                patch("xpra.audio.sink.CODEC_ORDER", ("opus",)), \
                patch("xpra.audio.sink.get_decoder_elements", return_value=("", "", "")), \
                patch.object(AudioSink, "setup_pipeline_and_bus", capture_pipeline):
            sink = AudioSink("auto", {"device": "device-name", "sync": "true"}, ["opus"], {})

        default_sink.assert_called_once_with()
        assert sink.sink_type == "fakesink"
        assert pipeline_elements[-1].startswith("fakesink ")
        assert 'device="device-name"' in pipeline_elements[-1]
        assert 'sync="true"' in pipeline_elements[-1]

    def test_sink_type_in_codec_log(self):
        sink = self.make_sink("pulsesink")
        with patch.object(sink, "gstloginfo") as gstloginfo:
            sink.new_codec_description("Opus")
        gstloginfo.assert_called_once_with(
            "using '%s' %s", "opus", "audio codec with 'Pulseaudio' sink",
        )

    def test_auto_sink_omitted_from_codec_log(self):
        for sink_type in ("auto", "autoaudiosink"):
            sink = self.make_sink(sink_type)
            with patch.object(sink, "gstloginfo") as gstloginfo:
                sink.new_codec_description("Opus")
            gstloginfo.assert_called_once_with("using '%s' %s", "opus", "audio codec")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
