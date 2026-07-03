#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base import aes
from xpra.client.base.aes import AES
from xpra.scripts.config import InitExit
from xpra.util.objects import typedict


def client(options=None, protocol_type="tcp"):
    value = AES()
    conn = SimpleNamespace(options=options or {})
    value._protocol = SimpleNamespace(TYPE=protocol_type, _conn=conn, set_cipher_in=Mock(), set_cipher_out=Mock())
    return value


class AESTest(unittest.TestCase):

    def test_encryption_selection(self):
        value = client({"encryption": "AES-CBC"})
        value.encryption = "AES-GCM"
        self.assertEqual(value.get_encryption(), "AES-CBC")
        self.assertEqual(client({"keydata": "0x0102"}).get_encryption(), f"AES-{aes.DEFAULT_MODE}")
        with patch.dict(os.environ, {"XPRA_ENCRYPTION_KEY": "secret"}):
            self.assertEqual(client().get_encryption(), f"AES-{aes.DEFAULT_MODE}")

    def test_key_precedence_and_failures(self):
        self.assertEqual(client({"keydata": "0x0102"}).get_encryption_key(), b"\x01\x02")
        with tempfile.NamedTemporaryFile() as keyfile:
            keyfile.write(b"file-key\r\n")
            keyfile.flush()
            self.assertEqual(client({"keyfile": keyfile.name}).get_encryption_key(), b"file-key")
        with patch.dict(os.environ, {"XPRA_ENCRYPTION_KEY": "env-key\n"}):
            self.assertEqual(client().get_encryption_key(), b"env-key")
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(InitExit):
            client().get_encryption_key()

    def test_cipher_caps(self):
        value = client({"encryption": "AES-GCM"})
        value.get_encryption_key = Mock(return_value=b"key")
        with patch.multiple(aes, crypto_backend_init=Mock(), get_ciphers=Mock(return_value=("AES",)),
                            get_modes=Mock(return_value=("GCM",)), get_iv=Mock(return_value="iv"),
                            get_salt=Mock(return_value=b"salt"), get_iterations=Mock(return_value=10),
                            choose_padding=Mock(return_value="PKCS#7")):
            caps = value.get_cipher_caps()
        self.assertEqual((caps["cipher"], caps["mode"]), ("AES", "GCM"))
        value._protocol.set_cipher_in.assert_called_once()
        with patch.object(value, "get_encryption", return_value="invalid-GCM"), \
                patch.object(aes, "get_ciphers", return_value=("AES",)):
            with self.assertRaises(ValueError):
                value.get_cipher_caps()

    def test_server_encryption_validation(self):
        value = client()
        value.warn_and_quit = Mock()
        encryption = {
            "cipher": "AES", "mode": "GCM", "iv": "iv", "key_salt": b"salt",
            "key_hash": "SHA1", "key_size": 32, "key_stretch": "PBKDF2",
            "key_stretch_iterations": 10, "padding": "PKCS#7",
        }
        with patch.object(aes, "get_ciphers", return_value=("AES",)), \
                patch.object(aes, "get_key_hashes", return_value=("SHA1",)), \
                patch.object(aes, "ALL_PADDING_OPTIONS", ("PKCS#7",)):
            self.assertTrue(value.set_server_encryption(typedict({"encryption": encryption}), b"key"))
            value._protocol.set_cipher_out.assert_called_once()
            for key, invalid in (("key_stretch", "bad"), ("cipher", "bad"),
                                 ("padding", "bad"), ("key_hash", "bad")):
                bad = dict(encryption)
                bad[key] = invalid
                with self.subTest(key=key):
                    self.assertFalse(value.set_server_encryption(typedict({"encryption": bad}), b"key"))
        self.assertEqual(value.warn_and_quit.call_count, 4)

    def test_setup_connection(self):
        value = client({"encryption": "AES-GCM"})
        value.get_encryption_key = Mock(return_value=b"key")
        with patch.object(aes, "ENCRYPT_FIRST_PACKET", True):
            value.setup_connection(value._protocol._conn)
        value._protocol.set_cipher_out.assert_called_once()
        rfb = client({"encryption": "AES-GCM"}, "rfb")
        rfb.setup_connection(rfb._protocol._conn)
        rfb._protocol.set_cipher_out.assert_not_called()

    def test_parse_server_capabilities(self):
        value = client()
        value.get_encryption = Mock(return_value="AES-GCM")
        value.get_encryption_key = Mock(return_value=b"key")
        value.set_server_encryption = Mock(return_value=True)
        caps = typedict({"encryption": {}})
        self.assertTrue(value.parse_server_capabilities(caps))
        value.set_server_encryption.assert_called_once_with(caps, b"key")
        value._protocol = None
        self.assertFalse(value.parse_server_capabilities(caps))


if __name__ == "__main__":
    unittest.main()
