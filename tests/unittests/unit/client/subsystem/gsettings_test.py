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

    def test_platform_auto_values(self):
        values = {
            ("org.gnome.desktop.wm.preferences", "button-layout"): "'close,minimize,maximize:'",
            ("org.gnome.desktop.interface", "color-scheme"): "'prefer-dark'",
            ("org.gnome.desktop.a11y.interface", "high-contrast"): "true",
        }
        with (
            patch("xpra.client.subsystem.gsettings.OSX", True),
            patch("xpra.client.subsystem.gsettings.WIN32", False),
            patch("xpra.platform.gsettings.get_auto_gsettings", return_value=values) as get_auto,
        ):
            owner = Client()
            client = GSettingsClient(owner)
            opts = AdHocStruct()
            opts.gsettings_sync = "auto"
            client.init(opts)
            self.assertEqual(client.allowlist, ())
            self.assertEqual(client.values, values)
            with patch("xpra.os_util.gi_import", side_effect=AssertionError) as gi_import:
                client.setup_gsettings()
            gi_import.assert_not_called()
        get_auto.assert_called_once_with()
        self.assertEqual(owner.packets, [("gsettings-update", {
            "org.gnome.desktop.wm.preferences:button-layout": "'close,minimize,maximize:'",
            "org.gnome.desktop.interface:color-scheme": "'prefer-dark'",
            "org.gnome.desktop.a11y.interface:high-contrast": "true",
        })])

    def test_platform_defaults_only_apply_to_auto(self):
        with (
            patch("xpra.client.subsystem.gsettings.OSX", False),
            patch("xpra.client.subsystem.gsettings.WIN32", True),
            patch("xpra.platform.gsettings.get_auto_gsettings") as get_auto,
        ):
            client = GSettingsClient(Client())
            opts = AdHocStruct()
            opts.gsettings_sync = "yes"
            client.init(opts)
        get_auto.assert_not_called()
        self.assertTrue(client.allowlist)
        self.assertEqual(client.values, {})

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
