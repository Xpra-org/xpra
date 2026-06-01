#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.scripts.config import InitException
from xpra.server.session_registry import Session, SessionRegistry
from xpra.server.session_registry.helper import load_session_registry, parse_session_registry_string


class TestRegistryHelper(unittest.TestCase):

    def test_parse_simple(self):
        name, options = parse_session_registry_string("auth")
        self.assertEqual(name, "auth")
        self.assertEqual(options, {})

    def test_parse_brackets(self):
        name, options = parse_session_registry_string("multifile(filename=/etc/xpra/users.txt)")
        self.assertEqual(name, "multifile")
        self.assertEqual(options.get("filename"), "/etc/xpra/users.txt")

    def test_parse_colon(self):
        name, options = parse_session_registry_string("sqlite:filename=db.sdb")
        self.assertEqual(name, "sqlite")
        self.assertEqual(options.get("filename"), "db.sdb")

    def test_parse_rejects_base(self):
        with self.assertRaises(ValueError):
            parse_session_registry_string("sqlbase")

    def test_parse_rejects_helper(self):
        with self.assertRaises(ValueError):
            parse_session_registry_string("helper")

    def test_load_auth_default(self):
        r = load_session_registry("auth")
        self.assertIsInstance(r, SessionRegistry)
        self.assertEqual(r.NAME, "auth")

    def test_load_empty_defaults_to_auth(self):
        r = load_session_registry("")
        self.assertEqual(r.NAME, "auth")

    def test_load_unknown_raises(self):
        with self.assertRaises(InitException):
            load_session_registry("nonexistent_registry_xyz")

    def test_load_socket(self):
        r = load_session_registry("socket")
        self.assertEqual(r.NAME, "socket")

    def test_base_cleanup_is_noop(self):
        r = SessionRegistry()
        self.assertIsNone(r.cleanup())


class TestSessionTuple(unittest.TestCase):

    def test_unpack_as_tuple(self):
        s = Session(uid=1000, gid=1001, displays=[":10"],
                    env_options={"X": "1"}, session_options={"Y": "2"})
        uid, gid, displays, env_options, session_options = s
        self.assertEqual(uid, 1000)
        self.assertEqual(gid, 1001)
        self.assertEqual(displays, [":10"])
        self.assertEqual(env_options, {"X": "1"})
        self.assertEqual(session_options, {"Y": "2"})

    def test_slice(self):
        s = Session(uid=42, gid=43, displays=[])
        self.assertEqual(tuple(s[:2]), (42, 43))

    def test_from_tuple_none(self):
        self.assertIsNone(Session.from_tuple(None))

    def test_from_tuple_data(self):
        s = Session.from_tuple((1, 2, [":1"], {}, {}))
        self.assertEqual(s.uid, 1)
        self.assertEqual(s.gid, 2)
        self.assertEqual(s.displays, [":1"])

    def test_extra_fields_default_empty(self):
        s = Session(uid=0, gid=0, displays=[])
        self.assertEqual(s.uuid, "")
        self.assertEqual(s.session_name, "")
        self.assertIsNone(s.endpoint)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
