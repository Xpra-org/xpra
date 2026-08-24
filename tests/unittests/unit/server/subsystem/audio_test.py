#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.util.objects import AdHocStruct, typedict

from unit.test_util import silence_info
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class FakeAudioSource:

    def __init__(self, codec):
        self.codec = codec
        self.sequence = 0
        self.volume = 1.0
        self.started = False
        self.cleaned_up = False
        self.signals = {}

    def connect(self, signal, callback):
        self.signals[signal] = callback

    def start(self):
        self.started = True

    def cleanup(self):
        self.cleaned_up = True

    def get_volume(self):
        return self.volume

    def set_volume(self, volume):
        self.volume = volume


class AudioMixinTest(ServerMixinTest):

    @classmethod
    def setUpClass(cls):
        ServerMixinTest.setUpClass()
        from xpra.net import packet_encoding
        packet_encoding.init_all()
        from xpra.net import compression
        compression.init_all()

    def test_audio(self):
        from xpra.server.subsystem import audio
        from xpra.server.source.audio import AudioConnection
        from xpra.audio import wrapper
        opts = AdHocStruct()
        opts.audio_source = "test"
        opts.speaker = "on"
        opts.speaker_codec = ("opus",)
        opts.microphone = "on"
        opts.microphone_codec = ("opus",)
        opts.audio = True
        opts.pulseaudio = False
        opts.pulseaudio_command = "/bin/true"
        opts.pulseaudio_configure_commands = []
        opts.av_sync = True
        audio_properties = typedict({
            "gst.version": ("1", "0", "0", "0"),
            "sources": ("audiotestsrc",),
            "sinks": (),
            "encoders": ("opus",),
            "decoders": ("opus",),
            "muxers": (),
            "demuxers": (),
        })
        audio_source = FakeAudioSource("opus")
        with silence_info(audio), \
                patch.object(audio, "start_thread", side_effect=lambda fn, *_args: fn()), \
                patch.object(self, "idle_add", side_effect=lambda fn, *args: fn(*args)), \
                patch.object(wrapper, "query_audio", return_value=audio_properties), \
                patch.object(wrapper, "start_sending_audio", return_value=audio_source) as start_audio:
            self._test_mixin_class(audio.AudioServer, opts, {
                "audio": {
                    "receive": True,
                    "decoders": ("opus",),
                },
            }, AudioConnection)
            self.assertEqual(self.mixin.speaker_codecs, ("opus",))
            self.assertEqual(self.source.audio_properties, audio_properties)
            self.handle_packet(("audio-control", "start", "opus"))
            start_audio.assert_called_once_with(
                ("audiotestsrc",), "test", "", "opus", 1.0, True, ["opus"], "", "",
            )
            self.assertIs(self.source.audio_source, audio_source)
            self.assertTrue(audio_source.started)
            self.handle_packet(("audio-control", "fadeout"))
            self.handle_packet(("audio-control", "stop"))
            self.assertIsNone(self.source.audio_source)
            self.assertTrue(audio_source.cleaned_up)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
