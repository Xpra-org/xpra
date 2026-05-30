#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.server.session_registry.auth import Registry as AuthRegistry
from xpra.server.session_registry.multifile import Registry as MultifileRegistry


class FakeAuth:
    """Minimal stub: only the attributes/methods the registries actually use."""

    def __init__(self, username="alice", sessions=None, uid=1000, gid=1000):
        self.username = username
        self._sessions = sessions
        self._uid = uid
        self._gid = gid

    def get_sessions(self):
        return self._sessions

    def get_uid(self):
        return self._uid

    def get_gid(self):
        return self._gid


class TestAuthRegistry(unittest.TestCase):

    def test_delegates_to_authenticator(self):
        a = FakeAuth(sessions=(1000, 1000, [":10"], {"A": "1"}, {"B": "2"}))
        r = AuthRegistry()
        s = r.lookup(a)
        self.assertEqual(s.uid, 1000)
        self.assertEqual(s.displays, [":10"])
        self.assertEqual(s.env_options, {"A": "1"})
        self.assertEqual(s.session_options, {"B": "2"})

    def test_returns_none_when_authenticator_returns_none(self):
        r = AuthRegistry()
        self.assertIsNone(r.lookup(FakeAuth(sessions=None)))


class TestMultifileRegistry(unittest.TestCase):

    def _make_file(self, contents: str) -> str:
        fd, path = tempfile.mkstemp(prefix="xpra-mf-test-", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(contents)
        self.addCleanup(os.unlink, path)
        return path

    def test_missing_file_returns_none(self):
        r = MultifileRegistry(filename="/nonexistent/path/xpra/users.txt")
        self.assertIsNone(r.lookup(FakeAuth(username="alice")))

    def test_lookup_known_user(self):
        # username|password|uid|gid|displays|env|session_options
        path = self._make_file("alice|secret|1000|1000|:10,:11|FOO=bar|key=val\n")
        r = MultifileRegistry(filename=path)
        s = r.lookup(FakeAuth(username="alice"))
        self.assertIsNotNone(s)
        self.assertEqual(s.uid, 1000)
        self.assertEqual(s.gid, 1000)
        self.assertEqual(s.displays, [":10", ":11"])
        self.assertEqual(s.env_options, {"FOO": "bar"})
        self.assertEqual(s.session_options, {"key": "val"})

    def test_lookup_unknown_user(self):
        path = self._make_file("alice|secret|1000|1000|:10||\n")
        r = MultifileRegistry(filename=path)
        self.assertIsNone(r.lookup(FakeAuth(username="bob")))

    def test_comments_and_blank_lines_ignored(self):
        path = self._make_file("# header\n\nalice|secret|1000|1000|:10||\n")
        r = MultifileRegistry(filename=path)
        self.assertIsNotNone(r.lookup(FakeAuth(username="alice")))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
