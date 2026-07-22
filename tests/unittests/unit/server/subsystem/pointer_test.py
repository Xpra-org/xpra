#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from xpra.server.subsystem.pointer import PointerManager


def make_server():
    server = AdHocStruct()
    server.idle_add = lambda *args: None
    server.timeout_add = lambda *args: None
    server.source_remove = lambda *args: None
    server.subsystems = {}
    server.ui_driver = None
    server.get_server_source = lambda _proto: None
    return server


class RecordingPointerManager(PointerManager):
    """Records which pipeline hooks were called, in order."""

    def __init__(self, server=None):
        super().__init__(server)
        self.calls: list[tuple] = []
        self.pointer_device = AdHocStruct()
        self.pointer_device.get_position = lambda: (0, 0)
        self.pointer_device.click = lambda *args: self.calls.append(("click",) + args)

    def is_readonly(self, _proto) -> bool:
        return False

    def _adjust_pointer(self, proto, device_id, wid, pointer):
        self.calls.append(("adjust", wid, tuple(pointer)))
        return pointer

    def get_pointer_target(self, proto, wid, pos, props=None):
        self.calls.append(("target", wid, tuple(pos)))
        return pos[0], pos[1]

    def _move_pointer(self, device_id, wid, pos, props=None) -> None:
        self.calls.append(("move", wid, tuple(pos[:2])))

    def may_record_pointer_event(self, packet_type, *data) -> None:
        self.calls.append(("record", packet_type))


class PointerPipelineTest(unittest.TestCase):

    def make_manager(self) -> RecordingPointerManager:
        return RecordingPointerManager(make_server())

    def test_motion_hook_order(self):
        m = self.make_manager()
        self.assertEqual(m.process_mouse_common(object(), 0, 1, (10, 20)), (10, 20))
        self.assertEqual(m.calls, [
            ("adjust", 1, (10, 20)),
            ("target", 1, (10, 20)),
            ("move", 1, (10, 20)),
            ("record", "pointer-motion"),
        ])

    def test_adjust_can_drop_the_event(self):
        m = self.make_manager()
        m._adjust_pointer = lambda *args: None
        self.assertIsNone(m.process_mouse_common(object(), 0, 1, (10, 20)))
        self.assertEqual(m.calls, [])

    def test_target_can_drop_the_event(self):
        m = self.make_manager()
        m.get_pointer_target = lambda *args, **kwargs: None
        self.assertIsNone(m.process_mouse_common(object(), 0, 1, (10, 20)))
        self.assertEqual(m.calls, [("adjust", 1, (10, 20))])

    def test_readonly_drops_the_event(self):
        m = self.make_manager()
        m.is_readonly = lambda _proto: True
        self.assertIsNone(m.process_mouse_common(object(), 0, 1, (10, 20)))
        self.assertEqual(m.calls, [])

    def test_redundant_move_is_skipped(self):
        m = self.make_manager()
        m.pointer_device.get_position = lambda: (10, 20)
        self.assertEqual(m.process_mouse_common(object(), 0, 1, (10, 20)), (10, 20))
        self.assertNotIn("move", [c[0] for c in m.calls])
        # ..but not when the backend opts out:
        m2 = self.make_manager()
        m2.SKIP_REDUNDANT_MOVES = False
        m2.pointer_device.get_position = lambda: (10, 20)
        m2.process_mouse_common(object(), 0, 1, (10, 20))
        self.assertIn("move", [c[0] for c in m2.calls])

    def test_button_moves_then_clicks(self):
        m = self.make_manager()
        m.process_pointer_button(object(), 0, 1, 3, True, (10, 20), {})
        self.assertEqual(m.calls, [
            ("adjust", 1, (10, 20)),
            ("target", 1, (10, 20)),
            ("move", 1, (10, 20)),
            ("record", "pointer-motion"),
            ("record", "pointer-button"),
            ("click", 3, True, {}),
        ])

    def test_button_not_clicked_when_event_is_dropped(self):
        m = self.make_manager()
        m._adjust_pointer = lambda *args: None
        m.process_pointer_button(object(), 0, 1, 3, True, (10, 20), {})
        self.assertEqual(m.calls, [])

    def test_button_props_reach_the_device(self):
        m = self.make_manager()
        props = {"modifiers": (), "window-position": (1, 2)}
        m.process_pointer_button(object(), 0, 1, 3, True, (10, 20), props)
        self.assertIn(("click", 3, True, props), m.calls)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
