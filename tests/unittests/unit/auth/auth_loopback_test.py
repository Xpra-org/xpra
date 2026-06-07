#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side "loopback" tests for the authentication handshake.

Each test wires a real client challenge handler (`xpra.challenge.*`) to a real
server authenticator (`xpra.auth.*`) and exchanges the actual `challenge` packet
through the real `ChallengeClient` dispatch (see `auth_loopback_util.py`).

Only the hmac digest pairs are covered here: they flow through the real client
send path end-to-end. `scram` is deferred - the client `send_challenge_reply`
cannot send raw SCRAM responses (`gendigest` returns b"" for SCRAM-* digests and
there is no scram code under `xpra/client/`); its stage exchange is covered by
`auth_scram_test.py`. `kerberos`/`gss`/`fido2`/`u2f` need external services or
hardware tokens.
"""

import os
import tempfile
import unittest

from xpra.util.env import OSEnvContext

from unit.auth.auth_loopback_util import challenge_roundtrip


class AuthLoopbackTest(unittest.TestCase):

    def test_uri_password(self):
        from xpra.challenge.uri import Handler
        from xpra.auth.password import Authenticator
        handler = Handler(password="secret")
        auth = Authenticator(value="secret", username="foo")
        passed, captured, errors = challenge_roundtrip(handler, auth)
        self.assertTrue(captured, "client did not send a challenge reply")
        self.assertFalse(errors, "unexpected failure: %s" % (errors,))
        self.assertTrue(passed, "server rejected a matching password")

    def test_uri_password_wrong(self):
        from xpra.challenge.uri import Handler
        from xpra.auth.password import Authenticator
        handler = Handler(password="wrong")
        auth = Authenticator(value="secret", username="foo")
        passed, captured, _errors = challenge_roundtrip(handler, auth)
        # a response is still sent, but it must not authenticate:
        self.assertTrue(captured, "client did not send a challenge reply")
        self.assertFalse(passed, "server accepted a wrong password")

    def test_env_env(self):
        from xpra.challenge.env import Handler
        from xpra.auth.env import Authenticator
        with OSEnvContext():
            os.environ["XPRA_PASSWORD"] = "secret"
            handler = Handler()
            auth = Authenticator(username="foo")
            passed, captured, errors = challenge_roundtrip(handler, auth)
            self.assertTrue(captured, "client did not send a challenge reply")
            self.assertFalse(errors, "unexpected failure: %s" % (errors,))
            self.assertTrue(passed, "server rejected a matching env password")

    def test_env_missing(self):
        from xpra.challenge.env import Handler
        from xpra.auth.env import Authenticator
        with OSEnvContext():
            os.environ.pop("XPRA_PASSWORD", None)
            handler = Handler()
            auth = Authenticator(username="foo")
            passed, captured, errors = challenge_roundtrip(handler, auth)
            # the handler returns "" so no reply is sent and the client bails:
            self.assertFalse(captured, "client should not send a reply with no password")
            self.assertFalse(passed)
            self.assertTrue(errors, "client should have reported a failure")

    def test_file_file(self):
        from xpra.challenge.file import Handler
        from xpra.auth.file import Authenticator
        f = tempfile.NamedTemporaryFile(prefix="auth-loopback-", delete=False)
        f.write(b"secret")
        f.close()
        self.addCleanup(os.unlink, f.name)
        handler = Handler(filename=f.name)
        auth = Authenticator(filename=f.name, username="foo")
        passed, captured, errors = challenge_roundtrip(handler, auth)
        self.assertTrue(captured, "client did not send a challenge reply")
        self.assertFalse(errors, "unexpected failure: %s" % (errors,))
        self.assertTrue(passed, "server rejected a matching file password")

    def test_prompt_password(self):
        from xpra.challenge.prompt import Handler
        from xpra.auth.password import Authenticator
        handler = Handler(challenge_prompt_function=lambda prompt: "secret")
        auth = Authenticator(value="secret", username="foo")
        passed, captured, errors = challenge_roundtrip(handler, auth)
        self.assertTrue(captured, "client did not send a challenge reply")
        self.assertFalse(errors, "unexpected failure: %s" % (errors,))
        self.assertTrue(passed, "server rejected a matching prompt password")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
