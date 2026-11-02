#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""The client's own read-only setting is kept apart from the one the server enforces."""

import unittest

from xpra.net.common import Packet
from xpra.client.gui.ui_client_base import UIXpraClient


def make_client(readonly: bool) -> UIXpraClient:
    client = UIXpraClient.__new__(UIXpraClient)
    client.readonly = readonly
    client.server_readonly = False
    client.server_setting_updates = {}
    client._on_server_setting_changed = {}
    return client


class ReadonlyTest(unittest.TestCase):

    def test_server_turns_readonly_off(self) -> None:
        for readonly in (False, True):
            with self.subTest(readonly=readonly):
                client = make_client(readonly)
                client._process_setting_change(Packet("setting-change", "readonly", True))
                self.assertTrue(client.server_readonly)
                self.assertEqual(client.readonly, readonly)
                client._process_setting_change(Packet("setting-change", "readonly", False))
                self.assertFalse(client.server_readonly)
                # the user's own setting is unchanged:
                self.assertEqual(client.readonly, readonly)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
