#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.common import Packet
from xpra.server.subsystem.settings import SettingsServer
from xpra.server.subsystem.stub import StubSubsystem
from unit.server.subsystem.servermixintest_util import FakeServerBase


class FakeSource:

    def __init__(self, uuid: str):
        self.uuid = uuid
        self.settings = []
        self.client_readonly = False
        self.enforced_readonly = False

    def send_setting_change(self, setting: str, value) -> None:
        self.settings.append((setting, value))

    def server_enforced_readonly(self) -> bool:
        return self.enforced_readonly

    def set_client_readonly(self, readonly: bool) -> None:
        self.client_readonly = readonly


class FakeServer(FakeServerBase):
    """ stands in for the source lookups `ServerCore` delegates to `client-session` """

    def __init__(self):
        super().__init__()
        self.sources: dict = {}

    def get_server_source(self, proto):
        return self.sources.get(proto)

    def get_sources_by_type(self, atype=object, exclude=None):
        return tuple(
            ss for ss in self.sources.values()
            if isinstance(ss, atype) and (exclude is None or ss.uuid != exclude.uuid)
        )


class SettingsTest(unittest.TestCase):

    def setUp(self) -> None:
        self.server = FakeServer()
        self.settings = SettingsServer(self.server)
        self.server.subsystems[self.settings.PREFIX] = self.settings

    def test_add_client_setting(self) -> None:
        proto = object()
        source = FakeSource("one")
        self.server.sources[proto] = source
        applied = []
        # subsystems add their own settings to the allow-list via the stub helper:
        subsystem = StubSubsystem(self.server)
        subsystem.add_client_setting("xsettings", "get_dict", lambda ss, value: applied.append((ss, value)))
        settings = {"resource-manager": "Xft.dpi:\t96\n"}
        self.settings._process_change(proto, Packet("setting-change", "xsettings", settings))
        self.assertEqual(applied, [(source, settings)])

    def test_setting_change(self) -> None:
        proto1 = object()
        proto2 = object()
        source1 = FakeSource("one")
        source2 = FakeSource("two")
        self.server.sources.update({proto1: source1, proto2: source2})

        # `readonly` is broadcast per-client, as each one enforces it differently:
        source1.enforced_readonly = True
        source2.enforced_readonly = False
        self.settings.setting_changed("readonly", True)
        self.assertEqual(source1.settings, [("readonly", True)])
        self.assertEqual(source2.settings, [("readonly", False)])
        # any other setting is broadcast as-is:
        self.settings.setting_changed("session_name", "test")
        self.assertEqual(source1.settings[-1], ("session_name", "test"))
        self.assertEqual(source2.settings[-1], ("session_name", "test"))

        self.settings._process_change(proto1, Packet("setting-change", "readonly", True))
        self.assertTrue(source1.client_readonly)
        self.assertFalse(source2.client_readonly)
        # settings not in the allow-list are ignored:
        self.settings._process_change(proto2, Packet("setting-change", "session_name", "hacked"))
        self.assertFalse(source2.client_readonly)
        # unknown protocols are ignored:
        self.settings._process_change(object(), Packet("setting-change", "readonly", True))
        # legacy packet:
        self.settings._process_readonly_toggled(proto2, Packet("readonly-toggled", True))
        self.assertTrue(source2.client_readonly)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
