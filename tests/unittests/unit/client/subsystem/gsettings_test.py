#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.client.subsystem.gsettings import GSettingsClient
from xpra.util.objects import AdHocStruct


class Client:

    def __init__(self):
        self.packets = []

    @staticmethod
    def idle_add(*_args):
        return 0

    @staticmethod
    def timeout_add(*_args):
        return 0

    @staticmethod
    def source_remove(*_args):
        return None

    def send(self, *packet):
        self.packets.append(packet)


class GSettingsClientTest(unittest.TestCase):

    def test_fixed_values(self):
        owner = Client()
        client = GSettingsClient(owner)
        opts = AdHocStruct()
        opts.gsettings_sync = (
            "org.example:theme=Adwaita(s),org.example:enabled=true(bool),"
            "org.example:count=12(u),org.example:names=['one', 'two'](as)"
        )
        client.init(opts)
        self.assertTrue(client.enabled)
        self.assertEqual(client.allowlist, ())
        self.assertEqual(client.values, {
            ("org.example", "theme"): "Adwaita(s)",
            ("org.example", "enabled"): "true(bool)",
            ("org.example", "count"): "12(u)",
            ("org.example", "names"): "['one', 'two'](as)",
        })

        with patch("xpra.os_util.gi_import", side_effect=AssertionError) as gi_import:
            client.setup_gsettings()
        gi_import.assert_not_called()
        self.assertEqual(owner.packets, [("gsettings-update", {
            "org.example:theme": "Adwaita(s)",
            "org.example:enabled": "true(bool)",
            "org.example:count": "12(u)",
            "org.example:names": "['one', 'two'](as)",
        })])

    def test_value_validation_is_deferred(self):
        owner = Client()
        client = GSettingsClient(owner)
        opts = AdHocStruct()
        opts.gsettings_sync = (
            "org.example:missing-type=value,org.example:empty-type=value(),"
            "org.example:bad-type=value(not-a-type)"
        )
        client.init(opts)
        self.assertTrue(client.enabled)
        self.assertEqual(client.values, {
            ("org.example", "missing-type"): "value",
            ("org.example", "empty-type"): "value()",
            ("org.example", "bad-type"): "value(not-a-type)",
        })

    def test_fixed_value_ignores_local_changes(self):
        owner = Client()
        client = GSettingsClient(owner)
        opts = AdHocStruct()
        opts.gsettings_sync = "org.example:.*,org.example:theme=Adwaita(s)"
        client.init(opts)

        class Settings:

            @staticmethod
            def get_value(_key):
                raise AssertionError("the fixed key must not be read")

        client._gsetting_changed(Settings(), "theme", "org.example")
        self.assertEqual(owner.packets, [])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
