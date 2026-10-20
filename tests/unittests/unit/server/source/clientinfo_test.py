#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import typedict
from xpra.server.source.clientinfo import ClientInfoConnection, MAX_CLIENT_STRING


def parse(caps: dict) -> ClientInfoConnection:
    ci = ClientInfoConnection()
    ci.init_state()
    ci.parse_client_caps(typedict(caps))
    return ci


class ClientInfoTest(unittest.TestCase):

    def test_identity_is_single_line(self):
        # these are logged and shown in the "user connected" notifications:
        ci = parse({
            "hostname": "host\x1b[2J",
            "username": "admin‮nimda",
            "user": "line1\nline2",
            "name": "x" * 1000,
        })
        self.assertEqual(ci.hostname, "host[2J")
        self.assertEqual(ci.username, "adminnimda")
        self.assertEqual(ci.user, "line1 line2")
        self.assertEqual(len(ci.name), MAX_CLIENT_STRING)
        for msg in ci.get_connect_info():
            self.assertTrue(msg.isprintable(), f"{msg!r} is not printable")

    def test_platform_is_single_line(self):
        ci = parse({
            "name": "test",
            "username": "test",
            "platform": "linux",
            "platform.sysrelease": "6.0\x1b]0;title\x07",
            "platform.linux_distribution": ("Fedora\n", "44‮", "x" * 1000) + ("y", ) * 100,
            "session-type": "wayland\r\nFAKE",
            "proxy": True,
            "proxy.hostname": "proxy⁦",
            "proxy.platform": "linux",
            "proxy.platform.sysrelease": "\x1b[2J",
            "opengl": {"enabled": True, "backend": "GLX\x1b[2J", "renderer": "fake\n"},
        })
        self.assertEqual(ci.client_session_type, "wayland  FAKE")
        self.assertEqual(len(ci.client_linux_distribution), 4)
        self.assertTrue(all(len(x) <= MAX_CLIENT_STRING for x in ci.client_linux_distribution))
        info = ci.get_connect_info()
        self.assertEqual(len(info), 4)
        for msg in info:
            self.assertTrue(msg.isprintable(), f"{msg!r} is not printable")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
