#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import struct
import unittest

from xpra.util.objects import AdHocStruct
from xpra.codecs.image import ImageWrapper
from xpra.common import noop
from xpra.net.rfb.const import RFBAuth, RFBEncoding, RFBVeNCrypt
from xpra.net.rfb.protocol import RFBProtocol, READ_BUFFER_SIZE
from xpra.server.rfb.protocol import RFBServerProtocol
from xpra.server.rfb.source import RFB_WRITE_QUEUE_MAX_BYTES, RFBSource


class TestRFB(unittest.TestCase):

    def _rfb_server_proto(self, auth=None, ssl_options=None):
        class Conn:
            target = "test-target"
            local = ("127.0.0.1", 10000)
            remote = ("127.0.0.1", 20000)
            endpoint = remote
            socktype = "rfb"
            options = {}
            timeout = 1

            def write(self, buf):
                return len(buf)

            def close(self):
                pass

        def get_pixelformat():
            return 640, 480, 32, 24, False, True, 255, 255, 255, 16, 8, 0

        proto = RFBServerProtocol(Conn(), auth, noop, get_pixelformat,
                                  ssl_options=ssl_options)
        proto.sent = []
        proto.send = proto.sent.append
        return proto

    def test_rfb_server_vencrypt_advertisement(self):
        proto = self._rfb_server_proto()
        proto.handshake_complete()
        self.assertEqual(proto.sent[0], bytes([1, RFBAuth.NONE]))

        proto = self._rfb_server_proto(ssl_options={"cert": "/tmp/cert.pem"})
        proto.handshake_complete()
        self.assertEqual(proto.sent[0], bytes([2, RFBAuth.VeNCrypt, RFBAuth.NONE]))

        class Auth:
            def requires_challenge(self):
                return True

        proto = self._rfb_server_proto(Auth(), {"cert": "/tmp/cert.pem"})
        proto.handshake_complete()
        self.assertEqual(proto.sent[0], bytes([2, RFBAuth.VeNCrypt, RFBAuth.VNC]))

    def test_rfb_server_vencrypt_version_and_subtype(self):
        proto = self._rfb_server_proto(ssl_options={"cert": "/tmp/cert.pem"})
        proto.handshake_complete()
        self.assertEqual(proto._parse_security_handshake(bytes([RFBAuth.VeNCrypt])), 1)
        self.assertEqual(proto.sent[-1], b"\0\2")
        self.assertEqual(proto._packet_parser, proto._parse_vencrypt_version)

        self.assertEqual(proto._parse_vencrypt_version(b"\0\2"), 2)
        self.assertEqual(proto.sent[-2], b"\0")
        self.assertEqual(proto.sent[-1], b"\1" + struct.pack(b"!I", RFBVeNCrypt.X509NONE))
        self.assertEqual(proto.read_buffer_size, 4)

        acks = []
        upgrades = []
        proto._send_vencrypt_subtype_ack = lambda accepted: acks.append(accepted) or True
        proto._upgrade_to_tls = lambda: upgrades.append(proto._vencrypt_subtype)
        self.assertEqual(proto._parse_vencrypt_subtype(struct.pack(b"!I", RFBVeNCrypt.X509NONE)), 4)
        self.assertEqual(acks, [True])
        self.assertEqual(upgrades, [RFBVeNCrypt.X509NONE])
        self.assertEqual(proto.read_buffer_size, READ_BUFFER_SIZE)

    def test_rfb_server_vencrypt_authenticated_subtype(self):
        class Auth:
            def requires_challenge(self):
                return True

            def get_challenge(self, _digests):
                return b"0123456789abcdef", "des"

        proto = self._rfb_server_proto(Auth(), {"cert": "/tmp/cert.pem"})
        proto.handshake_complete()
        proto._parse_security_handshake(bytes([RFBAuth.VeNCrypt]))
        proto._parse_vencrypt_version(b"\0\2")
        self.assertEqual(proto.sent[-1], b"\1" + struct.pack(b"!I", RFBVeNCrypt.X509VNC))

    def test_rfb_server_vencrypt_rejects_bad_subtype(self):
        proto = self._rfb_server_proto(ssl_options={"cert": "/tmp/cert.pem"})
        proto.handshake_complete()
        proto._parse_security_handshake(bytes([RFBAuth.VeNCrypt]))
        proto._parse_vencrypt_version(b"\0\2")
        acks = []
        proto._send_vencrypt_subtype_ack = lambda accepted: acks.append(accepted) or True
        proto._upgrade_to_tls = lambda: self.fail("unexpected TLS upgrade")
        self.assertEqual(proto._parse_vencrypt_subtype(struct.pack(b"!I", RFBVeNCrypt.X509VNC)), 0)
        self.assertEqual(acks, [False])

    def test_rfb_protocol_write_backlog(self):
        class Conn:
            def write(self, buf):
                return len(buf)

            def close(self):
                pass

        class WriteThread:
            name = "write"

            def is_alive(self):
                return False

        p = RFBProtocol(Conn(), noop)
        p.start_write_thread = lambda: setattr(p, "_write_thread", WriteThread())
        p.send(b"abc")
        p.send(b"defg")
        self.assertEqual(p.queue_size(), 2)
        self.assertEqual(p.queue_byte_size(), 7)
        self.assertEqual(p.pending_write_bytes(), 7)

        p._write()
        self.assertEqual(p.queue_size(), 1)
        self.assertEqual(p.queue_byte_size(), 4)
        self.assertEqual(p.pending_write_bytes(), 4)
        self.assertEqual(p.output_bytecount, 3)
        self.assertEqual(p.get_info()["write"]["last"]["bytes"], 3)

    def test_rfb_source(self):
        # fake protocol:
        p = AdHocStruct()
        p.send = noop
        p.queue_size = lambda : 1
        # fake window:
        window = AdHocStruct()

        def get_image(x, y, w, h):
            stride = (w+8)*4
            pixels = b"0"*stride*h
            return ImageWrapper(x, y, w, h, pixels, "BGRX", 24, stride, 4)
        window.get_image = get_image
        window.acknowledge_changes = noop
        for protocol in (p, None):
            s = RFBSource(protocol, True)
            assert s.get_info()
            s.set_default_keymap()
            s.send_cursor()
            s.update_mouse(1, 0, 0)
            s.damage(1, window, 0, 0, 1024, 768, {"polling" : protocol is None})
            s.damage(1, window, 0, 0, 2, 2, {"polling" : protocol is None})
            s.send_clipboard("foo")
            s.bell()
            assert not s.is_closed()
            s.close()
            # noop:
            s.damage(1, window, 0, 0, 2, 2, {"polling" : protocol is None})
            assert s.is_closed()

    def test_rfb_source_damage_batching(self):
        sent = []
        p = AdHocStruct()
        p.send = sent.append
        p.queue_size = lambda : 0

        image_calls = []
        window = AdHocStruct()

        def get_image(x, y, w, h):
            image_calls.append((x, y, w, h))
            stride = (w + 8) * 4
            pixels = b"0" * stride * h
            return ImageWrapper(x, y, w, h, pixels, "BGRX", 24, stride, 4)

        window.get_image = get_image
        window.acknowledge_changes = noop
        window.get_dimensions = lambda: (100, 100)

        s = RFBSource(p, True)
        try:
            s.damage(1, window, 1, 2, 3, 4, {"polling": True})
            self.assertEqual(image_calls, [])
            self.assertEqual(s.damage_rectangles, [])

            s.request_update(0, 0, 100, 100)
            s.damage(1, window, 1, 2, 3, 4, {"polling": True})
            self.assertEqual(image_calls, [])
            self.assertEqual([r.get_geometry() for r in s.damage_rectangles], [(1, 2, 3, 4)])
            self.assertNotEqual(s.damage_timer, 0)

            s.damage(1, window, 10, 20, 5, 6, {"polling": True})
            self.assertEqual(len(s.damage_rectangles), 2)

            s.cancel_damage_timer()
            s.process_damage()
            self.assertEqual(image_calls, [(1, 2, 14, 24)])
            self.assertEqual(s.damage_rectangles, [])
        finally:
            s.close()

    def test_rfb_source_write_byte_backlog(self):
        p = AdHocStruct()
        p.send = noop
        p.queue_size = lambda: 0
        p.pending_write_bytes = lambda: RFB_WRITE_QUEUE_MAX_BYTES

        s = RFBSource(p, True)
        try:
            self.assertTrue(s.has_backlog())
        finally:
            s.close()

    def test_rfb_source_damage_request_clip(self):
        p = AdHocStruct()
        p.send = noop
        p.queue_size = lambda: 0

        window = AdHocStruct()
        s = RFBSource(p, True)
        try:
            s.request_update(10, 10, 20, 20)
            s.damage(1, window, 0, 0, 20, 20, {"polling": True})
            self.assertEqual([r.get_geometry() for r in s.damage_rectangles], [(10, 10, 10, 10)])
            self.assertEqual(s.damage_clip.get_geometry(), (10, 10, 20, 20))

            s.damage(1, window, 25, 25, 20, 20, {"polling": True})
            self.assertEqual([r.get_geometry() for r in s.damage_rectangles],
                             [(10, 10, 10, 10), (25, 25, 5, 5)])

            s.damage(1, window, 0, 40, 5, 5, {"polling": True})
            self.assertEqual([r.get_geometry() for r in s.damage_rectangles],
                             [(10, 10, 10, 10), (25, 25, 5, 5)])
        finally:
            s.close()

    def test_rfb_source_continuous_updates_clip(self):
        p = AdHocStruct()
        p.send = noop
        p.queue_size = lambda: 0

        window = AdHocStruct()
        s = RFBSource(p, True)
        try:
            s.set_continuous_updates(True, 10, 10, 20, 20)
            s.damage(1, window, 0, 0, 20, 20, {"polling": True})
            self.assertEqual([r.get_geometry() for r in s.damage_rectangles], [(10, 10, 10, 10)])

            s.damage(1, window, 0, 40, 5, 5, {"polling": True})
            self.assertEqual([r.get_geometry() for r in s.damage_rectangles], [(10, 10, 10, 10)])
        finally:
            s.close()

    def test_rfb_source_damage_regions(self):
        p = AdHocStruct()
        p.send = noop
        p.queue_size = lambda: 0

        image_calls = []
        window = AdHocStruct()

        def get_image(x, y, w, h):
            image_calls.append((x, y, w, h))
            stride = (w + 8) * 4
            pixels = b"0" * stride * h
            return ImageWrapper(x, y, w, h, pixels, "BGRX", 24, stride, 4)

        window.get_image = get_image
        window.acknowledge_changes = noop
        window.get_dimensions = lambda: (1000, 1000)

        s = RFBSource(p, True)
        try:
            s.request_update(0, 0, 1000, 1000)
            s.damage(1, window, 0, 0, 10, 10, {"polling": True})
            s.damage(1, window, 900, 900, 10, 10, {"polling": True})
            s.cancel_damage_timer()
            s.process_damage()
            self.assertEqual(image_calls, [(0, 0, 10, 10), (900, 900, 10, 10)])
        finally:
            s.close()

    def test_rfb_source_region_encoding_selection(self):
        p = AdHocStruct()
        p.send = noop
        p.queue_size = lambda: 0

        s = RFBSource(p, True)
        try:
            s.encodings = [RFBEncoding.ZLIB, RFBEncoding.TIGHT, RFBEncoding.TIGHT_PNG]
            self.assertEqual(s.get_region_encoding(16, 16), RFBEncoding.ZLIB)
            s.quality = 30
            self.assertEqual(s.get_region_encoding(128, 128), RFBEncoding.TIGHT)
            s.quality = 90
            self.assertEqual(s.get_region_encoding(128, 128), RFBEncoding.TIGHT_PNG)
            s.encodings = [RFBEncoding.TIGHT]
            self.assertEqual(s.get_region_encoding(128, 128), RFBEncoding.TIGHT)
        finally:
            s.close()

    def test_rfb_source_encode_regions(self):
        sent = []
        p = AdHocStruct()
        p.send = sent.append
        p.queue_size = lambda: 0

        s = RFBSource(p, True)
        try:
            images = (
                ImageWrapper(0, 0, 1, 1, b"1234", "BGRX", 24, 4, 4),
                ImageWrapper(2, 2, 1, 1, b"5678", "BGRX", 24, 4, 4),
            )
            regions = (
                (images[0], 0, 0, 1, 1, RFBEncoding.RAW),
                (images[1], 2, 2, 1, 1, RFBEncoding.RAW),
            )
            s.encode_regions(1, regions)
            self.assertEqual(len(sent), 1)
            self.assertEqual(struct.unpack(b"!BBH", sent[0][:4]), (0, 0, 2))
        finally:
            s.close()

    def test_rfb_source_refresh_rate_delay(self):
        p = AdHocStruct()
        p.send = noop
        p.queue_size = lambda : 0

        s = RFBSource(p, True)
        try:
            s.set_refresh_rate(50)
            self.assertEqual(s.damage_delay, 20)
            s.set_refresh_rate(60)
            self.assertEqual(s.damage_delay, 16)
            s.set_refresh_rate(200)
            self.assertEqual(s.damage_delay, 10)
            s.set_refresh_rate(1)
            self.assertEqual(s.damage_delay, 100)
            s.set_refresh_rate(0)
            self.assertEqual(s.damage_delay, 20)
        finally:
            s.close()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
