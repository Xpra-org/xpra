#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import MagicMock

from xpra.net.common import Packet
from xpra.net.audio_packet import (
    MAX_AUDIO_DATA, MAX_AUDIO_CAPABILITY_ITEMS, MAX_AUDIO_CAPABILITY_NAME, MAX_AUDIO_CAPABILITY_STRING, MAX_AUDIO_DEVICE_NAME,
    parse_audio_data_packet, parse_audio_stream_packet, parse_audio_control_packet,
    parse_audio_capabilities_packet, parse_audio_keepalive_packet,
)


def data_packet(codec="opus", data=b"data", metadata=None, *extra) -> Packet:
    return Packet("audio-data", codec, data, {"sequence": 1} if metadata is None else metadata, *extra)


class AudioPacketTest(unittest.TestCase):

    def test_data(self):
        audio = parse_audio_data_packet(data_packet(metadata={
            "sequence": 2, "timestamp": -1, "duration": 20.5, "time": 1000, "compress": "lz4",
            "codec": "opus", "start-of-stream": True,
        }))
        self.assertEqual(audio.codec, "opus")
        self.assertEqual(audio.data, b"data")
        self.assertEqual(audio.packet_metadata, ())
        audio = parse_audio_data_packet(data_packet("opus", b"data", {}, [b"header1", b"header2"]))
        self.assertEqual(audio.packet_metadata, (b"header1", b"header2"))
        # the legacy start-of-stream marker:
        self.assertEqual(parse_audio_data_packet(data_packet("opus", (), {"start-of-stream": True})).data, b"")

    def test_invalid_data(self):
        for packet in (
            Packet("audio-data", "opus", b"data"),
            Packet("audio-data", "opus", b"data", {}, (), 1),
            data_packet("x" * 65),
            data_packet(data=bytes(MAX_AUDIO_DATA + 1)),
            data_packet(metadata=[]),
            data_packet(metadata={f"key{i}": i for i in range(33)}),
            data_packet(metadata={"": 1}),
            data_packet(metadata={"sequence": "1"}),
            data_packet(metadata={"sequence": True}),
            data_packet(metadata={"time": 2**63}),
            data_packet(metadata={"compress": "zlib"}),
            data_packet(metadata={"other": "x" * 2000}),
            data_packet(metadata={"other": ((1, ), )}),
            data_packet(metadata={"other": object()}),
            data_packet("opus", b"data", {}, [b""] * 17),
            data_packet("opus", b"data", {}, [bytes(MAX_AUDIO_DATA + 1)]),
            data_packet("opus", b"data", {}, b"header"),
        ):
            with self.assertRaises((ValueError, TypeError), msg=f"{packet!r} accepted"):
                parse_audio_data_packet(packet)

    def test_stream(self):
        self.assertEqual(parse_audio_stream_packet(Packet("audio-stream", "start", "opus", 3)), ("start", "opus", 3))
        for packet in (
            Packet("audio-stream", "start", "opus"),
            Packet("audio-stream", "start", "opus", 3, 4),
            Packet("audio-stream", "x" * 17, "opus", 3),
            Packet("audio-stream", "start", "x" * 65, 3),
        ):
            with self.assertRaises(ValueError):
                parse_audio_stream_packet(packet)

    def test_control(self):
        self.assertEqual(parse_audio_control_packet(Packet("audio-control", "stop")), ("stop", []))
        self.assertEqual(parse_audio_control_packet(Packet("audio-control", "sync", 100)), ("sync", [100]))
        self.assertEqual(parse_audio_control_packet(Packet("audio-control", "start", b"opus")), ("start", ["opus"]))
        for packet in (
            Packet("audio-control", ),
            Packet("audio-control", "start", 1, 2, 3, 4, 5),
            Packet("audio-control", "x" * 33),
            Packet("audio-control", "start", "x" * 65),
            Packet("audio-control", "start", 2**64),
            Packet("audio-control", "start", True),
            Packet("audio-control", "start", ("opus", )),
        ):
            with self.assertRaises((ValueError, TypeError), msg=f"{packet!r} accepted"):
                parse_audio_control_packet(packet)

    def test_capabilities_and_keepalive(self):
        capabilities = {
            "send": True,
            "receive": False,
            "encoders": ["opus", b"mp3"],
            "keepalive.interval": 5,
            "gst.version": (1, 24, "3"),
            "python.bits": "64",
            "pulseaudio": {"found": True, "id": "audio-server"},
            "device": {"output.1": "Speakers"},
        }
        self.assertEqual(parse_audio_capabilities_packet(Packet("audio-capabilities", capabilities)), capabilities)
        self.assertEqual(parse_audio_keepalive_packet(Packet("audio-keepalive", 10)), 10)
        for fn, packet in (
            (parse_audio_capabilities_packet, Packet("audio-capabilities", {}, 1)),
            (parse_audio_capabilities_packet, Packet("audio-capabilities", {str(i): i for i in range(33)})),
            (parse_audio_capabilities_packet, Packet("audio-capabilities", "send")),
            (parse_audio_keepalive_packet, Packet("audio-keepalive", -1)),
            (parse_audio_keepalive_packet, Packet("audio-keepalive", 1, 2)),
        ):
            with self.assertRaises((ValueError, TypeError), msg=f"{packet!r} accepted"):
                fn(packet)

    def test_invalid_capabilities(self):
        invalid = (
            {"unknown": True},
            {1: True},
            {"send": 1},
            {"send": "yes"},
            {"keepalive.interval": True},
            {"keepalive.interval": -1},
            {"keepalive.interval": 2**31},
            {"python.bits": 128},
            {"pulseaudio.id": object()},
            {"pulseaudio.id": "x" * (MAX_AUDIO_CAPABILITY_STRING + 1)},
            {"encoders": "opus"},
            {"encoders": ["opus"] * (MAX_AUDIO_CAPABILITY_ITEMS + 1)},
            {"encoders": ["x" * (MAX_AUDIO_CAPABILITY_NAME + 1)]},
            {"encoders": [1]},
            {"gst.version": "1.24"},
            {"gst.version": [1] * 9},
            {"gst.version": [True]},
            {"pulseaudio": []},
            {"pulseaudio": {"unknown": True}},
            {"pulseaudio": {"found": 1}},
            {"pulseaudio": {"id": object()}},
            {"device": []},
            {"device": {str(i): "device" for i in range(MAX_AUDIO_CAPABILITY_ITEMS + 1)}},
            {"device": {"x" * (MAX_AUDIO_DEVICE_NAME + 1): "device"}},
            {"device": {"output": "x" * (MAX_AUDIO_CAPABILITY_STRING + 1)}},
            {"device": {"output": 1}},
        )
        for capabilities in invalid:
            packet = Packet("audio-capabilities", capabilities)
            with self.assertRaises((ValueError, TypeError), msg=f"{packet!r} accepted"):
                parse_audio_capabilities_packet(packet)


class AudioHandlersTest(unittest.TestCase):

    def test_server_control(self):
        from xpra.server.subsystem.audio import AudioServer
        source = MagicMock()

        class Server(AudioServer):
            def get_server_source(self, _proto):
                return source

        server = Server.__new__(Server)
        server._process_control(None, Packet("audio-control", "start", b"opus"))
        source.audio_control.assert_called_once_with("start", "opus")
        with self.assertRaises(ValueError):
            server._process_control(None, Packet("audio-control", "start", "x" * 100))
        server._process_data(None, data_packet())
        source.audio_data.assert_called_once_with("opus", b"data", {"sequence": 1}, ())
        with self.assertRaises(ValueError):
            server._process_data(None, data_packet(metadata={"compress": "zlib"}))
        self.assertEqual(source.audio_data.call_count, 1)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
