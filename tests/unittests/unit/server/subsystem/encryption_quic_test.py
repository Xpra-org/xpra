#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace

from xpra.net.common import QUIC_ENCRYPTION_ERROR
from xpra.server.subsystem.encryption import parse_encryption, setup_encryption
from xpra.util.objects import typedict


def protocol(socktype="wss", wrapped="quic"):
    conn = SimpleNamespace(socktype=socktype, socktype_wrapped=wrapped)
    return SimpleNamespace(_conn=conn, encryption="", keyfile="", keydata=b"", authenticators=())


class EncryptionQuicTest(unittest.TestCase):

    def test_socket_option_ignored(self):
        proto = protocol()
        parse_encryption(proto, {"encryption": "AES-CBC", "keydata": "secret"}, "", "")
        self.assertFalse(proto.encryption)

    def test_tcp_encryption_ignored(self):
        # ie: XPRA_ENCRYPTED_SOCKET_TYPES=tcp,ws,wss
        from unittest.mock import patch
        proto = protocol()
        with patch("xpra.server.subsystem.encryption.ENCRYPTED_SOCKET_TYPES", "wss"):
            parse_encryption(proto, {}, "AES-CBC", "")
        self.assertFalse(proto.encryption)

    def test_not_quic(self):
        proto = protocol("tcp", "tcp")
        parse_encryption(proto, {"encryption": "AES-CBC", "keydata": "secret"}, "", "")
        self.assertEqual(proto.encryption, "AES-CBC")

    def test_client_requests_encryption(self):
        with self.assertRaises(ValueError) as cm:
            setup_encryption(protocol(), typedict({"encryption": {"cipher": "AES"}}))
        self.assertEqual(str(cm.exception), QUIC_ENCRYPTION_ERROR)

    def test_no_encryption(self):
        self.assertEqual(setup_encryption(protocol(), typedict()), {})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
