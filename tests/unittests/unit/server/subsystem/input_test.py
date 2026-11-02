#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.server.source.keyboard import KeyboardConnection
from xpra.server.subsystem.keyboard import KeyboardManager
from xpra.util.objects import AdHocStruct, typedict
from unit.server.subsystem.servermixintest_util import ServerMixinTest
from unit.process_test_util import DisplayContext
from unit.test_util import stubbable


class FakeKeyboardDevice:
    """ records the keys the subsystem asks us to release """

    def __init__(self):
        self.cleared: list[tuple[int, ...]] = []

    def clear_keys_pressed(self, keycodes) -> None:
        self.cleared.append(tuple(keycodes))


class KeyboardHelloTest(unittest.TestCase):

    @staticmethod
    def make_source(keyboard_input=True, record=False):
        source = KeyboardConnection()
        source.init_state()
        source.keyboard_input = keyboard_input
        source.keyboard_record = record
        source.make_keymask_match = Mock()
        source.record_key = Mock()
        return source

    @staticmethod
    def make_manager(sources):
        server = Mock()
        server.get_sources_by_type.side_effect = lambda cls, exclude=None: tuple(
            source for source in sources if isinstance(source, cls) and source is not exclude
        )
        manager = stubbable(KeyboardManager)(server)
        manager.device = Mock()
        manager.get_keyboard_config = Mock(return_value=Mock())
        manager.set_keymap = Mock()
        return manager

    def test_recorder_does_not_configure_keyboard(self):
        recorder = self.make_source(keyboard_input=False, record=True)
        for sources in ([recorder], [self.make_source(), recorder]):
            with self.subTest(sources=sources):
                manager = self.make_manager(sources)
                current_config = manager.config = Mock()
                manager.key_repeat_delay, manager.key_repeat_interval = (750, 45)
                manager.parse_hello_ui_keyboard(recorder, typedict({"keyboard": {"input": False, "record": True}}))
                manager.get_keyboard_config.assert_not_called()
                manager.set_keymap.assert_not_called()
                manager.device.set_repeat_rate.assert_not_called()
                recorder.make_keymask_match.assert_not_called()
                self.assertIsNone(recorder.keyboard_config)
                self.assertIs(manager.config, current_config)
                self.assertEqual((manager.key_repeat_delay, manager.key_repeat_interval), (750, 45))

    def test_first_input_client_ignores_recorders(self):
        source = self.make_source()
        recorder = self.make_source(keyboard_input=False, record=True)
        manager = self.make_manager([recorder, source])
        caps = typedict({"keyboard": True, "key_repeat": (750, 45), "modifiers": ("shift",)})
        manager.parse_hello_ui_keyboard(source, caps)
        manager.device.set_repeat_rate.assert_called_once_with(750, 45)
        source.make_keymask_match.assert_called_once_with(("shift",))
        manager.set_keymap.assert_called_once_with(source)
        self.assertIs(source.keyboard_config, manager.get_keyboard_config.return_value)

    def test_another_input_client_still_counts_when_recording(self):
        for record in (False, True):
            with self.subTest(record=record):
                source = self.make_source()
                other = self.make_source(record=record)
                recorder = self.make_source(keyboard_input=False, record=True)
                manager = self.make_manager([other, recorder, source])
                manager.parse_hello_ui_keyboard(source, typedict({"key_repeat": (750, 45)}))
                manager.device.set_repeat_rate.assert_called_once_with(500, 30)
                source.make_keymask_match.assert_not_called()

    def test_passive_recorder_receives_key_events(self):
        recorder = self.make_source(keyboard_input=False, record=True)
        manager = self.make_manager([recorder])
        manager._handle_key(0, True, "a", 97, 38, [])
        recorder.record_key.assert_called_once_with(0, True, "a", 97, 38, [], False, True)
        manager.device.press_key.assert_called_once_with(38, True)


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
            idle_calls = []

            def idle_add(callback, *args):
                idle_calls.append((callback, args))
                return 0

            mixin.idle_add = idle_add
            source.key_events = 1
            self.emit("client-exited", source)
            # Client cleanup is called by a protocol reader thread, whereas
            # X11 keyboard operations must be performed by the main thread.
            self.assertEqual(device.cleared, [])
            self.assertEqual(idle_calls, [(mixin.clear_keys_pressed, ())])
            callback, args = idle_calls[0]
            callback(*args)
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
