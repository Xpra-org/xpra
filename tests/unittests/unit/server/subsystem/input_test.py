#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

# Initialize XPRA_UNIT_TEST before importing server subsystems.
from unit.server.subsystem.servermixintest_util import ServerMixinTest
from unit.process_test_util import DisplayContext

from xpra.server.source.keyboard import KeyboardConnection
from xpra.server.subsystem.keyboard import KeyboardServer
from xpra.util.objects import AdHocStruct, typedict


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
        manager = KeyboardServer()
        manager.get_sources_by_type = lambda cls, exclude=None: tuple(
            source for source in sources if isinstance(source, cls) and source is not exclude
        )
        manager.keyboard_device = Mock()
        manager.get_keyboard_config = Mock(return_value=Mock())
        manager.set_keymap = Mock()
        return manager

    def test_recorder_does_not_configure_keyboard(self):
        recorder = self.make_source(keyboard_input=False, record=True)
        for sources in ([recorder], [self.make_source(), recorder]):
            with self.subTest(sources=sources):
                manager = self.make_manager(sources)
                current_config = manager.keyboard_config = Mock()
                manager.key_repeat_delay, manager.key_repeat_interval = (750, 45)
                manager.parse_hello_ui_keyboard(recorder, typedict({"keyboard": {"input": False, "record": True}}))
                manager.get_keyboard_config.assert_not_called()
                manager.set_keymap.assert_not_called()
                manager.keyboard_device.set_repeat_rate.assert_not_called()
                recorder.make_keymask_match.assert_not_called()
                self.assertIsNone(recorder.keyboard_config)
                self.assertIs(manager.keyboard_config, current_config)
                self.assertEqual((manager.key_repeat_delay, manager.key_repeat_interval), (750, 45))

    def test_first_input_client_ignores_recorders(self):
        source = self.make_source()
        recorder = self.make_source(keyboard_input=False, record=True)
        manager = self.make_manager([recorder, source])
        caps = typedict({"keyboard": True, "key_repeat": (750, 45), "modifiers": ("shift",)})
        with patch("xpra.server.subsystem.keyboard.DELAY_KEYBOARD_DATA", False):
            manager.parse_hello_ui_keyboard(source, caps)
        manager.keyboard_device.set_repeat_rate.assert_called_once_with(750, 45)
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
                manager.keyboard_device.set_repeat_rate.assert_called_once_with(500, 30)
                source.make_keymask_match.assert_not_called()

    def test_passive_recorder_receives_key_events(self):
        recorder = self.make_source(keyboard_input=False, record=True)
        manager = self.make_manager([recorder])
        manager._handle_key(0, True, "a", 97, 38, [])
        recorder.record_key.assert_called_once_with(0, True, "a", 97, 38, [], False, True)
        manager.keyboard_device.press_key.assert_called_once_with(38, True)


class InputMixinTest(ServerMixinTest):

    def test_input(self):
        with DisplayContext():
            from xpra.server.subsystem.keyboard import KeyboardServer
            from xpra.server.source.keyboard import KeyboardConnection
            opts = AdHocStruct()
            opts.input_method = "auto"
            self._test_mixin_class(KeyboardServer, opts, {}, KeyboardConnection)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
