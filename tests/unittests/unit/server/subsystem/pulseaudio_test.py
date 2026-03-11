#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.server.subsystem.stub import StubServerMixin
from xpra.server.subsystem.pulseaudio import PulseaudioServer, get_default_pulseaudio_command


class TestGetDefaultPulseaudioCommand(unittest.TestCase):

    def test_speaker_loaded_after_microphone(self):
        # Xpra-Speaker must be the last null sink loaded so it is the PA default
        # when the socket opens - preventing clients from attaching to Xpra-Microphone
        cmd = get_default_pulseaudio_command()
        mic_idx = next((i for i, a in enumerate(cmd) if "Xpra-Microphone" in a), None)
        spk_idx = next((i for i, a in enumerate(cmd) if "Xpra-Speaker" in a), None)
        assert mic_idx is not None, "Xpra-Microphone not found in PA command"
        assert spk_idx is not None, "Xpra-Speaker not found in PA command"
        assert mic_idx < spk_idx, \
            "Xpra-Speaker must load after Xpra-Microphone so it becomes the PA default"

    def test_native_protocol_loaded(self):
        # module-native-protocol-unix must be present so clients can connect
        cmd = get_default_pulseaudio_command()
        assert any("module-native-protocol-unix" in a for a in cmd)

    def test_mic_source_remap_loaded(self):
        # module-remap-source for Xpra-Mic-Source must be present for microphone forwarding
        cmd = get_default_pulseaudio_command()
        assert any("Xpra-Mic-Source" in a for a in cmd)


class TestPulseaudioServerGetChildEnv(unittest.TestCase):

    def setUp(self):
        self.server = PulseaudioServer()

    def test_pulse_vars_not_added_to_child_env(self):
        # get_child_env must not add PULSE_SINK or PULSE_SOURCE - those would
        # override PA routing for user applications
        pulse_env = self.server.get_pulse_env()
        base_env = StubServerMixin.get_child_env(self.server)
        child_env = self.server.get_child_env()
        for key in pulse_env:
            if key not in base_env:
                assert key not in child_env, \
                    f"{key} must not be added to child process environment"


def main():
    from xpra.os_util import POSIX, OSX
    if POSIX and not OSX:
        unittest.main()


if __name__ == "__main__":
    main()
