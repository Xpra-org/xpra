#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from xpra.net.control.common import ControlError
from xpra.server.core import ServerCore
from xpra.server.source.readonly import ReadonlyConnection
from xpra.server.subsystem.client_session import ClientSessionServer
from xpra.server.subsystem.control import ControlHandler
from xpra.server.subsystem.settings import SettingsServer


class ControlTest(unittest.TestCase):

    def setUp(self):
        self.server = ServerCore.__new__(ServerCore)
        self.server.hello_request_handlers = {}
        self.server.readonly = False
        self.server.emit = Mock()
        self.session = ClientSessionServer(self.server)
        self.control = ControlHandler(self.server)
        self.server.subsystems = {
            "client-session": self.session,
            "setting": SettingsServer(self.server),
            "control": self.control,
        }
        self.control.init(SimpleNamespace(control=True))
        self.control.setup()
        self.sources = []
        for uuid in ("one", "two", "three"):
            source = ReadonlyConnection()
            protocol = SimpleNamespace(_conn=SimpleNamespace(options={}))
            source.init_from(protocol, self.server)
            source.uuid = uuid
            source.send_setting_change = Mock()
            self.session.sources[uuid] = source
            self.sources.append(source)

    def test_global_readonly(self):
        first, second, third = self.sources
        second.connection_readonly = True
        third.client_readonly = True
        command = self.control.commands["readonly"]
        self.assertEqual(command.run("yes"), "server readonly: True")
        self.assertTrue(self.server.readonly)
        self.assertTrue(all(source.effective_readonly() for source in self.sources))
        self.assertEqual(command.run("no"), "server readonly: False")
        self.assertFalse(self.server.readonly)
        self.assertFalse(first.effective_readonly())
        self.assertTrue(second.effective_readonly())
        self.assertTrue(third.effective_readonly())
        for source, last_value in ((first, False), (second, True), (third, False)):
            self.assertEqual(source.send_setting_change.call_args_list, [
                call("readonly", True), call("readonly", last_value),
            ])
        self.assertEqual(self.server.emit.call_args_list, [
            call("setting-changed", "readonly", True, None), call("setting-changed", "readonly", False, None),
        ])

    def test_client_readonly_selection_and_notifications(self):
        first, second, third = self.sources
        third.client_readonly = True
        # Connections without readonly support are skipped, including with '*'.
        self.session.sources["legacy"] = SimpleNamespace(uuid="legacy")
        command = self.control.commands["client-readonly"]
        self.assertEqual(command.run(" one, missing, , two ", "yes"), "set client readonly=True for 2 client(s)")
        self.assertTrue(first.control_readonly)
        self.assertTrue(second.control_readonly)
        self.assertFalse(third.control_readonly)
        third.send_setting_change.assert_not_called()
        self.assertEqual(command.run("*", "off"), "set client readonly=False for 3 client(s)")
        self.assertFalse(self.server.readonly)
        self.assertTrue(all(not source.control_readonly for source in self.sources))
        for source in (first, second):
            self.assertEqual(source.send_setting_change.call_args_list, [call("readonly", True), call("readonly", False)])
        third.send_setting_change.assert_called_once_with("readonly", False)
        self.assertEqual(self.server.emit.call_args_list, [
            call("setting-changed", "readonly", True, first), call("setting-changed", "readonly", True, second),
            call("setting-changed", "readonly", False, first), call("setting-changed", "readonly", False, second),
            call("setting-changed", "readonly", True, third),
        ])

    def test_command_validation(self):
        for name, args in (("readonly", ()), ("readonly", ("maybe",)), ("readonly", ("yes", "extra")),
                           ("client-readonly", ("*",)), ("client-readonly", ("*", "maybe")),
                           ("client-readonly", ("*", "yes", "extra"))):
            with self.subTest(command=name, args=args), self.assertRaises(ControlError):
                self.control.commands[name].run(*args)
        self.assertFalse(self.server.readonly)
        self.server.emit.assert_not_called()

    def test_disabled_or_missing_control_preserves_readonly(self):
        self.server.subsystems.pop("control")
        for present in (False, True):
            with self.subTest(present=present):
                if present:
                    control = ControlHandler(self.server)
                    self.server.subsystems["control"] = control
                    control.init(SimpleNamespace(control=False))
                    control.setup()
                    self.assertEqual(set(control.commands), {"hello", "*"})
                self.server.readonly = True
                self.assertTrue(all(source.effective_readonly() for source in self.sources))
                self.server.readonly = False
                self.assertTrue(all(not source.effective_readonly() for source in self.sources))

    def test_worker_default_commands_exclude_readonly(self):
        self.control.commands.clear()
        self.control.add_default_control_commands()
        self.assertEqual(set(self.control.commands), {"hello", "help", "client", "toggle-feature"})


if __name__ == "__main__":
    unittest.main()
