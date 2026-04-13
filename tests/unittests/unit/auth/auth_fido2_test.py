#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import json
import base64
import binascii
import unittest
from hashlib import sha256
from struct import pack

from xpra.util.objects import typedict


PUB_KEY_DER_PREFIX = binascii.a2b_hex("3059301306072a8648ce3d020106082a8648ce3d030107034200")


def _generate_keypair():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend
    return ec.generate_private_key(ec.SECP256R1(), default_backend())


def _pub_key_hex(private_key) -> str:
    """Return the raw 64-byte EC point as a hex string (without DER prefix)."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    der = private_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    # strip the fixed prefix to get the raw 65-byte uncompressed point,
    # then drop the 0x04 uncompressed marker → 64 bytes
    raw = der[len(PUB_KEY_DER_PREFIX):]
    return raw.hex()


def _make_authenticator(private_key, app_id="Xpra"):
    """Build an Authenticator instance with an in-memory public key."""
    from xpra.auth.fido2 import Authenticator
    return Authenticator(
        connection=None,
        username="testuser",
        app_id=app_id,
        public_key=_pub_key_hex(private_key),
    )


def _sign_challenge(private_key, salt: bytes, app_id: str = "Xpra",
                    origin: str = "test-origin",
                    user_presence: int = 1,
                    counter: int = 1) -> tuple[bytes, str]:
    """Build a valid fido2 challenge_response and client_salt for the given salt."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    app_param = sha256(app_id.encode()).digest()
    server_b64 = base64.urlsafe_b64encode(salt).decode().rstrip("=")
    client_data = {
        "challenge": server_b64,
        "origin": origin,
        "typ": "navigator.id.getAssertion",
    }
    client_param = sha256(json.dumps(client_data, sort_keys=True).encode()).digest()
    param = app_param + pack(b">B", user_presence) + pack(b">I", counter) + client_param
    sig = private_key.sign(param, ec.ECDSA(hashes.SHA256()))
    response = pack(b">B", user_presence) + pack(b">I", counter) + sig
    return response, origin


class Fido2AuthTest(unittest.TestCase):

    def _caps(self, response: bytes, origin: str) -> typedict:
        return typedict({
            "challenge_response": response,
            "challenge_client_salt": origin,
        })

    def test_valid_authentication(self):
        key = _generate_keypair()
        auth = _make_authenticator(key)
        salt, digest = auth.get_challenge(["fido2"])
        self.assertTrue(salt)
        self.assertEqual(digest, "fido2:xor")
        response, origin = _sign_challenge(key, salt)
        self.assertTrue(auth.fido2_check(self._caps(response, origin)))

    def test_wrong_key_rejected(self):
        key = _generate_keypair()
        wrong_key = _generate_keypair()
        auth = _make_authenticator(key)
        salt, _ = auth.get_challenge(["fido2"])
        # sign with the wrong private key
        response, origin = _sign_challenge(wrong_key, salt)
        self.assertFalse(auth.fido2_check(self._caps(response, origin)))

    def test_tampered_response_rejected(self):
        key = _generate_keypair()
        auth = _make_authenticator(key)
        salt, _ = auth.get_challenge(["fido2"])
        response, origin = _sign_challenge(key, salt)
        # flip a byte in the signature portion
        tampered = response[:5] + bytes([response[5] ^ 0xff]) + response[6:]
        self.assertFalse(auth.fido2_check(self._caps(tampered, origin)))

    def test_unsupported_digest_returns_empty(self):
        key = _generate_keypair()
        auth = _make_authenticator(key)
        salt, digest = auth.get_challenge(["sha256", "md5"])
        self.assertEqual(salt, b"")
        self.assertEqual(digest, "")

    def test_custom_app_id(self):
        key = _generate_keypair()
        app_id = "my.custom.app"
        auth = _make_authenticator(key, app_id=app_id)
        salt, _ = auth.get_challenge(["fido2"])
        response, origin = _sign_challenge(key, salt, app_id=app_id)
        self.assertTrue(auth.fido2_check(self._caps(response, origin)))

    def test_wrong_app_id_rejected(self):
        key = _generate_keypair()
        auth = _make_authenticator(key, app_id="correct.app")
        salt, _ = auth.get_challenge(["fido2"])
        # sign with a different app_id
        response, origin = _sign_challenge(key, salt, app_id="wrong.app")
        self.assertFalse(auth.fido2_check(self._caps(response, origin)))

    def test_invalid_public_key_rejected(self):
        from xpra.auth.fido2 import Authenticator
        with self.assertRaises(Exception):
            Authenticator(
                connection=None,
                username="testuser",
                public_key="deadbeef",   # not a valid EC key
            )

    def test_no_public_key_raises(self):
        from xpra.auth.fido2 import Authenticator
        with self.assertRaises(RuntimeError):
            Authenticator(connection=None, username="testuser")

    def test_repr(self):
        key = _generate_keypair()
        auth = _make_authenticator(key)
        self.assertEqual(repr(auth), "fido2")


if __name__ == "__main__":
    unittest.main()
