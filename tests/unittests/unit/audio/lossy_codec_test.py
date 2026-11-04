#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Connections that can send lossy datagrams (ie: QUIC) expose `datagram=True`,
and both audio subsystems use it to prefer the loss-tolerant codecs.
"""

import unittest
from unittest.mock import MagicMock, patch

from xpra.audio.common import OPUS, OPUS_RTP, VORBIS_OGG, FLAC_OGG, LOSS_TOLERANT_CODECS, get_matching_codecs
from xpra.net.bytestreams import Connection
from xpra.util.objects import AdHocStruct, typedict


def fake_conn(datagram: bool) -> AdHocStruct:
    conn = AdHocStruct()
    conn.datagram = datagram
    return conn


class TestMatchingCodecs(unittest.TestCase):

    def test_reliable_keeps_local_order(self):
        local = (OPUS, VORBIS_OGG, OPUS_RTP)
        assert get_matching_codecs(local, (OPUS_RTP, VORBIS_OGG, OPUS)) == local
        assert get_matching_codecs(local, (OPUS_RTP, VORBIS_OGG, OPUS), False) == local

    def test_lossy_prefers_loss_tolerant(self):
        local = (OPUS, VORBIS_OGG, OPUS_RTP, FLAC_OGG)
        assert get_matching_codecs(local, local, True) == (OPUS_RTP, OPUS, VORBIS_OGG, FLAC_OGG)

    def test_lossy_only_matching(self):
        # the remote end must support the loss-tolerant codec for it to be selected:
        assert get_matching_codecs((OPUS, OPUS_RTP), (OPUS, ), True) == (OPUS, )
        assert get_matching_codecs((OPUS, ), (OPUS, OPUS_RTP), True) == (OPUS, )
        assert get_matching_codecs((OPUS, OPUS_RTP), (VORBIS_OGG, ), True) == ()

    def test_loss_tolerant_codecs(self):
        assert OPUS_RTP in LOSS_TOLERANT_CODECS
        assert OPUS not in LOSS_TOLERANT_CODECS


class TestConnectionDatagram(unittest.TestCase):

    def test_default(self):
        conn = Connection(("localhost", 10000), "tcp")
        assert conn.datagram is False
        assert conn.get_info()["datagram"] is False

    def test_quic(self):
        try:
            from xpra.net.quic.connection import XpraQuicConnection
            from xpra.net.quic.webtransport import ServerWebTransportConnection
        except ImportError as e:
            raise unittest.SkipTest(f"no quic support: {e}") from None
        conn = XpraQuicConnection(MagicMock(), 0, MagicMock(), "localhost", 10000)
        assert conn.datagram is True
        assert conn.get_info()["datagram"] is True
        # webtransport connections ignore incoming datagrams:
        assert ServerWebTransportConnection(MagicMock(), {}, 0, MagicMock()).datagram is False


def make_client(datagram: bool):
    from xpra.client.subsystem.audio import AudioClient
    x = AudioClient()
    x.client = AdHocStruct()
    x.client.exit_code = None
    x.send = MagicMock()
    x.emit = MagicMock()
    x.idle_add = lambda fn, *a: fn(*a)
    x.timeout_add = MagicMock(return_value=0)
    x.speaker_codecs = [OPUS, VORBIS_OGG, OPUS_RTP]
    x.microphone_codecs = [OPUS, VORBIS_OGG, OPUS_RTP]
    x.server_send = True
    x.server_receive = True
    x.server_encoders = (OPUS_RTP, OPUS, VORBIS_OGG)
    x.server_decoders = (OPUS_RTP, OPUS, VORBIS_OGG)
    x.server_pulseaudio_server = ""
    x.server_pulseaudio_id = ""
    x.setup_connection(fake_conn(datagram))
    return x


class TestAudioClientCodec(unittest.TestCase):

    def test_no_connection(self):
        from xpra.client.subsystem.audio import AudioClient
        x = AudioClient()
        x.setup_connection(None)
        assert x.datagram is False
        assert x.get_info()["audio"]["datagram"] is False

    def speaker_codec(self, datagram: bool) -> str:
        x = make_client(datagram)
        assert x.get_info()["audio"]["datagram"] is datagram
        with (
            patch.object(x, "loop_check", return_value=True),
            patch.object(x, "start_sink", return_value=True) as start_sink,
        ):
            x.start_receiving_audio()
        start_sink.assert_called_once()
        return start_sink.call_args.args[0]

    def test_speaker_reliable(self):
        assert self.speaker_codec(False) == OPUS

    def test_speaker_datagram(self):
        assert self.speaker_codec(True) == OPUS_RTP

    def microphone_codecs(self, datagram: bool) -> tuple[str, ...]:
        x = make_client(datagram)
        x.properties = typedict({"sources": ("autoaudiosrc", )})
        with patch("xpra.audio.wrapper.start_sending_audio", return_value=None) as start:
            assert x.start_source() is False
        start.assert_called_once()
        return tuple(start.call_args.args[6])

    def test_microphone_reliable(self):
        assert self.microphone_codecs(False) == (OPUS, VORBIS_OGG, OPUS_RTP)

    def test_microphone_datagram(self):
        assert self.microphone_codecs(True) == (OPUS_RTP, OPUS, VORBIS_OGG)


def make_source(datagram: bool):
    from xpra.server.source.audio import AudioConnection
    cc = AudioConnection()
    cc.init_state()
    audio = AdHocStruct()
    audio.properties = typedict({"sources": ("autoaudiosrc", )})
    audio.source_plugin = ""
    audio.supports_speaker = True
    audio.supports_microphone = True
    audio.speaker_codecs = [OPUS, VORBIS_OGG, OPUS_RTP]
    audio.microphone_codecs = [OPUS, VORBIS_OGG, OPUS_RTP]
    audio.connect = MagicMock()
    server = AdHocStruct()
    server.subsystems = {"audio": audio}
    protocol = AdHocStruct()
    protocol._conn = fake_conn(datagram)
    cc.init_from(protocol, server)
    cc.audio_receive = True
    # the client's decoders, in its order of preference:
    cc.audio_decoders = (OPUS, VORBIS_OGG, OPUS_RTP)
    return cc


class TestAudioConnectionCodec(unittest.TestCase):

    def speaker_codec(self, datagram: bool, codec="") -> str:
        cc = make_source(datagram)
        assert cc.get_info()["audio"]["datagram"] is datagram
        with (
            patch.object(cc, "audio_loop_check", return_value=True),
            patch("xpra.audio.wrapper.start_sending_audio", return_value=None) as start,
        ):
            cc.start_sending_audio(codec)
        start.assert_called_once()
        return start.call_args.args[3]

    def test_reliable(self):
        assert self.speaker_codec(False) == OPUS

    def test_datagram(self):
        assert self.speaker_codec(True) == OPUS_RTP

    def test_datagram_explicit_codec(self):
        # the codec chosen by the client is always honoured:
        assert self.speaker_codec(True, VORBIS_OGG) == VORBIS_OGG


def main():
    unittest.main()


if __name__ == '__main__':
    main()
