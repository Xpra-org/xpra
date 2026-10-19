#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server import server_core
from xpra.util import typedict


class VerifyAuthTest(unittest.TestCase):

    def verify(self, challenged, result=True, exception=None):
        authenticator = Mock(passed=False, challenge_sent=challenged)
        authenticator.requires_challenge.return_value = challenged
        authenticator.authenticate.return_value = result
        authenticator.authenticate.side_effect = exception
        proto = SimpleNamespace(
            _conn=SimpleNamespace(socktype_wrapped="socket", socktype="socket"),
            is_closed=lambda: False,
            authenticators=[authenticator],
        )
        server = server_core.ServerCore.__new__(server_core.ServerCore)
        server.setup_encryption = Mock(return_value={})
        server.auth_failed = Mock()
        server.auth_verified = Mock()
        caps = typedict()
        with patch.object(server_core, "authlog"):
            server.verify_auth(proto, ("hello", caps), caps)
        authenticator.authenticate.assert_called_once_with(caps)
        return server

    def test_authenticator_exception(self):
        for challenged in (False, True):
            with self.subTest(challenged=challenged):
                server = self.verify(challenged, exception=ValueError("test authentication error"))
                server.auth_failed.assert_called_once()
                server.auth_verified.assert_not_called()

    def test_authenticator_result(self):
        for challenged in (False, True):
            for result in (False, True):
                with self.subTest(challenged=challenged, result=result):
                    server = self.verify(challenged, result=result)
                    self.assertEqual(server.auth_failed.call_count, int(not result))
                    self.assertEqual(server.auth_verified.call_count, int(result))


if __name__ == '__main__':
    unittest.main()
