#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.rdp.const import SecurityProtocol, RDPNeg, RDPNegFailure, protocols_str
from xpra.net.rdp import protocol


class TestRDP(unittest.TestCase):

    def test_tpkt_roundtrip(self):
        payload = b"hello rdp"
        pdu = protocol.format_tpkt(payload)
        # version, reserved, big-endian length including the 4 byte header:
        self.assertEqual(pdu[0], 3)
        self.assertEqual(pdu[1], 0)
        self.assertEqual((pdu[2] << 8) | pdu[3], len(payload) + 4)
        parsed, consumed = protocol.parse_tpkt(pdu)
        self.assertEqual(consumed, len(pdu))
        self.assertEqual(parsed, payload)

    def test_tpkt_incomplete(self):
        pdu = protocol.format_tpkt(b"some payload")
        # not enough for the header:
        self.assertEqual(protocol.parse_tpkt(pdu[:2]), (b"", 0))
        # header present but body truncated:
        self.assertEqual(protocol.parse_tpkt(pdu[:-1]), (b"", 0))
        # trailing bytes from the next PDU are not consumed:
        parsed, consumed = protocol.parse_tpkt(pdu + b"EXTRA")
        self.assertEqual(consumed, len(pdu))
        self.assertEqual(parsed, b"some payload")

    def test_tpkt_bad_version(self):
        self.assertRaises(ValueError, protocol.parse_tpkt, b"\x04\x00\x00\x05x")

    def test_connection_request_vector(self):
        # a minimal Connection Request advertising SSL+HYBRID, no cookie:
        expected = bytes.fromhex("03 00 00 13 0e e0 00 00 00 00 00 01 00 08 00 03 00 00 00".replace(" ", ""))
        cr = protocol.build_connection_request(SecurityProtocol.SSL | SecurityProtocol.HYBRID)
        self.assertEqual(cr, expected)

    def test_connection_request_roundtrip(self):
        for cookie in (b"", b"mstshash=user"):
            for requested in (
                0,
                SecurityProtocol.SSL,
                SecurityProtocol.SSL | SecurityProtocol.HYBRID | SecurityProtocol.HYBRID_EX,
            ):
                pdu = protocol.build_connection_request(requested, cookie)
                payload, consumed = protocol.parse_tpkt(pdu)
                self.assertEqual(consumed, len(pdu))
                req = protocol.parse_x224_connection_request(payload)
                self.assertTrue(req.has_negotiation)
                self.assertEqual(req.requested_protocols, int(requested))
                if cookie:
                    self.assertEqual(req.cookie, b"Cookie: " + cookie)

    def test_connection_confirm_response_vector(self):
        expected = bytes.fromhex("03 00 00 13 0e d0 00 00 00 00 00 02 00 08 00 01 00 00 00".replace(" ", ""))
        cc = protocol.build_connection_confirm(protocol.format_rdp_neg_rsp(SecurityProtocol.SSL))
        self.assertEqual(cc, expected)

    def test_connection_confirm_response_roundtrip(self):
        cc = protocol.build_connection_confirm(protocol.format_rdp_neg_rsp(SecurityProtocol.HYBRID))
        payload, consumed = protocol.parse_tpkt(cc)
        self.assertEqual(consumed, len(cc))
        rsp = protocol.parse_x224_connection_confirm(payload)
        self.assertIsNotNone(rsp)
        self.assertEqual(rsp.type, RDPNeg.RESPONSE)
        self.assertEqual(rsp.selected_protocol, int(SecurityProtocol.HYBRID))

    def test_connection_confirm_failure_roundtrip(self):
        cc = protocol.build_connection_confirm(
            protocol.format_rdp_neg_failure(RDPNegFailure.SSL_CERT_NOT_ON_SERVER))
        payload, _ = protocol.parse_tpkt(cc)
        rsp = protocol.parse_x224_connection_confirm(payload)
        self.assertIsNotNone(rsp)
        self.assertEqual(rsp.type, RDPNeg.FAILURE)
        self.assertEqual(rsp.failure_code, int(RDPNegFailure.SSL_CERT_NOT_ON_SERVER))

    def test_connection_confirm_no_negotiation(self):
        # an X.224 CC with no RDP negotiation structure (standard RDP fallback):
        cc = protocol.build_connection_confirm()
        payload, _ = protocol.parse_tpkt(cc)
        self.assertIsNone(protocol.parse_x224_connection_confirm(payload))

    def test_wrong_tpdu_codes(self):
        # a Connection Confirm parsed as a Connection Request should fail:
        cc_payload = protocol.format_x224_connection_confirm(protocol.format_rdp_neg_rsp(SecurityProtocol.SSL))
        self.assertRaises(ValueError, protocol.parse_x224_connection_request, cc_payload)
        cr_payload = protocol.format_x224_connection_request(SecurityProtocol.SSL)
        self.assertRaises(ValueError, protocol.parse_x224_connection_confirm, cr_payload)

    def test_protocols_str(self):
        self.assertEqual(protocols_str(0), "RDP")
        self.assertEqual(protocols_str(SecurityProtocol.SSL), "SSL")
        self.assertIn("HYBRID", protocols_str(SecurityProtocol.SSL | SecurityProtocol.HYBRID))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
