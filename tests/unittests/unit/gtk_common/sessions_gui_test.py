#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.gtk.dialogs.sessions_gui import get_uri


def make_uri(display=":10", mode="tcp", username="", password=""):
    # mimics an mDNS advertisement turned into an `xpra attach` URI:
    text = {
        "display": display,
        "mode": mode,
    }
    if username:
        text["username"] = username
    return get_uri(password, 0, 0, "service", "_xpra._tcp.", "local",
                   "host.local", "192.0.2.1", 14500, text)


class TestSessionsGUI(unittest.TestCase):

    def test_uri_accepts_valid_fields(self):
        # benign values (including a screen suffix and modes with `-`/`+`) are preserved:
        self.assertEqual(make_uri(display=":10.0"), "tcp://192.0.2.1/10.0")
        self.assertEqual(make_uri(username="alice-1.test"), "tcp://alice-1.test@192.0.2.1/10")
        # modes containing `-` / `+` are valid (the port is appended since they have no default):
        self.assertTrue(make_uri(mode="named-pipe").startswith("named-pipe://192.0.2.1"))
        self.assertTrue(make_uri(mode="vnc+ssh").startswith("vnc+ssh://192.0.2.1"))

    def test_uri_rejects_unsafe_display(self):
        # an untrusted advertisement must not be able to smuggle URL syntax
        # (query string, extra host, path traversal, ...) into the attach URI:
        for display in (":10?proxy-host=evil.com&proxy-port=1080", ":10@evil/10", ":10/../x", ":10 22"):
            self.assertEqual(make_uri(display=display), "")

    def test_uri_rejects_unsafe_username(self):
        for username in ("alice?proxy-host=evil", "alice@evil", "alice/x", "a:b"):
            self.assertEqual(make_uri(username=username), "")

    def test_uri_rejects_unsafe_mode(self):
        for mode in ("tcp?x", "tcp://evil", "tcp ssl", "../tcp"):
            self.assertEqual(make_uri(mode=mode), "")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
