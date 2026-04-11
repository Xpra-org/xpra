#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# ABOUTME: Tests for QUIC stream prioritization — verifies that _prioritize_streams
# ABOUTME: reorders aioquic's internal stream dict to send realtime data first.

import unittest
from unittest.mock import MagicMock, PropertyMock


class FakeQuicStream:
    """Minimal stand-in for aioquic QuicStream."""
    def __init__(self, stream_id):
        self.stream_id = stream_id


class TestPrioritizeStreams(unittest.TestCase):
    """Test that _prioritize_streams reorders the aioquic stream dict correctly."""

    def _make_connection(self, stream_ids_in_order):
        """Create an XpraQuicConnection with a fake _quic._streams dict."""
        from xpra.net.quic.connection import XpraQuicConnection
        conn = object.__new__(XpraQuicConnection)
        # minimal init for the fields _prioritize_streams touches
        conn.stream_id = 0  # main WebSocket stream
        conn._packet_type_streams = {}
        conn._substream_ids = set()
        # fake the aioquic connection with a _streams dict
        mock_h3 = MagicMock()
        mock_quic = MagicMock()
        mock_quic._streams = {sid: FakeQuicStream(sid) for sid in stream_ids_in_order}
        mock_h3._quic = mock_quic
        conn.connection = mock_h3
        return conn, mock_quic._streams

    def test_no_substreams(self):
        """With no substreams allocated, order stays unchanged."""
        conn, streams = self._make_connection([0, 2, 6])
        conn._prioritize_streams()
        self.assertEqual(list(streams.keys()), [0, 2, 6])

    def test_sound_before_draw(self):
        """Sound substream sorts before draw substream."""
        # simulate: main=0, draw=4, sound=8 (draw allocated before sound)
        conn, streams = self._make_connection([0, 2, 4, 8])
        conn._substream_ids = {4, 8}
        conn._packet_type_streams = {"draw": 4, "sound": 8}
        conn._prioritize_streams()
        order = list(streams.keys())
        sound_idx = order.index(8)
        draw_idx = order.index(4)
        self.assertLess(sound_idx, draw_idx,
                        f"sound (stream 8) should come before draw (stream 4), got {order}")

    def test_main_stream_first(self):
        """Main/control streams always come before substreams."""
        conn, streams = self._make_connection([0, 2, 4, 8])
        conn._substream_ids = {4, 8}
        conn._packet_type_streams = {"sound": 4, "draw": 8}
        conn._prioritize_streams()
        order = list(streams.keys())
        # main stream (0) and H3 control (2) should be first
        self.assertEqual(order[0], 0)
        self.assertEqual(order[1], 2)

    def test_input_before_sound(self):
        """Client-side: key and pointer streams sort before sound."""
        conn, streams = self._make_connection([0, 2, 4, 8, 12])
        conn._substream_ids = {4, 8, 12}
        conn._packet_type_streams = {"sound": 4, "key": 8, "pointer": 12}
        conn._prioritize_streams()
        order = list(streams.keys())
        key_idx = order.index(8)
        pointer_idx = order.index(12)
        sound_idx = order.index(4)
        self.assertLess(key_idx, sound_idx,
                        f"key should come before sound, got {order}")
        self.assertLess(pointer_idx, sound_idx,
                        f"pointer should come before sound, got {order}")

    def test_full_priority_order(self):
        """All stream types sort in the expected STREAM_PRIORITY order."""
        from xpra.net.quic.connection import STREAM_PRIORITY
        conn, streams = self._make_connection([0, 4, 8, 12, 16, 20])
        conn._substream_ids = {4, 8, 12, 16, 20}
        conn._packet_type_streams = {
            "draw": 4,
            "webcam": 8,
            "sound": 12,
            "pointer": 16,
            "key": 20,
        }
        conn._prioritize_streams()
        order = list(streams.keys())
        # main stream first
        self.assertEqual(order[0], 0)
        # then substreams in STREAM_PRIORITY order: key, pointer, sound, webcam, draw
        substream_order = order[1:]
        expected_types = list(STREAM_PRIORITY)
        actual_types = []
        type_by_sid = {v: k for k, v in conn._packet_type_streams.items()}
        for sid in substream_order:
            actual_types.append(type_by_sid[sid])
        self.assertEqual(actual_types, expected_types,
                         f"substream order should match STREAM_PRIORITY, got {actual_types}")

    def test_idempotent(self):
        """Calling _prioritize_streams twice gives the same result."""
        conn, streams = self._make_connection([0, 2, 4, 8])
        conn._substream_ids = {4, 8}
        conn._packet_type_streams = {"draw": 4, "sound": 8}
        conn._prioritize_streams()
        order1 = list(streams.keys())
        conn._prioritize_streams()
        order2 = list(streams.keys())
        self.assertEqual(order1, order2)

    def test_no_quic_attribute(self):
        """Gracefully handles missing _quic attribute (e.g., H0 connection)."""
        conn, _ = self._make_connection([0])
        conn.connection = MagicMock(spec=[])  # no _quic attribute
        # should not raise
        conn._prioritize_streams()


class TestAllocateSubstreamCallsPrioritize(unittest.TestCase):
    """Verify that _allocate_substream triggers _prioritize_streams."""

    def test_prioritize_called_on_allocate(self):
        from xpra.net.quic.connection import XpraQuicConnection
        conn = object.__new__(XpraQuicConnection)
        conn.stream_id = 0
        conn._packet_type_streams = {}
        conn._substream_ids = set()
        conn._pending_substreams = set()
        conn._use_substreams = True
        conn._substream_packet_types = ("sound", "draw")
        conn._register_substream = None
        conn.closed = False
        # fake quic
        mock_h3 = MagicMock()
        mock_quic = MagicMock()
        mock_quic.get_next_available_stream_id.return_value = 4
        mock_quic._streams = {0: FakeQuicStream(0)}
        mock_h3._quic = mock_quic
        conn.connection = mock_h3
        # spy on _prioritize_streams
        calls = []
        original = conn._prioritize_streams
        def spy():
            calls.append(True)
            original()
        conn._prioritize_streams = spy
        conn._allocate_substream("sound")
        self.assertEqual(len(calls), 1, "_prioritize_streams should be called once")
        self.assertIn(4, conn._substream_ids)


if __name__ == "__main__":
    unittest.main()
