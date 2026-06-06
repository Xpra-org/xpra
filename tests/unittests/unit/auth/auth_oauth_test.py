#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.auth.oauth import Authenticator, get_bearer_token, get_header
from xpra.util.objects import typedict


def make_connection(headers: dict[str, str]):
    return SimpleNamespace(options={"http-headers": headers})


class FakeResponse:

    def __init__(self, data: dict):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        return False

    def read(self):
        return json.dumps(self.data).encode("utf-8")


class TestOAuthAuthenticator(unittest.TestCase):

    def test_get_header_case_insensitive(self):
        assert get_header({"authorization": "Bearer token"}, "Authorization") == "Bearer token"
        assert get_header({"Authorization": "Bearer token"}, "authorization") == "Bearer token"
        assert get_header({}, "Authorization") == ""

    def test_get_bearer_token(self):
        assert get_bearer_token("Bearer abc") == "abc"
        assert get_bearer_token("bearer abc") == "abc"
        assert get_bearer_token("Basic abc") == ""
        assert get_bearer_token("") == ""

    def test_static_token_from_websocket_header(self):
        a = Authenticator(connection=make_connection({"Authorization": "Bearer secret"}), token="secret")
        assert not a.requires_challenge()
        assert a.authenticate(typedict()) is True

    def test_static_token_from_capability(self):
        a = Authenticator(connection=make_connection({}), token="secret")
        assert a.authenticate(typedict({"oauth.token": "secret"})) is True

    def test_static_token_mismatch(self):
        a = Authenticator(connection=make_connection({"Authorization": "Bearer wrong"}), token="secret")
        assert a.authenticate(typedict()) is False

    def test_missing_configuration_fails(self):
        a = Authenticator(connection=make_connection({"Authorization": "Bearer secret"}))
        assert a.authenticate(typedict()) is False

    def test_missing_token_fails(self):
        a = Authenticator(connection=make_connection({}), token="secret")
        assert a.authenticate(typedict()) is False

    def test_introspection_active_token(self):
        a = Authenticator(connection=make_connection({"Authorization": "Bearer secret"}),
                          introspection_url="https://idp.example/introspect",
                          client_id="client", client_secret="secret",
                          scope="openid xpra", audience="xpra")

        def fake_urlopen(request, timeout=0):
            assert timeout > 0
            assert request.full_url == "https://idp.example/introspect"
            assert request.get_header("Authorization").startswith("Basic ")
            assert request.data == b"token=secret"
            return FakeResponse({
                "active": True,
                "scope": "openid profile xpra",
                "aud": ["xpra", "other"],
                "username": "alice",
            })

        with patch("xpra.auth.oauth.urlopen", fake_urlopen):
            assert a.authenticate(typedict()) is True
        assert a.username == "alice"

    def test_introspection_inactive_token(self):
        a = Authenticator(connection=make_connection({"Authorization": "Bearer secret"}),
                          introspection_url="https://idp.example/introspect")
        with patch("xpra.auth.oauth.urlopen", lambda request, timeout=0: FakeResponse({"active": False})):
            assert a.authenticate(typedict()) is False

    def test_introspection_scope_mismatch(self):
        a = Authenticator(connection=make_connection({"Authorization": "Bearer secret"}),
                          introspection_url="https://idp.example/introspect", scope="xpra")
        with patch("xpra.auth.oauth.urlopen",
                   lambda request, timeout=0: FakeResponse({"active": True, "scope": "openid"})):
            assert a.authenticate(typedict()) is False

    def test_introspection_audience_mismatch(self):
        a = Authenticator(connection=make_connection({"Authorization": "Bearer secret"}),
                          introspection_url="https://idp.example/introspect", audience="xpra")
        with patch("xpra.auth.oauth.urlopen",
                   lambda request, timeout=0: FakeResponse({"active": True, "aud": "other"})):
            assert a.authenticate(typedict()) is False


def main():
    unittest.main()


if __name__ == "__main__":
    main()
