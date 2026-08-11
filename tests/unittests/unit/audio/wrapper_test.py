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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
