#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the client `AudioClient` subsystem to the
server `AudioServer` subsystem (+ `AudioConnection` source).

Exercises the *interaction contract* between the two sides - audio capability
negotiation and the audio-data path - without a real GStreamer pipeline (the
background query threads are patched out and a mock sink is used).
"""

import unittest
from unittest.mock import patch, MagicMock

from xpra.util.objects import AdHocStruct, typedict

from unit.loopback_util import LoopbackTest


def _server_opts():
    opts = AdHocStruct()
    opts.audio_source = ""
    opts.speaker = "on"
    opts.speaker_codec = ["opus"]
    opts.microphone = "on"
    opts.microphone_codec = ["opus"]
    opts.av_sync = True
    return opts


def _client_opts():
    opts = AdHocStruct()
    opts.av_sync = True
    # keep both directions disabled so no real pipeline is ever started:
    opts.speaker = "off"
    opts.microphone = "off"
    opts.audio_source = ""
    opts.speaker_codec = ["opus"]
    opts.microphone_codec = ["opus"]
    opts.tray_icon = ""
    return opts


class AudioLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.audio import AudioClient
        from xpra.server.subsystem import audio as server_audio
        from xpra.server.source import audio as source_audio
        from xpra.server.subsystem.audio import AudioServer
        from xpra.server.source.audio import AudioConnection
        # avoid spawning the GStreamer query threads on either side, and skip the
        # backwards-compatible 5s wait for audio properties in init_from:
        with patch.object(AudioServer, "init_audio_options", lambda self: None), \
             patch.object(AudioClient, "load", lambda self: None), \
             patch.object(source_audio, "BACKWARDS_COMPATIBLE", False), \
             patch.object(server_audio, "BACKWARDS_COMPATIBLE", False):
            return self.connect(AudioClient, AudioServer, AudioConnection,
                                client_opts=_client_opts(), server_opts=_server_opts(),
                                caps={})

    def test_capability_negotiation(self):
        client, _server, source = self._connect()
        # make the server source ready to answer (non-empty audio_properties
        # means it echoes capabilities straight back):
        source.audio_properties = typedict({"gst.version": ("1", "0")})

        client.send("audio-capabilities", {
            "encoders": ("opus",),
            "decoders": ("opus",),
            "send": True,
            "receive": True,
        })

        # the client's capabilities reached the server source:
        self.assertTrue(any(p[0] == "audio-capabilities" for p in self.c2s))
        self.assertTrue(source.audio_send)
        self.assertTrue(source.audio_receive)
        self.assertIn("opus", source.audio_encoders)

        # the server echoed its own capabilities back:
        self.assertTrue(any(p[0] == "audio-capabilities" for p in self.s2c),
                        "server did not send audio capabilities back: %s" % (self.s2c,))
        # which the client parsed:
        self.assertTrue(client.server_send)
        self.assertIn("opus", client.server_encoders)

    def test_audio_data_server_to_client(self):
        from xpra.audio.common import AUDIO_DATA_PACKET
        client, _server, source = self._connect()
        # a mock sink standing in for the GStreamer pipeline:
        client.speaker_enabled = True
        client.speaker_allowed = True
        sink = MagicMock()
        sink.codec = "opus"
        sink.sequence = client.sink_sequence
        sink.get_state = MagicMock(return_value="ready")
        client.sink = sink

        # the server pushes an audio-data packet to the client:
        source.send(AUDIO_DATA_PACKET, "opus", b"payload", {"sequence": -1})

        # it crossed the wire and was forwarded to the client's sink:
        self.assertTrue(any(p[0] == AUDIO_DATA_PACKET for p in self.s2c))
        sink.add_data.assert_called()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
