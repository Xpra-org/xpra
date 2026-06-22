#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
import threading
import unittest
from unittest.mock import patch

from xpra.net.websockets.common import OPCODE
from xpra.net.websockets.header import encode_hybi_header
from xpra.net.websockets.protocol import WebSocketProtocol


def frame(opcode, payload=b"", fin=True):
    return encode_hybi_header(opcode, len(payload), fin=fin) + payload


def protocol():
    p = object.__new__(WebSocketProtocol)
    p.ws_data = b""
    p.ws_payload = []
    p.ws_xpra_data = []
    p.ws_payload_opcode = 0
    p.ws_mask = False
    p.input_packetcount = 1
    p._closed = False
    p._conn = "test"
    p._write_lock = threading.Lock()
    p.writes = []
    p.losses = []
    p.raw_write = lambda packet_type, items: p.writes.append((packet_type, items))
    p._connection_lost = p.losses.append
    return p


class WebSocketProtocolTest(unittest.TestCase):

    def test_binary_text_and_partial_frames(self):
        p = protocol()
        binary = frame(OPCODE.BINARY, b"binary")
        p.parse_ws_frame(binary[:3])
        self.assertEqual(p.ws_data, binary[:3])
        p.parse_ws_frame(binary[3:] + frame(OPCODE.TEXT, b"text"))
        self.assertEqual(p.ws_xpra_data, [b"binary", b"text"])
        self.assertEqual(p.ws_data, b"")

    def test_fragmentation(self):
        p = protocol()
        p.parse_ws_frame(frame(OPCODE.BINARY, b"first", fin=False))
        self.assertEqual(p.ws_payload_opcode, OPCODE.BINARY)
        p.parse_ws_frame(frame(OPCODE.CONTINUE, b"second"))
        self.assertEqual(p.ws_xpra_data, [b"firstsecond"])
        self.assertEqual(p.ws_payload, [])
        with self.assertRaises(AssertionError):
            protocol().parse_ws_frame(frame(OPCODE.CONTINUE, b"orphan"))

    def test_invalid_fragment_sequences(self):
        p = protocol()
        p.parse_ws_frame(frame(OPCODE.TEXT, b"partial", fin=False))
        with self.assertRaises(ValueError):
            p.parse_ws_frame(frame(OPCODE.BINARY, b"wrong"))
        with self.assertRaises(RuntimeError):
            protocol().parse_ws_frame(frame(OPCODE.PING, b"ping", fin=False))

    def test_ping_and_close(self):
        p = protocol()
        p.parse_ws_frame(frame(OPCODE.PING, b"hello"))
        self.assertEqual(p.writes[0][0], "ws-ping")
        self.assertEqual(p.writes[0][1][0], frame(OPCODE.PONG, b"hello"))
        p.parse_ws_frame(frame(OPCODE.CLOSE, struct.pack("!H", 1001) + b"going away"))
        self.assertEqual(p.losses, ["code 1001: going away"])
        p = protocol()
        p.parse_ws_frame(frame(OPCODE.CLOSE, b""))
        self.assertEqual(p.losses, ["unknown reason"])

    def test_empty_pong_unknown_and_invalid_close(self):
        p = protocol()
        p.input_packetcount = 0
        p.parse_ws_frame(b"\r\n" + frame(OPCODE.BINARY) + frame(OPCODE.PONG, b"pong") + frame(3, b"unknown"))
        self.assertEqual(p.ws_xpra_data, [])
        p.parse_ws_frame(frame(OPCODE.CLOSE, struct.pack("!H", 1002) + b"\xff"))
        self.assertIn("code 1002:", p.losses[0])

    def test_frame_header_masking(self):
        p = protocol()
        self.assertEqual(p.make_wsframe_header("test", [b"abcd"]), encode_hybi_header(OPCODE.BINARY, 4))
        items = [b"abcd", b"efgh"]
        p.ws_mask = True
        with patch("xpra.net.websockets.protocol.os.urandom", return_value=b"1234"):
            header = p.make_wsframe_header("test", items)
        self.assertTrue(header[1] & 0x80)
        self.assertEqual(header[-4:], b"1234")
        self.assertNotEqual(items, [b"abcd", b"efgh"])


if __name__ == "__main__":
    unittest.main()
