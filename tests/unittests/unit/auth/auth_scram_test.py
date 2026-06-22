#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import base64
import os
import tempfile
import unittest

from xpra.util.objects import typedict


class FakeSocket:
    def get_channel_binding(self, name):
        if name == "tls-unique":
            return b"tls-binding"
        return None


class FakeConnection:
    _socket = FakeSocket()


class FakeProtocol:
    _conn = FakeConnection()


def stored_record(mechanism: str, password: str) -> str:
    from scramp import ScramMechanism
    salt, stored_key, server_key, iterations = ScramMechanism(mechanism).make_auth_info(password)

    def b64(v: bytes) -> str:
        return base64.b64encode(v).decode("ascii")

    return f"SCRAM${mechanism}${iterations}${b64(salt)}${b64(stored_key)}${b64(server_key)}"


class ScramAuthTest(unittest.TestCase):

    def temp_password_file(self, data: str):
        f = tempfile.NamedTemporaryFile(mode="w", prefix="scram-auth-", delete=False)
        f.write(data)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def make_authenticator(self, data: str, **kwargs):
        from xpra.auth.scram import Authenticator
        kwargs.setdefault("username", "foo")
        kwargs.setdefault("connection", FakeConnection())
        return Authenticator(filename=self.temp_password_file(data), **kwargs)

    def make_handler(self, password: str, **kwargs):
        from xpra.challenge.scram import Handler
        kwargs.setdefault("display-desc", {"username": "foo"})
        return Handler(password=password, **kwargs)

    def scram_roundtrip(self, password: str, data: str, **kwargs):
        auth = self.make_authenticator(data, **kwargs)
        handler_kwargs = {}
        if kwargs.get("connection"):
            handler_kwargs["protocol"] = FakeProtocol()
        handler = self.make_handler(password, **handler_kwargs)
        salt, digest = auth.get_challenge(handler.get_digests())
        assert digest.endswith(":client-first")

        client_first = handler.handle(salt, digest, "password")
        assert auth.authenticate(typedict({"challenge_response": client_first}))
        challenge, digest, prompt = auth.get_next_challenge()
        assert digest.endswith(":server-first")

        client_final = handler.handle(challenge, digest, prompt)
        assert auth.authenticate(typedict({"challenge_response": client_final}))
        challenge, digest, prompt = auth.get_next_challenge()
        assert digest.endswith(":server-final")

        ack = handler.handle(challenge, digest, prompt)
        assert ack == b"OK"
        assert auth.authenticate(typedict({"challenge_response": ack}))
        assert auth.passed
        assert handler.is_done()
        return auth, handler

    def test_plaintext_password_roundtrip(self):
        self.scram_roundtrip("secret", "secret")

    def test_stored_key_roundtrip(self):
        self.scram_roundtrip("secret", stored_record("SCRAM-SHA-256", "secret"), mechanisms="SCRAM-SHA-256")

    def test_multifile_roundtrip(self):
        data = "\n".join((
            "# comment",
            "bar|wrong",
            f"foo|{stored_record('SCRAM-SHA-256', 'secret')}|1000|1000|:100",
        ))
        auth, _handler = self.scram_roundtrip("secret", data, mechanisms="SCRAM-SHA-256")
        assert auth.get_sessions()[2] == [":100"]

    def test_wrong_password_fails(self):
        auth = self.make_authenticator("secret", mechanisms="SCRAM-SHA-256")
        handler = self.make_handler("wrong", mechanisms="SCRAM-SHA-256")
        salt, digest = auth.get_challenge(handler.get_digests())
        client_first = handler.handle(salt, digest, "password")
        assert auth.authenticate(typedict({"challenge_response": client_first}))
        challenge, digest, prompt = auth.get_next_challenge()
        client_final = handler.handle(challenge, digest, prompt)
        assert not auth.authenticate(typedict({"challenge_response": client_final}))

    def test_sha1_disabled_by_default(self):
        from xpra.challenge.scram import Handler
        handler = Handler(password="secret", mechanisms="SCRAM-SHA-1")
        assert handler.get_digests() == ()
        handler = Handler(password="secret", mechanisms="SCRAM-SHA-1", **{"legacy-sha1": "yes"})
        assert "SCRAM-SHA-1" in handler.get_digests()

    def test_plus_requires_channel_binding(self):
        from xpra.challenge.scram import Handler
        handler = Handler(password="secret", mechanisms="SCRAM-SHA-256")
        assert "SCRAM-SHA-256-PLUS" not in handler.get_digests()
        handler = Handler(password="secret", mechanisms="SCRAM-SHA-256", protocol=FakeProtocol())
        assert "SCRAM-SHA-256-PLUS" in handler.get_digests()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
