#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import typedict
from xpra.client.gui.window_base import do_get_window_title


class FakeClient:

    def __init__(self, **kwargs):
        self.title = kwargs.pop("title", "@title@")
        self._remote_hostname = kwargs.pop("_remote_hostname", "")
        self._remote_display = kwargs.pop("_remote_display", "")
        for k, v in kwargs.items():
            setattr(self, k, v)


class WindowTitleTest(unittest.TestCase):

    def _title(self, template, metadata=None, wid=1, **client_kwargs):
        client = FakeClient(title=template, **client_kwargs)
        md = typedict(metadata or {})
        return do_get_window_title(client, wid, md)

    def test_no_at_returns_literal(self):
        self.assertEqual(self._title("plain title"), "plain title")

    def test_strip_nulls(self):
        self.assertEqual(self._title("a\0b\0c"), "abc")

    def test_double_at_escapes_to_single(self):
        self.assertEqual(self._title("@@hello@@"), "@hello@")

    def test_title_substitution(self):
        out = self._title("@title@", {"title": "hello"})
        self.assertEqual(out, "hello")

    def test_title_default_when_missing(self):
        # template uses @title@ but metadata has no "title" key
        out = self._title("[@title@]")
        self.assertEqual(out, "[<untitled window>]")

    def test_windowid_substitution(self):
        out = self._title("wid=@windowid@", wid=42)
        self.assertEqual(out, "wid=42")

    def test_server_machine_and_display(self):
        out = self._title(
            "@title@ [ @server-machine@:@server-display@ ]",
            {"title": "xterm"},
            _remote_hostname="major.example.org",
            _remote_display=":73",
        )
        self.assertEqual(out, "xterm [ major.example.org::73 ]")

    def test_server_machine_unknown(self):
        out = self._title("[@server-machine@]")
        self.assertEqual(out, "[<unknown machine>]")

    def test_server_display_unknown(self):
        out = self._title("[@server-display@]")
        self.assertEqual(out, "[<unknown display>]")

    def test_server_display_backslash_replaced(self):
        out = self._title("@server-display@", _remote_display="1\\WinSta0\\Default")
        self.assertEqual(out, "1-WinSta0-Default")

    def test_unknown_var(self):
        out = self._title("@bogus@")
        self.assertEqual(out, "<unknown bogus>")

    def test_metadata_overrides_default(self):
        out = self._title(
            "@server-display@",
            {"server-display": "from-metadata"},
            _remote_display=":0",
        )
        self.assertEqual(out, "from-metadata")

    def test_concatenated_vars(self):
        # adjacent @a@@b@ should match as two separate substitutions
        out = self._title(
            "@server-machine@@server-display@",
            _remote_hostname="host",
            _remote_display=":1",
        )
        self.assertEqual(out, "host:1")

    def test_dashes_in_var_name(self):
        out = self._title("@client-machine@")
        self.assertEqual(out, "<unknown machine>")

    def test_non_string_metadata_value(self):
        out = self._title("wid=@foo@", {"foo": 123})
        self.assertEqual(out, "wid=123")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
