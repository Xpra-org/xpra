#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The start and end of an audio stream are marked using `audio-stream` packets,
older peers use `audio-data` packets without any data and with metadata flags instead.
"""

import unittest
from unittest.mock import patch, MagicMock

from xpra.audio import common
from xpra.audio.common import AUDIO_STREAM_START, AUDIO_STREAM_END, audio_stream_packet
from xpra.net.packet_type import AUDIO_DATA, AUDIO_STREAM
from xpra.net.common import Packet
from xpra.util.objects import typedict
from xpra.server.source.audio import AudioConnection

from unit.client.subsystem.audio_client_unit_test import _make_client, _make_sink, _make_source


def legacy(fn):
    """ enable the legacy `audio-data` start and end of stream markers """
    for module in ("xpra.audio.common", "xpra.client.subsystem.audio", "xpra.server.source.audio"):
        fn = patch(f"{module}.BACKWARDS_COMPATIBLE", True)(fn)
    return fn


class TestAudioStreamPacket(unittest.TestCase):

    def test_stream_packet(self):
        assert audio_stream_packet(True, AUDIO_STREAM_START, "opus", 3) == (AUDIO_STREAM, "start", "opus", 3)
        assert audio_stream_packet(True, AUDIO_STREAM_END, "opus", 3) == (AUDIO_STREAM, "end", "opus", 3)

    @legacy
    def test_legacy_packet(self):
        assert audio_stream_packet(False, AUDIO_STREAM_START, "opus", 3) == (
            AUDIO_DATA, "opus", (), {"start-of-stream": True, "codec": "opus", "sequence": 3},
        )
        assert audio_stream_packet(False, AUDIO_STREAM_END, "opus", 3) == (
            AUDIO_DATA, "opus", (), {"end-of-stream": True, "sequence": 3},
        )

    def test_not_backwards_compatible(self):
        with patch.object(common, "BACKWARDS_COMPATIBLE", False):
            assert audio_stream_packet(False, AUDIO_STREAM_START, "opus", 3)[0] == AUDIO_STREAM


class TestClientSend(unittest.TestCase):

    def test_capability(self):
        x = _make_client()
        x.properties = {"encoders": ["opus"]}
        assert x.get_audio_capabilities().get("stream-packet") is True

    def test_new_stream(self):
        x = _make_client()
        x.server_stream_packet = True
        source = _make_source(x)
        source.sequence = 2
        x.new_stream(source, "opus")
        assert x._sent == [(AUDIO_STREAM, AUDIO_STREAM_START, "opus", 2)]

    def test_stop_sending(self):
        x = _make_client()
        x.server_stream_packet = True
        source = _make_source(x)
        source.sequence = 2
        x.stop_sending_audio()
        assert (AUDIO_STREAM, AUDIO_STREAM_END, "opus", 2) in x._sent

    @legacy
    def test_legacy_new_stream(self):
        x = _make_client()
        source = _make_source(x)
        x.new_stream(source, "opus")
        assert len(x._sent) == 1
        packet = x._sent[0]
        assert packet[0] == AUDIO_DATA
        assert packet[3].get("start-of-stream") is True


class TestClientReceive(unittest.TestCase):

    def test_start(self):
        x = _make_client()
        x.speaker_allowed = True
        with patch.object(x, "start_sink") as start_sink:
            x._process_stream(Packet(AUDIO_STREAM, AUDIO_STREAM_START, "opus", 0))
        start_sink.assert_called_once_with("opus")
        assert x.speaker_enabled

    def test_start_not_allowed(self):
        x = _make_client()
        x.speaker_allowed = False
        with patch.object(x, "start_sink") as start_sink, patch.object(x, "stop_receiving_audio") as stop:
            x._process_stream(Packet(AUDIO_STREAM, AUDIO_STREAM_START, "opus", 0))
        start_sink.assert_not_called()
        stop.assert_called_once_with(True)

    def test_start_already_enabled(self):
        x = _make_client(speaker_enabled=True)
        _make_sink(x)
        with patch.object(x, "start_sink") as start_sink:
            x._process_stream(Packet(AUDIO_STREAM, AUDIO_STREAM_START, "opus", 0))
        start_sink.assert_not_called()

    def test_end(self):
        x = _make_client(speaker_enabled=True)
        _make_sink(x)
        with patch.object(x, "stop_receiving_audio") as stop:
            x._process_stream(Packet(AUDIO_STREAM, AUDIO_STREAM_END, "opus", 0))
        stop.assert_called_once_with(False)

    def test_end_old_sequence(self):
        x = _make_client(speaker_enabled=True)
        _make_sink(x)
        x.sink_sequence = 5
        with patch.object(x, "stop_receiving_audio") as stop:
            x._process_stream(Packet(AUDIO_STREAM, AUDIO_STREAM_END, "opus", 3))
        stop.assert_not_called()

    def test_unknown_event(self):
        x = _make_client(speaker_enabled=True)
        _make_sink(x)
        with patch.object(x, "stop_receiving_audio") as stop, patch.object(x, "start_sink") as start_sink:
            x._process_stream(Packet(AUDIO_STREAM, "pause", "opus", 0))
        stop.assert_not_called()
        start_sink.assert_not_called()

    def test_legacy_flags_ignored_when_not_backwards_compatible(self):
        from xpra.client.subsystem import audio as client_audio
        x = _make_client(speaker_enabled=True)
        sink = _make_sink(x)
        with patch.object(client_audio, "BACKWARDS_COMPATIBLE", False), \
                patch.object(x, "stop_receiving_audio") as stop:
            x._process_data(Packet(AUDIO_DATA, "opus", b"", {"end-of-stream": True, "sequence": -1}))
        stop.assert_not_called()
        sink.add_data.assert_not_called()


class FakeConnection(AudioConnection):
    def __init__(self):
        self.init_state()
        self.sent = []
        self.supports_speaker = True
        self.speaker_codecs = ["opus"]
        self.supports_microphone = True
        self.microphone_codecs = ["opus"]
        self.audio_properties = {}

    def send(self, *args, **_kwargs):
        self.sent.append(args)

    send_more = send

    def is_closed(self) -> bool:
        return False


class TestServerSource(unittest.TestCase):

    def test_capability(self):
        c = FakeConnection()
        assert c.get_audio_caps().get("stream-packet") is True
        c.parse_audio_caps(typedict({"stream-packet": True}))
        assert c.audio_stream_packet

    def test_send_eos(self):
        c = FakeConnection()
        c.audio_stream_packet = True
        c.send_eos("opus", 4)
        assert c.sent == [(AUDIO_STREAM, AUDIO_STREAM_END, "opus", 4)]

    @legacy
    def test_legacy_send_eos(self):
        c = FakeConnection()
        c.send_eos("opus", 4)
        assert c.sent == [(AUDIO_DATA, "opus", (), {"end-of-stream": True, "sequence": 4})]

    def test_new_stream(self):
        c = FakeConnection()
        c.audio_stream_packet = True
        source = MagicMock()
        source.codec = "opus"
        source.sequence = 1
        c.audio_source = source
        with patch.object(c, "new_stream_sound"), patch.object(c, "call_update_av_sync_delay"), \
                patch("xpra.server.source.audio.GLib"):
            c.new_stream(source, "opus")
        assert c.sent == [(AUDIO_STREAM, AUDIO_STREAM_START, "opus", 1)]

    def test_receive_start(self):
        c = FakeConnection()
        with patch.object(c, "ensure_audio_sink") as ensure:
            c.audio_stream(AUDIO_STREAM_START, "opus", 0)
        ensure.assert_called_once_with("opus")

    def test_receive_end(self):
        c = FakeConnection()
        with patch.object(c, "stop_receiving_audio") as stop:
            c.audio_stream(AUDIO_STREAM_END, "opus", 0)
        stop.assert_called_once()

    @legacy
    def test_receive_legacy(self):
        c = FakeConnection()
        with patch.object(c, "ensure_audio_sink") as ensure, patch.object(c, "stop_receiving_audio") as stop:
            c.audio_data("opus", b"", {"start-of-stream": True, "codec": "opus"})
            ensure.assert_called_once_with("opus")
            c.audio_data("opus", b"", {"end-of-stream": True, "sequence": 0})
            stop.assert_called_once()

    def test_no_data(self):
        c = FakeConnection()
        sink = MagicMock()
        sink.codec = "opus"
        c.audio_sink = sink
        c.audio_data("opus", b"", {"sequence": 0})
        sink.add_data.assert_not_called()

    def test_data_forwarded_to_sink(self):
        c = FakeConnection()
        sink = MagicMock()
        sink.codec = "opus"
        c.audio_sink = sink
        c.audio_data("opus", b"data", {"sequence": 0})
        sink.add_data.assert_called_once_with(b"data", {"sequence": 0}, ())


class TestServerSinkCreation(unittest.TestCase):
    """
    With clients that send `audio-stream` packets, only those create the sink:
    `audio-data` may arrive as a datagram, in the asyncio loop thread, which must not start a subprocess.
    """

    def test_data_does_not_create_sink(self):
        c = FakeConnection()
        c.audio_stream_packet = True
        with patch.object(c, "ensure_audio_sink") as ensure:
            c.audio_data("opus", b"data", {"sequence": 0})
        ensure.assert_not_called()
        assert c.audio_sink is None
        # held until the stream starts:
        assert len(c.pending_audio.items) == 1

    def test_data_fed_to_existing_sink(self):
        c = FakeConnection()
        c.audio_stream_packet = True
        sink = MagicMock()
        sink.codec = "opus"
        c.audio_sink = sink
        with patch.object(c, "ensure_audio_sink") as ensure:
            c.audio_data("opus", b"data", {"sequence": 0})
        ensure.assert_not_called()
        sink.add_data.assert_called_once_with(b"data", {"sequence": 0}, ())

    def test_codec_mismatch_dropped(self):
        c = FakeConnection()
        c.audio_stream_packet = True
        sink = MagicMock()
        sink.codec = "opus"
        c.audio_sink = sink
        with patch.object(c, "ensure_audio_sink") as ensure:
            c.audio_data("vorbis", b"data", {"sequence": 0})
        ensure.assert_not_called()
        sink.add_data.assert_not_called()
        sink.cleanup.assert_not_called()
        assert c.audio_sink is sink

    def test_stream_start_creates_sink(self):
        c = FakeConnection()
        c.audio_stream_packet = True
        with patch.object(c, "ensure_audio_sink") as ensure:
            c.audio_stream(AUDIO_STREAM_START, "opus", 0)
        ensure.assert_called_once_with("opus")

    def test_legacy_client_creates_sink_from_data(self):
        c = FakeConnection()
        with patch.object(c, "ensure_audio_sink", return_value=False) as ensure:
            c.audio_data("opus", b"data", {"sequence": 0})
        ensure.assert_called_once_with("opus")


class TestPendingAudio(unittest.TestCase):

    def test_held_until_start(self):
        from xpra.audio.common import PendingAudio
        pending = PendingAudio(200, 10)
        assert pending.add(1) and pending.add(2)
        assert pending.start() == [1, 2]
        # once started, the items must be processed straight away:
        assert not pending.add(3)
        assert pending.start() == []
        pending.stop()
        assert pending.add(4)

    def test_expired(self):
        from xpra.audio import common
        pending = common.PendingAudio(200, 10)
        with patch.object(common, "monotonic", return_value=10.0):
            pending.add("old")
        with patch.object(common, "monotonic", return_value=10.15):
            pending.add("recent")
        with patch.object(common, "monotonic", return_value=10.3):
            assert pending.start() == ["recent"]
        assert pending.dropped == 1

    def test_max_items(self):
        from xpra.audio.common import PendingAudio
        pending = PendingAudio(200, 3)
        for i in range(5):
            pending.add(i)
        assert pending.start() == [2, 3, 4]
        assert pending.dropped == 2

    def test_stop_drops(self):
        from xpra.audio.common import PendingAudio
        pending = PendingAudio(200, 10)
        pending.add(1)
        pending.stop()
        assert pending.start() == []
        assert pending.dropped == 1


class TestEarlyData(unittest.TestCase):
    """ `audio-data` received as datagrams can overtake the `audio-stream` start packet """

    def test_client_replays_early_data(self):
        x = _make_client()
        x.speaker_allowed = True
        x.server_stream_packet = True
        early = [Packet(AUDIO_DATA, "opus", b"data%i" % i, {"sequence": 0}) for i in range(3)]
        for packet in early:
            x._process_data(packet)
        sink = MagicMock()
        sink.codec = "opus"
        sink.get_state.return_value = "running"

        def start_sink(_codec) -> bool:
            x.sink = sink
            return True

        with patch.object(x, "start_sink", side_effect=start_sink):
            x._process_stream(Packet(AUDIO_STREAM, AUDIO_STREAM_START, "opus", 0))
        assert [c.args[0] for c in sink.add_data.call_args_list] == [b"data0", b"data1", b"data2"]
        # later packets go straight to the sink:
        x._process_data(Packet(AUDIO_DATA, "opus", b"later", {"sequence": 0}))
        assert sink.add_data.call_args_list[-1].args[0] == b"later"

    def test_client_without_stream_packet(self):
        # older servers send the legacy start of stream, never overtaken by datagrams
        x = _make_client()
        x._process_data(Packet(AUDIO_DATA, "opus", b"data", {"sequence": 0}))
        assert not x.pending_audio.items

    def test_client_stop_drops_early_data(self):
        x = _make_client()
        x.server_stream_packet = True
        x._process_data(Packet(AUDIO_DATA, "opus", b"data", {"sequence": 0}))
        x.stop_receiving_audio(False)
        assert not x.pending_audio.items

    def test_server_replays_early_data(self):
        c = FakeConnection()
        c.audio_stream_packet = True
        for i in range(3):
            c.audio_data("opus", b"data%i" % i, {"sequence": 0})
        sink = MagicMock()
        sink.codec = "opus"

        def ensure(_codec) -> bool:
            c.audio_sink = sink
            return True

        with patch.object(c, "ensure_audio_sink", side_effect=ensure):
            c.audio_stream(AUDIO_STREAM_START, "opus", 0)
        assert [call.args[0] for call in sink.add_data.call_args_list] == [b"data0", b"data1", b"data2"]
        c.audio_data("opus", b"later", {"sequence": 0})
        assert sink.add_data.call_args_list[-1].args[0] == b"later"

    def test_server_stop_drops_early_data(self):
        c = FakeConnection()
        c.audio_stream_packet = True
        c.audio_data("opus", b"data", {"sequence": 0})
        c.audio_stream(AUDIO_STREAM_END, "opus", 0)
        assert not c.pending_audio.items


class TestServerSubsystem(unittest.TestCase):

    def test_process_stream(self):
        from xpra.server.subsystem.audio import AudioServer
        server = AudioServer.__new__(AudioServer)
        ss = MagicMock()
        server.server = MagicMock()
        server.server.get_server_source.return_value = ss
        server._process_stream(None, Packet(AUDIO_STREAM, AUDIO_STREAM_END, "opus", 7))
        ss.audio_stream.assert_called_once_with(AUDIO_STREAM_END, "opus", 7)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
