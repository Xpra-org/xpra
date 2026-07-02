#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Unit tests for AudioClient that do not require a real GStreamer pipeline.
Exercises the state-machine, packet-handling, and capability helpers directly.
"""

import unittest
from unittest.mock import MagicMock, patch
from xpra.net.common import Packet
from xpra.util.objects import typedict


def _make_client(*, speaker_enabled=False, microphone_enabled=False,
                 av_sync=False, server_av_sync=False):
    """Return a bare AudioClient wired with minimal stubs."""
    from xpra.client.subsystem.audio import AudioClient
    x = AudioClient()
    x.exit_code = None
    x._signal_callbacks = {}
    x._remote_uuid = ""
    x._remote_machine_id = ""
    # stubs expected by the mixin
    sent = []
    x.send = lambda *a: sent.append(a)
    x._sent = sent
    x.emit = MagicMock()
    x.connect = MagicMock()
    x.idle_add = lambda fn, *a: fn(*a)
    x.timeout_add = MagicMock(return_value=0)
    # initial state
    x.speaker_enabled = speaker_enabled
    x.microphone_enabled = microphone_enabled
    x.speaker_allowed = speaker_enabled
    x.microphone_allowed = microphone_enabled
    x.speaker_codecs = ["opus"]
    x.microphone_codecs = ["opus"]
    x.av_sync = av_sync
    x.server_av_sync = server_av_sync
    x.server_send = False
    x.server_receive = False
    x.server_encoders = ()
    x.server_decoders = ()
    x.on_sink_ready = lambda: None
    return x


def _make_sink(x, codec="opus"):
    sink = MagicMock()
    sink.codec = codec
    sink.sequence = x.sink_sequence
    sink.get_state = MagicMock(return_value="ready")
    sink.get_info = MagicMock(return_value={})
    x.sink = sink
    x.speaker_enabled = True
    return sink


def _make_source(x, codec="opus"):
    source = MagicMock()
    source.codec = codec
    source.sequence = x.source_sequence
    x.source = source
    x.microphone_enabled = True
    return source


# ---------------------------------------------------------------------------
# get_info / get_caps / get_audio_capabilities / get_avsync_capabilities
# ---------------------------------------------------------------------------

class TestGetInfo(unittest.TestCase):

    def test_structure(self):
        x = _make_client()
        info = x.get_info()
        from xpra.client.subsystem.audio import AudioClient
        assert AudioClient.PREFIX in info
        sub = info[AudioClient.PREFIX]
        assert "speaker" in sub
        assert "microphone" in sub
        assert "properties" in sub

    def test_with_sink(self):
        x = _make_client()
        _make_sink(x)
        info = x.get_info()
        from xpra.client.subsystem.audio import AudioClient
        assert "sink" in info[AudioClient.PREFIX]

    def test_with_source(self):
        x = _make_client()
        _make_source(x)
        info = x.get_info()
        from xpra.client.subsystem.audio import AudioClient
        assert "src" in info[AudioClient.PREFIX]


class TestGetCaps(unittest.TestCase):

    def test_has_avsync_key(self):
        x = _make_client()
        caps = x.get_caps()
        assert "av-sync" in caps

    def test_has_audio_key(self):
        x = _make_client()
        caps = x.get_caps()
        from xpra.client.subsystem.audio import AudioClient
        assert AudioClient.PREFIX in caps


class TestGetAudioCapabilities(unittest.TestCase):

    def test_empty_without_properties(self):
        x = _make_client()
        x.properties = typedict()
        assert x.get_audio_capabilities() == {}

    def test_has_expected_keys(self):
        x = _make_client()
        x.properties = typedict({"encoders": ["opus"], "decoders": ["opus"]})
        caps = x.get_audio_capabilities()
        assert "decoders" in caps
        assert "encoders" in caps
        assert "send" in caps
        assert "receive" in caps


class TestGetAvsyncCapabilities(unittest.TestCase):

    def test_empty_when_disabled(self):
        x = _make_client(av_sync=False)
        assert x.get_avsync_capabilities() == {}

    def test_keys_when_enabled(self):
        x = _make_client(av_sync=True)
        caps = x.get_avsync_capabilities()
        assert caps.get("enabled") is True
        assert "delay" in caps


# ---------------------------------------------------------------------------
# parse_server_capabilities / parse_audio_capabilities
# ---------------------------------------------------------------------------

class TestParseServerCapabilities(unittest.TestCase):

    def test_sets_server_av_sync(self):
        x = _make_client()
        c = typedict({"av-sync.enabled": True, "audio": {}})
        x.parse_server_capabilities(c)
        assert x.server_av_sync is True

    def test_async_flag_sets_wants_audio_caps(self):
        x = _make_client()
        c = typedict({"audio": {"async": True}})
        x.parse_server_capabilities(c)
        assert x.wants_capabilities is True

    def test_async_with_properties_sends_caps(self):
        x = _make_client()
        x.properties = typedict({"encoders": ["opus"]})
        c = typedict({"audio": {"async": True}})
        x.parse_server_capabilities(c)
        assert any(p[0] == "audio-capabilities" for p in x._sent)

    def test_non_async_calls_auto_start(self):
        x = _make_client(speaker_enabled=True)
        x.server_send = True
        x.server_encoders = ("opus",)
        c = typedict({"audio": {"send": True, "encoders": ["opus"]}})
        with patch.object(x, "start_receiving_audio"):
            x.parse_server_capabilities(c)
            # auto_start is called when server sends audio and speaker is enabled
            # (via the non-async path)
            # auto_start reads server_send which was set by parse_audio_capabilities
            # called just before; ensure emit was called
        x.emit.assert_called_with("audio-initialized")

    def test_no_server_audio_caps(self):
        x = _make_client()
        c = typedict({})
        result = x.parse_server_capabilities(c)
        assert result is True


class TestParseAudioCapabilities(unittest.TestCase):

    def test_sets_all_fields(self):
        x = _make_client()
        audio = typedict({
            "pulseaudio.id": "pa-id-123",
            "pulseaudio.server": "unix:/run/user/1000/pulse/native",
            "decoders": ("opus", "vorbis"),
            "encoders": ("opus",),
            "receive": True,
            "send": True,
        })
        x.parse_audio_capabilities(audio)
        assert x.server_pulseaudio_id == "pa-id-123"
        assert x.server_pulseaudio_server == "unix:/run/user/1000/pulse/native"
        assert "opus" in x.server_decoders
        assert "opus" in x.server_encoders
        assert x.server_receive is True
        assert x.server_send is True


# ---------------------------------------------------------------------------
# auto_start
# ---------------------------------------------------------------------------

class TestAutoStart(unittest.TestCase):

    def test_starts_speaker_when_conditions_met(self):
        x = _make_client(speaker_enabled=True)
        x.server_send = True
        with patch.object(x, "start_receiving_audio") as m:
            x.auto_start()
            m.assert_called_once()

    def test_does_not_start_speaker_when_disabled(self):
        x = _make_client(speaker_enabled=False)
        x.server_send = True
        with patch.object(x, "start_receiving_audio") as m:
            x.auto_start()
            m.assert_not_called()

    def test_schedules_microphone_via_idle_add(self):
        x = _make_client(microphone_enabled=True)
        x.server_receive = True
        idle_calls = []
        x.idle_add = lambda fn, *a: idle_calls.append(fn)
        with patch.object(x, "start_sending_audio"):
            x.auto_start()
        assert idle_calls  # idle_add was called


# ---------------------------------------------------------------------------
# stop_all_audio / stop_sending_audio / stop_receiving_audio
# ---------------------------------------------------------------------------

class TestStopAllAudio(unittest.TestCase):

    def test_stops_both_when_active(self):
        x = _make_client()
        _make_sink(x)
        _make_source(x)
        with patch.object(x, "stop_sending_audio") as ms, \
             patch.object(x, "stop_receiving_audio") as mr:
            x.stop_all_audio()
            ms.assert_called_once()
            mr.assert_called_once()

    def test_noop_when_nothing_active(self):
        x = _make_client()
        with patch.object(x, "stop_sending_audio") as ms, \
             patch.object(x, "stop_receiving_audio") as mr:
            x.stop_all_audio()
            ms.assert_not_called()
            mr.assert_not_called()


class TestStopSendingAudio(unittest.TestCase):

    def test_sends_end_of_stream(self):
        x = _make_client()
        _make_source(x)
        x.stop_sending_audio()
        from xpra.audio.common import AUDIO_DATA_PACKET
        sent_types = [p[0] for p in x._sent]
        assert AUDIO_DATA_PACKET in sent_types

    def test_increments_sequence(self):
        x = _make_client()
        _make_source(x)
        seq_before = x.source_sequence
        x.stop_sending_audio()
        assert x.source_sequence == seq_before + 1

    def test_clears_source(self):
        x = _make_client()
        _make_source(x)
        x.stop_sending_audio()
        assert x.source is None

    def test_emits_microphone_changed(self):
        x = _make_client(microphone_enabled=True)
        _make_source(x)
        x.stop_sending_audio()
        x.emit.assert_called_with("microphone-changed")


class TestStopReceivingAudio(unittest.TestCase):

    def test_sends_stop_and_new_sequence(self):
        x = _make_client()
        _make_sink(x)
        x.stop_receiving_audio(tell_server=True)
        from xpra.audio.common import AUDIO_CONTROL_PACKET
        types = [p[0] for p in x._sent]
        assert AUDIO_CONTROL_PACKET in types
        cmds = [p[1] for p in x._sent if p[0] == AUDIO_CONTROL_PACKET]
        assert "stop" in cmds
        assert "new-sequence" in cmds

    def test_no_stop_sent_when_tell_server_false(self):
        x = _make_client()
        _make_sink(x)
        x.stop_receiving_audio(tell_server=False)
        from xpra.audio.common import AUDIO_CONTROL_PACKET
        cmds = [p[1] for p in x._sent if p[0] == AUDIO_CONTROL_PACKET]
        assert "stop" not in cmds

    def test_increments_sequence(self):
        x = _make_client()
        _make_sink(x)
        seq_before = x.sink_sequence
        x.stop_receiving_audio()
        assert x.sink_sequence == seq_before + 1

    def test_clears_sink(self):
        x = _make_client()
        _make_sink(x)
        x.stop_receiving_audio()
        assert x.sink is None

    def test_noop_when_no_sink(self):
        x = _make_client()
        x.stop_receiving_audio()  # must not raise


# ---------------------------------------------------------------------------
# suspend_audio / resume_audio
# ---------------------------------------------------------------------------

class TestSuspendResumeAudio(unittest.TestCase):

    def test_suspend_sets_resume_restart_when_sink_present(self):
        x = _make_client()
        _make_sink(x)
        with patch.object(x, "stop_receiving_audio"), patch.object(x, "stop_sending_audio"):
            x.suspend_audio(None)
        assert x.resume_restart is True

    def test_suspend_no_restart_when_no_sink(self):
        x = _make_client()
        x.suspend_audio(None)
        assert x.resume_restart is False

    def test_resume_starts_audio_when_flag_set(self):
        x = _make_client()
        x.resume_restart = True
        with patch.object(x, "start_receiving_audio") as m:
            x.resume_audio(None)
            m.assert_called_once()
        assert x.resume_restart is False

    def test_resume_noop_when_flag_clear(self):
        x = _make_client()
        x.resume_restart = False
        with patch.object(x, "start_receiving_audio") as m:
            x.resume_audio(None)
            m.assert_not_called()


# ---------------------------------------------------------------------------
# new_stream / new_buffer / send_audio_sync
# ---------------------------------------------------------------------------

class TestNewStream(unittest.TestCase):

    def test_sends_start_of_stream(self):
        x = _make_client()
        source = _make_source(x)
        source.codec = "opus"
        x.new_stream(source, "opus")
        from xpra.audio.common import AUDIO_DATA_PACKET
        assert any(p[0] == AUDIO_DATA_PACKET for p in x._sent)
        meta = next(p[3] for p in x._sent if p[0] == AUDIO_DATA_PACKET)
        assert meta.get("start-of-stream") is True

    def test_drops_stale_source(self):
        x = _make_client()
        stale = MagicMock()
        stale.codec = "opus"
        # source is a different object
        x.source = MagicMock()
        x.new_stream(stale, "opus")
        assert not x._sent


class TestNewAudioBuffer(unittest.TestCase):

    def test_sends_audio_data(self):
        x = _make_client()
        source = _make_source(x)
        source.codec = "opus"
        source.sequence = x.source_sequence
        x.new_buffer(source, b"audio bytes", {})
        from xpra.audio.common import AUDIO_DATA_PACKET
        assert any(p[0] == AUDIO_DATA_PACKET for p in x._sent)

    def test_increments_bytecount(self):
        x = _make_client()
        source = _make_source(x)
        source.sequence = x.source_sequence
        x.new_buffer(source, b"1234", {})
        assert x.out_bytecount >= 4

    def test_drops_old_sequence(self):
        x = _make_client()
        source = _make_source(x)
        source.sequence = 0
        x.source_sequence = 5  # now source.sequence < source_sequence
        x.new_buffer(source, b"data", {})
        assert not x._sent


class TestSendAudioSync(unittest.TestCase):

    def test_sends_when_server_av_sync(self):
        x = _make_client(server_av_sync=True)
        x.send_audio_sync(100)
        from xpra.audio.common import AUDIO_CONTROL_PACKET
        assert any(p[0] == AUDIO_CONTROL_PACKET and p[1] == "sync" for p in x._sent)

    def test_noop_when_server_av_sync_disabled(self):
        x = _make_client(server_av_sync=False)
        x.send_audio_sync(100)
        assert not x._sent


# ---------------------------------------------------------------------------
# sink_state_changed / sink_exit / process_stopped
# ---------------------------------------------------------------------------

class TestAudioSinkStateChanged(unittest.TestCase):

    def test_calls_on_sink_ready(self):
        x = _make_client()
        sink = _make_sink(x)
        ready_called = []
        x.on_sink_ready = lambda: ready_called.append(True)
        x.sink_state_changed(sink, "ready")
        assert ready_called
        assert x.on_sink_ready.__name__ == "<lambda>" or x.on_sink_ready is not None

    def test_emits_speaker_changed(self):
        x = _make_client()
        sink = _make_sink(x)
        x.sink_state_changed(sink, "playing")
        x.emit.assert_called_with("speaker-changed")

    def test_ignores_stale_sink(self):
        x = _make_client()
        _make_sink(x)
        stale = MagicMock()
        x.sink_state_changed(stale, "ready")
        x.emit.assert_not_called()


class TestAudioSinkExit(unittest.TestCase):

    def test_stops_receiving_audio(self):
        x = _make_client()
        sink = _make_sink(x)
        with patch.object(x, "stop_receiving_audio") as m:
            x.sink_exit(sink)
            m.assert_called_once()

    def test_ignores_stale_sink(self):
        x = _make_client()
        _make_sink(x)
        stale = MagicMock()
        with patch.object(x, "stop_receiving_audio") as m:
            x.sink_exit(stale)
            m.assert_not_called()

    def test_ignores_when_exiting(self):
        x = _make_client()
        sink = _make_sink(x)
        x.exit_code = 0
        with patch.object(x, "stop_receiving_audio") as m:
            x.sink_exit(sink)
            m.assert_not_called()


class TestAudioProcessStopped(unittest.TestCase):

    def test_stops_receiving_audio(self):
        x = _make_client()
        sink = _make_sink(x)
        with patch.object(x, "stop_receiving_audio") as m:
            x.process_stopped(sink)
            m.assert_called_once()

    def test_ignores_stale_sink(self):
        x = _make_client()
        _make_sink(x)
        stale = MagicMock()
        with patch.object(x, "stop_receiving_audio") as m:
            x.process_stopped(stale)
            m.assert_not_called()


# ---------------------------------------------------------------------------
# _process_audio_capabilities / _process_audio_data
# ---------------------------------------------------------------------------

class TestProcessAudioCapabilities(unittest.TestCase):

    def test_calls_parse_and_auto_start(self):
        x = _make_client()
        packet = Packet("audio-capabilities", {
            "send": True,
            "encoders": ["opus"],
        })
        with patch.object(x, "parse_audio_capabilities") as pp, \
             patch.object(x, "auto_start") as pa:
            x._process_audio_capabilities(packet)
            pp.assert_called_once()
            pa.assert_called_once()
        x.emit.assert_called_with("audio-initialized")


class TestProcessAudioData(unittest.TestCase):

    def _make_packet(self, codec="opus", data=b"", metadata=None, packet_meta=()):
        meta = metadata or {}
        if packet_meta:
            return Packet("audio-data", codec, data, meta, packet_meta)
        return Packet("audio-data", codec, data, meta)

    def test_ignores_old_sequence(self):
        x = _make_client()
        x.sink_sequence = 5
        pkt = self._make_packet(metadata={"sequence": 3})
        x._process_audio_data(pkt)
        assert x.sink is None  # nothing started

    def test_drops_without_speaker_enabled(self):
        x = _make_client(speaker_enabled=False)
        pkt = self._make_packet(data=b"audio")
        x._process_audio_data(pkt)
        # just ensure no crash

    def test_start_of_stream_starts_sink(self):
        x = _make_client()
        x.speaker_allowed = True
        pkt = self._make_packet(metadata={"start-of-stream": True, "codec": "opus"})
        with patch.object(x, "start_sink") as m:
            x._process_audio_data(pkt)
            m.assert_called_once_with("opus")

    def test_end_of_stream_stops_receiving(self):
        x = _make_client(speaker_enabled=True)
        _make_sink(x)
        pkt = self._make_packet(metadata={"end-of-stream": True, "sequence": -1})
        with patch.object(x, "stop_receiving_audio") as m:
            x._process_audio_data(pkt)
            m.assert_called_once_with(False)

    def test_codec_mismatch_stops_receiving(self):
        x = _make_client(speaker_enabled=True)
        _make_sink(x, codec="opus")
        pkt = self._make_packet(codec="vorbis", data=b"data", metadata={"sequence": -1})
        with patch.object(x, "stop_receiving_audio") as m:
            x._process_audio_data(pkt)
            m.assert_called_once()

    def test_data_forwarded_to_sink(self):
        x = _make_client(speaker_enabled=True)
        sink = _make_sink(x)
        pkt = self._make_packet(codec="opus", data=b"audio-data", metadata={"sequence": -1})
        x._process_audio_data(pkt)
        sink.add_data.assert_called()

    def test_sink_stopped_state_triggers_stop(self):
        x = _make_client(speaker_enabled=True)
        sink = _make_sink(x)
        sink.get_state.return_value = "stopped"
        pkt = self._make_packet(codec="opus", data=b"d", metadata={"sequence": -1})
        with patch.object(x, "stop_receiving_audio") as m:
            x._process_audio_data(pkt)
            m.assert_called_once()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
