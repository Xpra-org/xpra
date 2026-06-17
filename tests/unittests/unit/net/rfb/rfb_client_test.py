#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import zlib
import struct
import unittest

from xpra.net.common import Packet
from xpra.net.compression import Compressible
from xpra.net.rfb.const import RFBEncoding, RFBClientMessage, RFBServerMessage, PACKET_STRUCT
from xpra.clipboard.targets import TEXT_TARGETS
from xpra.client.base.rfb_protocol import RFBClientProtocol


def compact_len(n: int) -> bytes:
    # tight "compact" length encoding (mirrors the server's tight_header)
    if n < 128:
        return struct.pack(b"!B", n)
    if n < 16383:
        return struct.pack(b"!BB", 0x80 + (n & 0x7F), n >> 7)
    return struct.pack(b"!BBB", 0x80 + (n & 0x7F), 0x80 + ((n >> 7) & 0x7F), n >> 14)


def rect_header(x: int, y: int, w: int, h: int, encoding: int) -> bytes:
    return struct.pack(b"!HHHHi", x, y, w, h, encoding)


def zlib_stream(data: bytes) -> bytes:
    c = zlib.compressobj()
    return c.compress(data) + c.flush(zlib.Z_SYNC_FLUSH)


def gradient_encode(actual: bytes, w: int, h: int) -> bytes:
    # forward gradient filter: residual = (actual - clamp(left+up-upleft)) % 256
    res = bytearray(w * h * 3)

    def at(buf, xx, yy, cc):
        return buf[(yy * w + xx) * 3 + cc]
    for yy in range(h):
        for xx in range(w):
            for cc in range(3):
                i = (yy * w + xx) * 3 + cc
                left = at(actual, xx - 1, yy, cc) if xx > 0 else 0
                up = at(actual, xx, yy - 1, cc) if yy > 0 else 0
                ul = at(actual, xx - 1, yy - 1, cc) if (xx > 0 and yy > 0) else 0
                pred = left + up - ul
                pred = 0 if pred < 0 else (255 if pred > 255 else pred)
                res[i] = (actual[i] - pred) & 0xFF
    return bytes(res)


