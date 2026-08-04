#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.server.subsystem.gsettings import GSettingsServer
from xpra.util.gsettings import gsettings_match
from xpra.util.objects import AdHocStruct
from unit.server.subsystem.servermixintest_util import FakeServerBase


class GSettingsServerTest(unittest.TestCase):

    @staticmethod
    def make_server(option: str) -> GSettingsServer:
        server = GSettingsServer(FakeServerBase())
        opts = AdHocStruct()
        opts.gsettings_sync = option
        server.init(opts)
        return server

    def test_server_defaults_without_client_access(self):
        server = self.make_server("none,org.example:key=server-value")
        self.assertTrue(server.sync_enabled)
        self.assertEqual(server.allowlist, ())
        self.assertEqual(server.defaults, {("org.example", "key"): "server-value"})
        self.assertEqual(server.get_caps(None), {})

    def test_server_defaults_with_client_access(self):
        server = self.make_server("all,org.example:key=server-value")
        self.assertTrue(server.sync_enabled)
        self.assertTrue(gsettings_match(server.allowlist, "any.schema", "any-key"))
        self.assertEqual(server.defaults, {("org.example", "key"): "server-value"})
        self.assertEqual(server.get_caps(None), {"gsettings": True})


def main():
    unittest.main()


if __name__ == "__main__":
    main()
