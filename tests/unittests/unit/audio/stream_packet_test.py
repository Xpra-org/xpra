#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Newer peers mark the start and end of audio streams with `audio-stream` packets,
which we handle like the metadata of empty `audio-data` packets.
"""

import unittest
from unittest.mock import patch, MagicMock

from xpra.audio.common import AUDIO_STREAM_PACKET, audio_stream_metadata
from xpra.net.common import Packet

from unit.client.subsystem.audio_client_unit_test import _make_client, _make_sink


class TestAudioStreamMetadata(unittest.TestCase):

    def test_metadata(self):
        assert audio_stream_metadata("start", "opus", 2) == {"start-of-stream": True, "codec": "opus", "sequence": 2}
        assert audio_stream_metadata("end", "opus", 2) == {"end-of-stream": True, "sequence": 2}
        assert audio_stream_metadata("pause", "opus", 2) is None


class TestClient(unittest.TestCase):

    def test_capability(self):
        x = _make_client()
        x.properties = {"encoders": ["opus"]}
        assert x.get_audio_capabilities().get("stream-packet") is True

    def test_start(self):
        x = _make_client()
        x.speaker_allowed = True
        with patch.object(x, "start_sink") as start_sink:
            x._process_stream(Packet(AUDIO_STREAM_PACKET, "start", "opus", 0))
        start_sink.assert_called_once_with("opus")

    def test_end(self):
        x = _make_client(speaker_enabled=True)
        _make_sink(x)
        with patch.object(x, "stop_receiving_audio") as stop:
            x._process_stream(Packet(AUDIO_STREAM_PACKET, "end", "opus", 0))
        stop.assert_called_once_with(False)

    def test_unknown_event(self):
        x = _make_client(speaker_enabled=True)
        _make_sink(x)
        with patch.object(x, "_process_data") as process_data:
            x._process_stream(Packet(AUDIO_STREAM_PACKET, "pause", "opus", 0))
        process_data.assert_not_called()


class TestServer(unittest.TestCase):

    def test_capability(self):
        from xpra.server.source.audio import AudioConnection

        class FakeConnection(AudioConnection):
            def __init__(self):
                self.init_state()
                self.supports_speaker = self.supports_microphone = True
                self.speaker_codecs = self.microphone_codecs = ["opus"]
                self.audio_properties = {}

        assert FakeConnection().get_audio_caps().get("stream-packet") is True

    def test_process_stream(self):
        from xpra.server.subsystem.audio import AudioServer
        server = AudioServer.__new__(AudioServer)
        ss = MagicMock()
        server.server = MagicMock()
        server.server.get_server_source.return_value = ss
        server._process_stream(None, Packet(AUDIO_STREAM_PACKET, "end", "opus", 7))
        ss.audio_data.assert_called_once_with("opus", b"", {"end-of-stream": True, "sequence": 7})
        ss.reset_mock()
        server._process_stream(None, Packet(AUDIO_STREAM_PACKET, "start", "opus", 7))
        ss.audio_data.assert_called_once_with("opus", b"", {"start-of-stream": True, "codec": "opus", "sequence": 7})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