class TestRFBClient(unittest.TestCase):

    def _proto(self, dimensions=(64, 64)):
        # build a protocol instance without a connection or threads:
        proto = object.__new__(RFBClientProtocol)
        proto.protocol_version = (3, 8)
        proto.share = False
        proto._closed = False
        proto._conn = type("_Conn", (), {"target": "test"})()
        proto.dimensions = dimensions
        proto.position = (0, 0)
        proto.cursor_serial = 0
        proto.desktop_resized = False
        proto.rectangles = 0
        proto.zlib_streams = [None, None, None, None]
        proto.emitted = []
        proto.sent = []
        proto.idle_calls = []
        proto.timeout_calls = []
        proto._process_packet_cb = lambda p, packet: proto.emitted.append(packet)
        proto.send = proto.sent.append
        proto.idle_add = lambda fn, *args: proto.idle_calls.append((fn, args))
        proto.timeout_add = lambda delay, fn, *args: proto.timeout_calls.append((delay, fn, args))
        return proto

    def _feed_rect(self, proto, body, encoding, w, h, x=0, y=0):
        # drive a single rectangle through the dispatch + completion path:
        proto.emitted.clear()
        proto.sent.clear()
        proto.rectangles = 1
        proto._packet_parser = proto._parse_rectangle
        return proto._parse_rectangle(rect_header(x, y, w, h, encoding) + body)

    # -- helpers ------------------------------------------------------------

    def test_compact_length_roundtrip(self):
        for length in (0, 1, 127, 128, 200, 16382, 16383, 50000, 2097151):
            enc = compact_len(length)
            dec, used = RFBClientProtocol._parse_tight_length(enc, 0)
            self.assertEqual(dec, length)
            self.assertEqual(used, len(enc))
        # incomplete -> (-1, 0)
        self.assertEqual(RFBClientProtocol._parse_tight_length(b"\x80", 0), (-1, 0))

    # -- raw / pixel formats ------------------------------------------------

    def test_raw_rectangle(self):
        proto = self._proto()
        px = bytes([1, 2, 3, 4, 5, 6, 7, 8])  # 2x1 BGRX
        consumed = self._feed_rect(proto, px, RFBEncoding.RAW, 2, 1)
        self.assertEqual(consumed, 12 + 8)
        draw = proto.emitted[0]
        self.assertEqual(draw[0], "draw")
        self.assertEqual(draw[6], "rgb32")
        self.assertEqual(bytes(draw[7]), px)
        self.assertEqual(draw[9], 2 * 4)               # rowstride
        self.assertEqual(draw[10], {"rgb_format": "BGRX"})

    def test_raw_partial_waits(self):
        proto = self._proto()
        consumed = self._feed_rect(proto, bytes([1, 2, 3]), RFBEncoding.RAW, 2, 1)
        self.assertEqual(consumed, 0)
        self.assertEqual(proto.emitted, [])

    # -- tight --------------------------------------------------------------

    def test_tight_fill(self):
        proto = self._proto()
        consumed = self._feed_rect(proto, bytes([0x80, 9, 8, 7]), RFBEncoding.TIGHT, 2, 2)
        self.assertEqual(consumed, 12 + 4)
        draw = proto.emitted[0]
        self.assertEqual(draw[6], "rgb24")
        self.assertEqual(bytes(draw[7]), bytes([9, 8, 7]) * 4)

    def test_tight_jpeg(self):
        proto = self._proto()
        jpg = b"\xff\xd8\xff\xe0JPEGDATA"
        body = bytes([0x90]) + compact_len(len(jpg)) + jpg
        consumed = self._feed_rect(proto, body, RFBEncoding.TIGHT, 8, 8)
        self.assertEqual(consumed, 12 + len(body))
        draw = proto.emitted[0]
        self.assertEqual(draw[6], "jpeg")
        self.assertEqual(bytes(draw[7]), jpg)

    def test_tight_copy_zlib(self):
        proto = self._proto()
        w, h = 6, 5
        rgb = bytes((i * 7) % 256 for i in range(w * h * 3))
        z = zlib_stream(rgb)
        body = bytes([0x00]) + compact_len(len(z)) + z  # basic, stream0, copy filter
        consumed = self._feed_rect(proto, body, RFBEncoding.TIGHT, w, h)
        self.assertEqual(consumed, 12 + len(body))
        self.assertEqual(bytes(proto.emitted[0][7]), rgb)

    def test_tight_copy_raw_small(self):
        proto = self._proto()
        small = bytes(range(1, 10))  # 3x1 -> 9 bytes < TIGHT_MIN_TO_COMPRESS
        body = bytes([0x00]) + small
        consumed = self._feed_rect(proto, body, RFBEncoding.TIGHT, 3, 1)
        self.assertEqual(consumed, 12 + len(body))
        self.assertEqual(bytes(proto.emitted[0][7]), small)

    def test_tight_palette_indexed(self):
        proto = self._proto()
        palette = bytes([10, 11, 12, 20, 21, 22, 30, 31, 32])  # 3 colours
        idx = bytes([0, 1, 2, 2, 1, 0])
        body = bytes([0x40, 0x01, 0x02]) + palette + idx     # filter-present, palette, num-1=2
        consumed = self._feed_rect(proto, body, RFBEncoding.TIGHT, 6, 1)
        self.assertEqual(consumed, 12 + len(body))
        expect = bytes([10, 11, 12, 20, 21, 22, 30, 31, 32, 30, 31, 32, 20, 21, 22, 10, 11, 12])
        self.assertEqual(bytes(proto.emitted[0][7]), expect)

    def test_tight_palette_2color_1bit(self):
        proto = self._proto()
        pal = bytes([0, 0, 0, 255, 255, 255])
        w, h = 10, 1
        bits = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
        row = bytearray((w + 7) // 8)
        for xx, b in enumerate(bits):
            if b:
                row[xx >> 3] |= (1 << (7 - (xx & 7)))
        body = bytes([0x40, 0x01, 0x01]) + pal + bytes(row)  # num-1=1 -> 2 colours
        consumed = self._feed_rect(proto, body, RFBEncoding.TIGHT, w, h)
        self.assertEqual(consumed, 12 + len(body))
        expect = b"".join((pal[3:] if b else pal[:3]) for b in bits)
        self.assertEqual(bytes(proto.emitted[0][7]), expect)

    def test_tight_gradient(self):
        proto = self._proto()
        w, h = 4, 3
        actual = bytes((i * 13 + 7) % 256 for i in range(w * h * 3))
        z = zlib_stream(gradient_encode(actual, w, h))
        body = bytes([0x40, 0x02]) + compact_len(len(z)) + z  # filter-present, gradient
        consumed = self._feed_rect(proto, body, RFBEncoding.TIGHT, w, h)
        self.assertEqual(consumed, 12 + len(body))
        self.assertEqual(bytes(proto.emitted[0][7]), actual)

    def test_tight_zlib_stream_continuity(self):
        proto = self._proto()
        w, h = 4, 4
        r1 = bytes(i % 256 for i in range(w * h * 3))
        r2 = bytes((i * 2) % 256 for i in range(w * h * 3))
        c = zlib.compressobj()
        z1 = c.compress(r1) + c.flush(zlib.Z_SYNC_FLUSH)
        z2 = c.compress(r2) + c.flush(zlib.Z_SYNC_FLUSH)
        self._feed_rect(proto, bytes([0x00]) + compact_len(len(z1)) + z1, RFBEncoding.TIGHT, w, h)
        d1 = bytes(proto.emitted[0][7])
        self._feed_rect(proto, bytes([0x00]) + compact_len(len(z2)) + z2, RFBEncoding.TIGHT, w, h)
        d2 = bytes(proto.emitted[0][7])
        self.assertEqual((d1, d2), (r1, r2))

    def test_tight_unsupported_subtype_is_invalid(self):
        proto = self._proto()
        # reserved high nibble (0xA0): cannot be decoded
        self._feed_rect(proto, bytes([0xA0]), RFBEncoding.TIGHT, 2, 2)
        self.assertEqual(proto._packet_parser, proto._parse_invalid)

    # -- framebuffer-update dispatch ----------------------------------------

    def test_framebuffer_update_header(self):
        proto = self._proto()
        # exactly 4 bytes, 0 rectangles -> consumed (off-by-one fix)
        self.assertEqual(proto._parse_framebuffer_update(struct.pack(b"!BBH", 0, 0, 0)), 4)
        # fewer than 4 -> wait
        self.assertEqual(proto._parse_framebuffer_update(b"\x00\x00\x00"), 0)
        # 2 rectangles -> switch to rectangle parser
        proto._parse_framebuffer_update(struct.pack(b"!BBH", 0, 0, 2))
        self.assertEqual(proto.rectangles, 2)
        self.assertEqual(proto._packet_parser, proto._parse_rectangle)

    def test_bell_does_not_disconnect(self):
        proto = self._proto()
        consumed = proto._parse_rfb_packet(struct.pack(b"!B", RFBServerMessage.BELL))
        self.assertEqual(consumed, 1)
        self.assertEqual(proto.emitted[0][0], "bell")
        # invalid() would have scheduled idle/timeout callbacks to tear the connection down:
        self.assertEqual(proto.idle_calls, [])
        self.assertEqual(proto.timeout_calls, [])

    def test_setcolourmap_skipped(self):
        proto = self._proto()
        # type(1), pad, first(0), ncolours(2) -> 6 + 2*6 bytes
        body = struct.pack(b"!BBHH", RFBServerMessage.SETCOLORMAPENTRIES, 0, 0, 2) + b"\0" * 12
        self.assertEqual(proto._parse_rfb_packet(body), len(body))
        self.assertEqual(proto.emitted, [])

    def test_unknown_server_message_is_invalid(self):
        proto = self._proto()
        proto._parse_rfb_packet(struct.pack(b"!B", 99))
        self.assertEqual(proto._packet_parser, proto._parse_invalid)

    # -- clipboard ----------------------------------------------------------

    def _client_cut_text(self, msg):
        s = PACKET_STRUCT[RFBClientMessage.ClientCutText]
        return msg[s.size:s.size + s.unpack(msg[:s.size])[4]]

    def test_send_client_cut_text(self):
        proto = self._proto()
        proto.send_client_cut_text("hi\r\nthere")  # CR stripped, LF kept
        msg = proto.sent[0]
        self.assertEqual(msg[0], RFBClientMessage.ClientCutText)
        self.assertEqual(self._client_cut_text(msg), b"hi\nthere")

    def test_clipboard_token_text(self):
        proto = self._proto()
        token = ["clipboard-token", "CLIPBOARD", ["UTF8_STRING"], "UTF8_STRING",
                 "UTF8_STRING", 8, "bytes", "héllo".encode("utf8"), True, True]
        proto.send_clipboard_token(token)
        self.assertEqual(self._client_cut_text(proto.sent[0]), "héllo".encode("latin1"))

    def test_clipboard_token_non_text_ignored(self):
        proto = self._proto()
        for target in ("image/png", "application/octet-stream"):
            proto.sent.clear()
            token = ["clipboard-token", "CLIPBOARD", [target], target, target, 8, "bytes", b"\x89PNG", True, True]
            proto.send_clipboard_token(token)
            self.assertEqual(proto.sent, [])

    def test_clipboard_token_bare_ignored(self):
        proto = self._proto()
        proto.send_clipboard_token(["clipboard-token", "CLIPBOARD"])
        self.assertEqual(proto.sent, [])

    def test_clipboard_token_compressible(self):
        proto = self._proto()
        big = "A" * 5000
        comp = Compressible("clipboard: UTF8_STRING / 8", big.encode("utf8"))
        token = ["clipboard-token", "CLIPBOARD", ["UTF8_STRING"], "UTF8_STRING",
                 "UTF8_STRING", 8, "bytes", comp, True, True]
        proto.send_clipboard_token(token)
        self.assertEqual(self._client_cut_text(proto.sent[0]), big.encode("latin1"))

    def test_all_text_targets_accepted(self):
        proto = self._proto()
        for target in TEXT_TARGETS:
            proto.sent.clear()
            token = ["clipboard-token", "CLIPBOARD", [target], target, target, 8, "bytes", b"abc", True, True]
            proto.send_clipboard_token(token)
            self.assertEqual(len(proto.sent), 1, f"text target {target!r} should be relayed")

    def test_server_cut_text_to_clipboard(self):
        proto = self._proto()
        data = "héllo world".encode("latin1")
        msg = struct.pack(b"!BBBBI", 3, 0, 0, 0, len(data)) + data
        consumed = proto._parse_server_cut_text(msg)
        self.assertEqual(consumed, len(msg))
        token = proto.emitted[0]
        self.assertEqual(token[0], "clipboard-token")
        self.assertEqual(token[1], "CLIPBOARD")
        self.assertIn(token[3], TEXT_TARGETS)
        self.assertEqual(token[5], 8)
        self.assertEqual(token[6], "bytes")
        self.assertTrue(token[8] is True)
        self.assertEqual(token[7].decode("utf8"), "héllo world")

    def test_server_cut_text_partial_waits(self):
        proto = self._proto()
        self.assertEqual(proto._parse_server_cut_text(b"\x03\x00\x00"), 0)
        self.assertEqual(proto._parse_server_cut_text(struct.pack(b"!BBBBI", 3, 0, 0, 0, 10) + b"abc"), 0)
        self.assertEqual(proto.emitted, [])

    # -- cursor -------------------------------------------------------------

    def test_cursor(self):
        proto = self._proto()
        w, h, xhot, yhot = 2, 2, 1, 0
        px = bytes([10, 11, 12, 0, 20, 21, 22, 0, 30, 31, 32, 0, 40, 41, 42, 0])  # BGRX
        mask = bytes([0x80, 0x40])  # row0: px0 opaque; row1: px1 opaque
        consumed = self._feed_rect(proto, px + mask, RFBEncoding.CURSOR, w, h, x=xhot, y=yhot)
        self.assertEqual(consumed, 12 + len(px) + len(mask))
        cd = proto.emitted[0]
        self.assertEqual(cd[0], "cursor-data")
        self.assertEqual((cd[2], cd[3]), (w, h))
        self.assertEqual((cd[4], cd[5]), (xhot, yhot))
        self.assertEqual(cd[6], 1)  # serial
        expect = bytes([10, 11, 12, 0xFF, 20, 21, 22, 0x00,
                        30, 31, 32, 0x00, 40, 41, 42, 0xFF])
        self.assertEqual(bytes(cd[7]), expect)

    def test_cursor_empty(self):
        proto = self._proto()
        self.assertEqual(proto._parse_cursor(0, 0, 0, 0, b""), 0)
        self.assertEqual(proto.emitted, [])

    def test_cursor_partial_waits(self):
        proto = self._proto()
        self.assertEqual(proto._parse_cursor(0, 0, 2, 2, b"\0" * 17), -1)

    # -- desktop resize -----------------------------------------------------

    def test_desktop_size(self):
        proto = self._proto(dimensions=(800, 600))
        consumed = self._feed_rect(proto, b"", RFBEncoding.DESKTOPSIZE, 1024, 768)
        self.assertEqual(consumed, 12)
        self.assertEqual(proto.dimensions, (1024, 768))
        self.assertEqual([p[0] for p in proto.emitted], ["window-metadata", "window-move-resize"])
        md, mr = proto.emitted
        self.assertEqual(md[2]["size-constraints"]["maximum-size"], (1024, 768))
        self.assertEqual((mr[4], mr[5]), (1024, 768))
        # the completing update must request a *full* refresh:
        req = struct.unpack(b"!BBHHHH", proto.sent[0])
        self.assertEqual(req[0], RFBClientMessage.FramebufferUpdateRequest)
        self.assertEqual(req[1], 0)
        self.assertFalse(proto.desktop_resized)

    def test_desktop_size_same_is_noop(self):
        proto = self._proto(dimensions=(1024, 768))
        self._feed_rect(proto, b"", RFBEncoding.DESKTOPSIZE, 1024, 768)
        self.assertEqual(proto.emitted, [])
        self.assertEqual(struct.unpack(b"!BBHHHH", proto.sent[0])[1], 1)  # plain incremental

    def test_extended_desktop_size(self):
        proto = self._proto(dimensions=(800, 600))
        body = bytes([1, 0, 0, 0]) + struct.pack(b"!IHHHHI", 0, 0, 0, 1280, 1024, 0)
        consumed = self._feed_rect(proto, body, RFBEncoding.EXTENDEDDESKTOPSIZE, 1280, 1024, x=1)
        self.assertEqual(consumed, 12 + len(body))
        self.assertEqual(proto.dimensions, (1280, 1024))
        mr = proto.emitted[1]
        self.assertEqual((mr[4], mr[5]), (1280, 1024))

    def test_extended_desktop_size_partial_waits(self):
        proto = self._proto()
        self.assertEqual(proto._parse_extended_desktop_size(0, 0, 1280, 1024, bytes([1, 0, 0, 0]) + b"\0\0"), -1)

    # -- input --------------------------------------------------------------

    def test_pointer_position(self):
        proto = self._proto()
        proto.send_pointer_position(["pointer-position", 1, (30, 40), [], [1, 3]])
        mtype, mask, x, y = struct.unpack(b"!BBHH", proto.sent[0])
        self.assertEqual(mtype, RFBClientMessage.PointerEvent)
        self.assertEqual((x, y), (30, 40))
        self.assertEqual(mask, 0b101)   # buttons 1 and 3 -> bits 0 and 2

    def test_button_action_no_offbyone(self):
        proto = self._proto()
        # left button (1) press, no buttons list -> bit 0 only
        proto.send_button_action(Packet("button-action", 1, 1, True, (5, 6)))
        self.assertEqual(struct.unpack(b"!BBHH", proto.sent[0])[1], 0b1)
        # right button (3) with buttons list -> bit 2
        proto.sent.clear()
        proto.send_button_action(Packet("button-action", 1, 3, True, (5, 6), [], [3]))
        self.assertEqual(struct.unpack(b"!BBHH", proto.sent[0])[1], 0b100)

    def test_key_action(self):
        proto = self._proto()
        proto.send_key_action(["key-action", 1, "a", True, [], 0, "a", 38, 0])
        mtype, pressed, _pad, keysym = struct.unpack(b"!BBHI", proto.sent[0])
        self.assertEqual(mtype, RFBClientMessage.KeyEvent)
        self.assertEqual(pressed, 1)
        self.assertEqual(keysym, ord("a"))
        # unknown key name -> nothing sent
        proto.sent.clear()
        proto.send_key_action(["key-action", 1, "NoSuchKey", True, [], 0, "", 0, 0])
        self.assertEqual(proto.sent, [])

    # -- security handshake -------------------------------------------------

    def test_security_handshake_length_guard(self):
        proto = self._proto()
        self.assertEqual(proto._parse_security_handshake(b""), 0)              # need the count byte
        self.assertEqual(proto._parse_security_handshake(b"\x02\x01"), 0)      # claims 2 types, only 1 present

    def test_security_handshake_none(self):
        proto = self._proto()
        # 1 type offered: None(1) -> selects None and acknowledges it
        consumed = proto._parse_security_handshake(struct.pack(b"!BB", 1, 1))
        self.assertEqual(consumed, 2)
        self.assertEqual(proto.sent[0], struct.pack(b"!B", 1))
        self.assertEqual(proto._packet_parser, proto._parse_security_result)

    def test_security_handshake_none_37_skips_result(self):
        # RFB 3.7 with None must go straight to ClientInit (no SecurityResult):
        proto = self._proto()
        proto.protocol_version = (3, 7)
        consumed = proto._parse_security_handshake(struct.pack(b"!BB", 1, 1))
        self.assertEqual(consumed, 2)
        # selected type byte, then the ClientInit shared-flag byte:
        self.assertEqual(proto.sent, [struct.pack(b"!B", 1), struct.pack(b"!B", 0)])
        self.assertEqual(proto._packet_parser, proto._parse_client_init)

    def test_security_handshake_vnc(self):
        proto = self._proto()
        consumed = proto._parse_security_handshake(struct.pack(b"!BB", 1, 2))
        self.assertEqual(consumed, 2)
        self.assertEqual(proto.sent[0], struct.pack(b"!B", 2))
        self.assertEqual(proto._packet_parser, proto._parse_vnc_security_challenge)

    def test_security_handshake_failure_reason(self):
        # n==0 means failure, followed by a u32-length-prefixed reason:
        proto = self._proto()
        reason = b"too many attempts"
        proto._parse_security_handshake(struct.pack(b"!BI", 0, len(reason)) + reason)
        self.assertEqual(len(proto.idle_calls), 1)  # _internal_error -> connection lost

    # -- protocol version negotiation ---------------------------------------

    def test_version_negotiation_38(self):
        proto = self._proto()
        consumed = proto._parse_protocol_handshake(b"RFB 003.008\n")
        self.assertEqual(consumed, 12)
        self.assertEqual(proto.protocol_version, (3, 8))
        self.assertEqual(proto.sent[0], b"RFB 003.008\n")
        self.assertEqual(proto._packet_parser, proto._parse_security_handshake)

    def test_version_negotiation_37(self):
        proto = self._proto()
        proto._parse_protocol_handshake(b"RFB 003.007\n")
        self.assertEqual(proto.protocol_version, (3, 7))
        self.assertEqual(proto.sent[0], b"RFB 003.007\n")
        self.assertEqual(proto._packet_parser, proto._parse_security_handshake)

    def test_version_negotiation_33(self):
        proto = self._proto()
        proto._parse_protocol_handshake(b"RFB 003.003\n")
        self.assertEqual(proto.protocol_version, (3, 3))
        self.assertEqual(proto.sent[0], b"RFB 003.003\n")
        # 3.3 uses the single-u32 security handshake:
        self.assertEqual(proto._packet_parser, proto._parse_security_handshake_33)

    def test_version_negotiation_clamps_to_max(self):
        # Apple Remote Desktop announces 003.889; we cap at our maximum (3.8):
        proto = self._proto()
        proto._parse_protocol_handshake(b"RFB 003.889\n")
        self.assertEqual(proto.protocol_version, (3, 8))
        self.assertEqual(proto.sent[0], b"RFB 003.008\n")

    def test_version_negotiation_unknown_minor_rounds_down(self):
        # a non-standard 3.5 rounds down to the highest version we know (3.3):
        proto = self._proto()
        proto._parse_protocol_handshake(b"RFB 003.005\n")
        self.assertEqual(proto.protocol_version, (3, 3))
        self.assertEqual(proto.sent[0], b"RFB 003.003\n")

    def test_version_negotiation_incomplete(self):
        proto = self._proto()
        self.assertEqual(proto._parse_protocol_handshake(b"RFB 003"), 0)
        self.assertEqual(proto.sent, [])

    def test_version_negotiation_bad_header(self):
        proto = self._proto()
        proto._parse_protocol_handshake(b"XXX 003.008\n")
        # rejected: parser switched to the invalid sink, nothing sent
        self.assertEqual(proto._packet_parser, proto._parse_invalid)

    def test_version_negotiation_too_old(self):
        # older than 3.3 is unsupported -> rejected with a reason
        proto = self._proto()
        proto._parse_protocol_handshake(b"RFB 003.002\n")
        self.assertEqual(proto._packet_parser, proto._parse_invalid)

    # -- RFB 3.3 security handshake -----------------------------------------

    def test_security_handshake_33_none(self):
        # 3.3 None: server sends type as u32, no client reply, straight to ClientInit
        proto = self._proto()
        proto.protocol_version = (3, 3)
        consumed = proto._parse_security_handshake_33(struct.pack(b"!I", 1))
        self.assertEqual(consumed, 4)
        # only the ClientInit shared-flag byte is sent (no selected-type byte):
        self.assertEqual(proto.sent, [struct.pack(b"!B", 0)])
        self.assertEqual(proto._packet_parser, proto._parse_client_init)

    def test_security_handshake_33_vnc(self):
        proto = self._proto()
        proto.protocol_version = (3, 3)
        consumed = proto._parse_security_handshake_33(struct.pack(b"!I", 2))
        self.assertEqual(consumed, 4)
        self.assertEqual(proto.sent, [])  # no reply byte in 3.3
        self.assertEqual(proto._packet_parser, proto._parse_vnc_security_challenge)

    def test_security_handshake_33_failure(self):
        # type 0 == failure, followed by a reason string:
        proto = self._proto()
        proto.protocol_version = (3, 3)
        reason = b"no"
        proto._parse_security_handshake_33(struct.pack(b"!II", 0, len(reason)) + reason)
        self.assertEqual(len(proto.idle_calls), 1)

    def test_security_handshake_33_incomplete(self):
        proto = self._proto()
        proto.protocol_version = (3, 3)
        self.assertEqual(proto._parse_security_handshake_33(b"\x00\x00\x00"), 0)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
