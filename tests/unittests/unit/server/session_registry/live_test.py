#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import typedict
from xpra.server.session_registry import Session
from xpra.server.session_registry.live import Registry


class FakeAuth:
    def __init__(self, username="alice"):
        self.username = username


def make_session(uuid, name="", displays=None) -> Session:
    return Session(uid=1000, gid=1000, displays=displays or [], uuid=uuid, session_name=name)


class TestLiveRegistry(unittest.TestCase):

    def test_register_and_list(self):
        r = Registry()
        s = make_session("u1", "alpha", [":10"])
        r.register(s)
        self.assertEqual(r.list_sessions(), [s])

    def test_unregister(self):
        r = Registry()
        s = make_session("u1", "alpha")
        r.register(s)
        r.unregister(s)
        self.assertEqual(r.list_sessions(), [])

    def test_duplicate_uuid_replaces(self):
        r = Registry()
        first = make_session("u1", "alpha")
        second = make_session("u1", "alpha-v2")
        r.register(first)
        r.register(second)
        self.assertEqual(r.list_sessions(), [second])

    def test_register_requires_uuid(self):
        r = Registry()
        with self.assertRaises(ValueError):
            r.register(make_session("", "alpha"))

    def test_lookup_by_session_name(self):
        r = Registry()
        s = make_session("u1", "alpha", [":10"])
        r.register(s)
        caps = typedict({"session-name": "alpha"})
        self.assertEqual(r.lookup(FakeAuth(), client_caps=caps), s)

    def test_lookup_by_nested_session_name(self):
        r = Registry()
        s = make_session("u1", "alpha", [":10"])
        r.register(s)
        caps = typedict({"session": {"name": "alpha"}})
        self.assertEqual(r.lookup(FakeAuth(), client_caps=caps), s)

    def test_lookup_by_nested_session_display(self):
        r = Registry(**{"lookup-by": "display"})
        r.register(make_session("u1", "alpha", [":10"]))
        s = make_session("u2", "beta", [":20"])
        r.register(s)
        caps = typedict({"session": {"name": "ignored-in-display-mode", "display": ":20"}})
        self.assertEqual(r.lookup(FakeAuth(), client_caps=caps), s)

    def test_lookup_by_uuid_via_default_matcher(self):
        # default lookup-by is session-name, but uuid is accepted as a fallback
        r = Registry()
        s = make_session("u1", "alpha", [":10"])
        r.register(s)
        caps = typedict({"session-name": "u1"})
        self.assertEqual(r.lookup(FakeAuth(), client_caps=caps), s)

    def test_lookup_by_display(self):
        r = Registry()
        s = make_session("u1", "alpha", [":10"])
        r.register(s)
        caps = typedict({"display": ":10"})
        self.assertEqual(r.lookup(FakeAuth(), client_caps=caps), s)

    def test_lookup_misses_returns_none(self):
        r = Registry()
        r.register(make_session("u1", "alpha"))
        caps = typedict({"session-name": "missing"})
        self.assertIsNone(r.lookup(FakeAuth(), client_caps=caps))

    def test_lookup_no_hint_auto_selects_single_session(self):
        r = Registry()
        s = make_session("u1", "alpha")
        r.register(s)
        self.assertEqual(r.lookup(FakeAuth()), s)

    def test_lookup_no_hint_with_multiple_returns_none(self):
        r = Registry()
        r.register(make_session("u1", "alpha"))
        r.register(make_session("u2", "beta"))
        self.assertIsNone(r.lookup(FakeAuth()))

    def test_lookup_by_uuid_strict(self):
        r = Registry(**{"lookup-by": "uuid"})
        r.register(make_session("u1", "alpha", [":10"]))
        s = make_session("u2", "beta", [":20"])
        r.register(s)
        caps = typedict({"session": {"uuid": "u2"}})
        self.assertEqual(r.lookup(FakeAuth(), client_caps=caps), s)

    def test_rejects_invalid_lookup_by(self):
        with self.assertRaises(ValueError):
            Registry(**{"lookup-by": "not-a-field"})


def main():
    unittest.main()


if __name__ == "__main__":
    main()
