#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.audio.pulseaudio.pactl_impl import do_get_pa_device_options

# Minimal pactl list output with one Sink section and one Source section
SINK_AND_SOURCE = b"""Sink #0
\tName: Xpra-Microphone
\tdevice.class = "abstract"
\tdevice.description = "Dummy Output"

Source #0
\tName: Xpra-Speaker.monitor
\tMonitor of Sink: Xpra-Speaker
\tdevice.description = "Monitor of Xpra-Speaker"

"""

# Output with both a monitor source and a regular (non-monitor) source
MIXED_SOURCES = b"""Source #0
\tName: alsa.monitor
\tMonitor of Sink: alsa_output
\tdevice.description = "Monitor of ALSA"

Source #1
\tName: alsa_input.mic
\tdevice.class = "sound"
\tdevice.description = "Built-in Mic"

"""


class TestDoGetPaDeviceOptions(unittest.TestCase):

    def test_sink_sections_excluded(self):
        # Sink sections must not appear as audio sources
        devices = do_get_pa_device_options(SINK_AND_SOURCE, monitors=None, input_or_output=None)
        assert "Xpra-Microphone" not in devices
        assert "Xpra-Speaker.monitor" in devices

    def test_sink_only_output_returns_empty(self):
        # Output with only Sink sections and no Sources returns empty dict
        sink_only = b"""Sink #0
\tName: Xpra-Microphone
\tdevice.class = "abstract"
\tdevice.description = "Dummy Output"

"""
        devices = do_get_pa_device_options(sink_only, monitors=None, input_or_output=None)
        assert devices == {}

    def test_monitor_filter_true(self):
        # monitors=True returns only monitor sources
        devices = do_get_pa_device_options(MIXED_SOURCES, monitors=True, input_or_output=None)
        assert "alsa.monitor" in devices
        assert "alsa_input.mic" not in devices

    def test_monitor_filter_false(self):
        # monitors=False excludes monitor sources
        devices = do_get_pa_device_options(MIXED_SOURCES, monitors=False, input_or_output=None)
        assert "alsa.monitor" not in devices
        assert "alsa_input.mic" in devices

    def test_monitor_filter_none(self):
        # monitors=None returns both monitor and non-monitor sources
        devices = do_get_pa_device_options(MIXED_SOURCES, monitors=None, input_or_output=None)
        assert "alsa.monitor" in devices
        assert "alsa_input.mic" in devices

    def test_empty_output(self):
        devices = do_get_pa_device_options(b"", monitors=None, input_or_output=None)
        assert devices == {}


def main():
    unittest.main()


if __name__ == "__main__":
    main()
