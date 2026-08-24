#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from unittest.mock import Mock, call, patch

from xpra.client.base.replay import Replay, WindowModel, WindowReplay
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


class WindowReplayTest(unittest.TestCase):

    @staticmethod
    def make_window_replay() -> WindowReplay:
        replay = Replay(make_defaults_struct())
        window_replay = WindowReplay(replay, 1, "")
        window_replay.window = Mock(spec=WindowModel(1))
        window_replay.events = {
            0: {"event": "new", "timestamp": 0, "geometry": (0, 0, 100, 100)},
            1: {"event": "move-resize", "timestamp": 10, "geometry": (10, 10, 100, 100)},
            2: {"event": "move-resize", "timestamp": 20, "geometry": (20, 20, 100, 100)},
            3: {"event": "sync", "timestamp": 30, "geometry": (30, 30, 100, 100)},
            4: {"event": "move-resize", "timestamp": 40, "geometry": (40, 40, 100, 100)},
            5: {"event": "sync", "timestamp": 50, "geometry": (50, 50, 100, 100)},
            6: {"event": "move-resize", "timestamp": 60, "geometry": (60, 60, 100, 100)},
        }
        window_replay.sync_index = ((0, 0), (30, 3), (50, 5))
        return window_replay

    def test_sync_with_empty_cursor_data(self) -> None:
        replay = Replay(make_defaults_struct())
        window_replay = WindowReplay(replay, 1, "")
        window_replay.window = Mock(spec=WindowModel(1))
        event = typedict({"event": "sync", "metadata": {}, "cursor-data": [], "geometry": (0, 0, 1, 1)})
        with patch.object(typedict, "_warn") as warn:
            window_replay.do_process_event(event)
        warn.assert_not_called()
        window_replay.window.set_cursor_data.assert_called_once_with(())

    def test_forward_seek_is_incremental_within_sync_interval(self) -> None:
        window_replay = self.make_window_replay()
        window_replay.event_index = 2

        window_replay.seek(20, 10)

        window_replay.window.move_resize.assert_called_once_with(20, 20, 100, 100)
        self.assertEqual(window_replay.event_index, 3)

    def test_forward_seek_jumps_to_latest_crossed_sync(self) -> None:
        window_replay = self.make_window_replay()
        window_replay.event_index = 2

        window_replay.seek(60, 10)

        self.assertEqual(window_replay.window.move_resize.call_args_list, [
            call(50, 50, 100, 100),
            call(60, 60, 100, 100),
        ])
        self.assertEqual(window_replay.event_index, 7)


class ReplaySeekTest(unittest.TestCase):

    def test_seek_uses_previous_playhead_for_window_streams(self) -> None:
        replay = Replay(make_defaults_struct())
        window_replay = Mock()
        replay.window_replay = {1: window_replay}
        replay.is_playing = False
        replay.time_index = 10
        replay.focus_timestamp = 8
        replay.grabbed = 1
        replay.grab_timestamp = 8

        replay.seek(20)

        window_replay.seek.assert_called_once_with(20, 10)
        self.assertEqual(replay.focus_timestamp, 8)
        self.assertEqual(replay.grabbed, 1)
        self.assertEqual(replay.grab_timestamp, 8)


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
