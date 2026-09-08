#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from unit.server.subsystem.servermixintest_util import ServerMixinTest
from unit.process_test_util import DisplayContext


class FakeKeyboardDevice:
    """ records the keys the subsystem asks us to release """

    def __init__(self):
        self.cleared: list[tuple[int, ...]] = []

    def clear_keys_pressed(self, keycodes) -> None:
        self.cleared.append(tuple(keycodes))


class InputMixinTest(ServerMixinTest):

    def test_input(self):
        with DisplayContext():
            from xpra.server.subsystem.keyboard import KeyboardManager
            from xpra.server.source.keyboard import KeyboardConnection
            opts = AdHocStruct()
            opts.input_method = "auto"
            self._test_mixin_class(KeyboardManager, opts, {}, KeyboardConnection)

    def make_keyboard_mixin(self):
        from xpra.server.subsystem.keyboard import KeyboardManager
        from xpra.server.source.keyboard import KeyboardConnection
        opts = AdHocStruct()
        opts.input_method = "auto"
        self._test_mixin_class(KeyboardManager, opts, {}, KeyboardConnection)
        device = FakeKeyboardDevice()
        self.mixin.device = device
        self.mixin.keys_pressed = {10: "a"}
        return self.mixin, self.source, device

    def test_exiting_client_settles_the_keys_it_pressed(self):
        with DisplayContext():
            mixin, source, device = self.make_keyboard_mixin()
            source.key_events = 1
            self.emit("client-exited", source)
            self.assertEqual(device.cleared, [(10, )])
            self.assertEqual(mixin.keys_pressed, {})

    def test_exiting_client_which_never_typed_settles_nothing(self):
        with DisplayContext():
            mixin, source, device = self.make_keyboard_mixin()
            # ie: a `record` client, which only watches
            self.assertEqual(source.key_events, 0)
            self.emit("client-exited", source)
            self.assertEqual(device.cleared, [])
            self.assertEqual(mixin.keys_pressed, {10: "a"})

    def test_readonly_settles_the_keys_the_client_pressed(self):
        with DisplayContext():
            mixin, source, device = self.make_keyboard_mixin()
            source.key_events = 1
            self.emit("setting-changed", "readonly", True, source)
            self.assertEqual(device.cleared, [(10, )])
            self.assertEqual(mixin.keys_pressed, {})

    def test_readonly_settles_nothing_for_a_client_which_never_typed(self):
        with DisplayContext():
            mixin, source, device = self.make_keyboard_mixin()
            self.emit("setting-changed", "readonly", True, source)
            self.assertEqual(device.cleared, [])

    def test_server_readonly_settles_the_keys(self):
        with DisplayContext():
            mixin, source, device = self.make_keyboard_mixin()
            # the keys pressed before the switch must still be released,
            # even though the whole server is now readonly:
            self.readonly = True
            self.emit("setting-changed", "readonly", True, None)
            self.assertEqual(device.cleared, [(10, )])
            self.assertEqual(mixin.keys_pressed, {})

    def test_other_settings_are_ignored(self):
        with DisplayContext():
            mixin, source, device = self.make_keyboard_mixin()
            source.key_events = 1
            self.emit("setting-changed", "readonly", False, source)
            self.emit("setting-changed", "session_name", "foo", source)
            self.assertEqual(device.cleared, [])
            self.assertEqual(mixin.keys_pressed, {10: "a"})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
