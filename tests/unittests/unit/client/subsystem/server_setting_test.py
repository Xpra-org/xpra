#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
The server can change some settings at runtime, using `setting-change` packets.
Settings owned by a subsystem must be updated in that subsystem, and before the UI's
own callbacks run: the win32 and macOS trays register theirs before the handshake.
"""

import unittest

from xpra.net.common import Packet
from xpra.util.objects import typedict
from xpra.util.glib_scheduler import GLibScheduler
from xpra.scripts.config import make_defaults_struct
from xpra.client.gui.ui_client_base import UIXpraClient, CLIENT_SETTINGS


class FakeUIClient:
    """ uses the real `UIXpraClient` setting-change dispatch """
    on_server_setting_changed = UIXpraClient.on_server_setting_changed
    server_setting_changed = UIXpraClient.server_setting_changed
    _process_setting_change = UIXpraClient._process_setting_change

    idle_add = GLibScheduler.idle_add
    timeout_add = GLibScheduler.timeout_add
    source_remove = GLibScheduler.source_remove

    def __init__(self):
        self._on_server_setting_changed = {}
        self.server_setting_updates = {}
        self.subsystems = {}
        self.display_desc = {}

    def after_handshake(self, *_args) -> None:
        pass

    def connect(self, *_args) -> None:
        pass

    def send(self, *_args) -> None:
        pass

    def setting_change(self, setting: str, value) -> None:
        self._process_setting_change(Packet("setting-change", setting, value))


def make_subsystem(subsystem_class, **options):
    client = FakeUIClient()
    subsystem = subsystem_class(client)
    opts = make_defaults_struct()
    for k, v in options.items():
        setattr(opts, k, v)
    subsystem.init(opts)
    return client, subsystem


class ServerSettingTest(unittest.TestCase):

    def check_setting(self, subsystem_class, setting: str, caps: dict, values: tuple, getter, **options) -> None:
        client, subsystem = make_subsystem(subsystem_class, **options)
        # registered after the subsystem's `init()`, but before the handshake, like the win32 tray:
        seen = []
        client.on_server_setting_changed(setting, lambda _setting, _value: seen.append(getter(subsystem)))
        subsystem.parse_server_capabilities(typedict(caps))
        for value in values:
            client.setting_change(setting, value)
        self.assertEqual(seen, list(values), f"{setting!r} not updated in {subsystem_class.__name__}")

    def test_bell(self):
        from xpra.client.subsystem.window import WindowClient
        self.check_setting(WindowClient, "bell", {"bell": True}, (False, True), lambda s: s.server_bell)

    def test_cursors(self):
        from xpra.client.subsystem.cursor import CursorClient
        self.check_setting(CursorClient, "cursors", {"cursor": {"default": ()}}, (False, True),
                           lambda s: s.server_enabled)

    def test_bandwidth_limit(self):
        from xpra.client.subsystem.bandwidth import BandwidthClient
        self.check_setting(BandwidthClient, "bandwidth-limit", {}, (10_000_000, 0), lambda s: s.server_limit)

    def test_webcam(self):
        from xpra.client.subsystem.webcam import WebcamForwarder
        self.check_setting(WebcamForwarder, "webcam", {"webcam": {"enabled": False}}, (True, False),
                           lambda s: s.server_enabled, webcam="no")

    def test_clipboard(self):
        from xpra.client.subsystem.clipboard import ClipboardClient
        self.check_setting(ClipboardClient, "clipboard", {"clipboard": True}, (False, True),
                           lambda s: s.server_clipboard)
        self.check_setting(ClipboardClient, "clipboard-direction", {"clipboard": True}, ("to-server", "both"),
                           lambda s: s.server_clipboard_direction)

    def test_start_new_commands(self):
        from xpra.client.subsystem.command import CommandClient
        self.check_setting(CommandClient, "start-new-commands", {"start-new-commands": True}, (False, True),
                           lambda s: s.server_start_new_commands)

    def test_border(self):
        from xpra.client.subsystem.window import WindowClient
        from xpra.client.subsystem.window.border import DEFAULT_BORDER
        self.check_setting(WindowClient, "border", {}, ("red", "blue"), lambda s: s.border_str, border=DEFAULT_BORDER)

    def test_client_settings(self):
        client = FakeUIClient()
        for setting in CLIENT_SETTINGS:
            client.setting_change(setting, True)
            self.assertIs(getattr(client, "server_" + setting.replace("-", "_")), True)

    def test_subsystem_settings_not_on_client(self):
        client = FakeUIClient()
        client.setting_change("bell", True)
        self.assertFalse(hasattr(client, "server_bell"))
        self.assertEqual(client.server_setting_updates, {"bell": True})


def main():
    unittest.main()


if __name__ == "__main__":
    main()
