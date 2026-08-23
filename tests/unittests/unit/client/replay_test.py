#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.client.base.replay import Replay
from xpra.scripts.config import make_defaults_struct
from xpra.util.objects import typedict


class ReplayInputStateTest(unittest.TestCase):

    def setUp(self):
        self.replay = Replay(make_defaults_struct())
        self.states = []
        self.replay.set_input_state_callback(
            lambda buttons, keys: self.states.append((buttons, keys)))

    def process(self, event: dict) -> None:
        self.replay.process_input_event(typedict(event))

    @staticmethod
    def key_event(timestamp: int, press: bool, name: str = "A",
                  keycode: int = 38, modifier: bool = False) -> dict:
        return {
            "event": "key",
            "timestamp": timestamp,
            "key": {
                "press": press,
                "name": name,
                "keycode": keycode,
                "is-modifier": modifier,
            },
        }

    def test_pointer_buttons(self):
        self.process({"event": "pointer-button", "button": 1, "pressed": True})
        self.process({"event": "pointer-button", "button": 3, "pressed": True})
        self.assertEqual(self.states[-1][0], (1, 3))
        self.process({"event": "pointer-button", "button": 1, "pressed": False})
        self.assertEqual(self.states[-1][0], (3,))

    def test_pressed_keys(self):
        self.process(self.key_event(0, True))
        self.process(self.key_event(1, True, "Shift_L", 50, True))
        self.assertEqual(self.states[-1][1], (("A", False), ("Shift_L", True)))
        self.process(self.key_event(2, False))
        self.assertEqual(self.states[-1][1], (("Shift_L", True),))

    def test_key_without_keycode_uses_its_name(self):
        press = self.key_event(0, True)
        release = self.key_event(1, False)
        press["key"].pop("keycode")
        release["key"].pop("keycode")
        self.process(press)
        self.process(release)
        self.assertEqual(self.states[-1][1], ())

    def test_rebuild_input_state_at_seek_target(self):
        self.replay.input_events = [
            {"event": "pointer-button", "timestamp": 10,
             "button": 1, "pressed": True},
            self.key_event(20, True),
            {"event": "pointer-button", "timestamp": 30,
             "button": 1, "pressed": False},
            self.key_event(40, False),
        ]
        self.replay.rebuild_input_state(25)
        self.assertEqual(self.states[-1], ((1,), (("A", False),)))
        self.replay.rebuild_input_state(35)
        self.assertEqual(self.states[-1], ((), (("A", False),)))
        self.replay.rebuild_input_state(45)
        self.assertEqual(self.states[-1], ((), ()))

    def test_modifier_keys_are_discovered(self):
        self.replay.input_events = [
            self.key_event(0, True, "Control_L", 37, True),
            self.key_event(1, False, "Control_L", 37, True),
            self.key_event(2, True, "Caps_Lock", 66, True),
        ]
        self.assertEqual(self.replay.get_modifier_keys(), ("Control_L", "Caps_Lock"))


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
