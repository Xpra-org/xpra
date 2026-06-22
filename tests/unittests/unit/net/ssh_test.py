#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from xpra.net.ssh.paramiko.util import keymd5
from xpra.net.ssh.util import get_default_keyfiles


class SSHTest(unittest.TestCase):

    def test_keymd5(self):
        k = AdHocStruct()
        k.get_fingerprint = lambda : b"abcd"
        assert keymd5(k).startswith("MD5:")

    def test_default_keyfiles(self):
        assert isinstance(get_default_keyfiles(), list)

    def test_parse_proxyjump(self):
        from xpra.net.ssh.paramiko.client import parse_proxyjump
        # disabled / empty:
        for v in ("", "  ", "none", "None", "NONE", " none ", None):
            assert parse_proxyjump(v) == [], f"expected no jump hosts for {v!r}"
        # comments are stripped:
        assert parse_proxyjump("bastion  # via the office") == [{"host": "bastion", "port": 0, "username": ""}]

        def chk(value, expected):
            actual = parse_proxyjump(value)
            assert actual == expected, f"parse_proxyjump({value!r})={actual!r}, expected {expected!r}"
        chk("host", [{"host": "host", "port": 0, "username": ""}])
        chk("user@host", [{"host": "host", "port": 0, "username": "user"}])
        chk("host:2222", [{"host": "host", "port": 2222, "username": ""}])
        chk("user@host:2222", [{"host": "host", "port": 2222, "username": "user"}])
        # multiple hops (with surrounding whitespace):
        chk("j1, user@j2:2222", [
            {"host": "j1", "port": 0, "username": ""},
            {"host": "j2", "port": 2222, "username": "user"},
        ])
        # bracketed IPv6 literal, with and without a port:
        chk("user@[::1]:2222", [{"host": "::1", "port": 2222, "username": "user"}])
        chk("[fe80::1]", [{"host": "fe80::1", "port": 0, "username": ""}])

    def test_parse_proxyjump_bad_port(self):
        from xpra.scripts.main import InitExit
        from xpra.net.ssh.paramiko.client import parse_proxyjump
        try:
            parse_proxyjump("host:notaport")
        except InitExit:
            pass
        else:
            raise Exception("expected InitExit for an invalid ProxyJump port")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
