#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import json
import os.path
import shutil
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from xpra.client.base import record as record_module
from xpra.client.base.record import RecordClient, can_focus
from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.scripts.config import make_defaults_struct
from xpra.util.objects import typedict
from unit.test_util import silence_warn


class FakeGLib:
    """
    `WindowModel` schedules its sync points with the module level `GLib`,
    so replace it to keep the timers out of the (absent) main loop
    and to make the scheduling observable.
    """

    def __init__(self):
        self.timers: dict[int, Any] = {}
        self.timer_id = 0

    def timeout_add(self, _delay: int, callback, *args) -> int:
        self.timer_id += 1
        self.timers[self.timer_id] = (callback, args)
        return self.timer_id

    def source_remove(self, timer: int) -> None:
        self.timers.pop(timer, None)

    def fire_all(self) -> None:
        for callback, args in tuple(self.timers.values()):
            callback(*args)
        self.timers = {}


class RecordClientTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="xpra-record-test")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.glib = FakeGLib()
        patcher = patch("xpra.client.base.record.GLib", self.glib)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = RecordClient(make_defaults_struct())
        self.client.record_directory = self.tmpdir
        self.client.timeout_add = lambda *args: 0
        self.client.init_authenticated_packet_handlers()
        self.process("startup-complete")

    def find_handler(self, packet_type: str):
        """
        Look the handler up in the dispatcher registry - so that the packet names
        registered by `init_authenticated_packet_handlers` are exercised - but call
        it directly: `dispatch_packet` logs handler errors instead of raising them.
        """
        packet_type = self.client.packet_alias.get(packet_type, packet_type)
        for handlers in (self.client._authenticated_ui_packet_handlers,
                         self.client._authenticated_packet_handlers):
            handler = handlers.get(packet_type)
            if handler:
                return handler
        raise AssertionError(f"no handler registered for {packet_type!r}")

    def process(self, *packet_data) -> None:
        packet = Packet(*packet_data)
        self.find_handler(packet.get_type())(packet)

    def new_window(self, wid: int, metadata: dict | None = None) -> None:
        self.process("window-create", wid, 0, 0, 100, 100, metadata or {})

    def events(self, wid: int) -> list[dict]:
        directory = os.path.join(self.tmpdir, "%x" % wid)
        records = []
        for filename in os.listdir(directory):
            if filename.endswith(".json"):
                with open(os.path.join(directory, filename)) as f:
                    records.append(json.load(f))
        # the file names are event indexes, which are not zero padded:
        records.sort(key=lambda record: record["index"])
        return records

    def event_types(self, wid: int) -> list[str]:
        return [record["event"] for record in self.events(wid)]

    def last_event(self, wid: int, event_type: str = "") -> dict:
        for record in reversed(self.events(wid)):
            if not event_type or record["event"] == event_type:
                return record
        raise AssertionError(f"no {event_type or 'event'!r} recorded for window {wid:#x}")

    def sync(self, wid: int) -> dict:
        """ flush the pending sync timers and return the last sync point of this window """
        self.glib.fire_all()
        return self.last_event(wid, "sync")

    def test_startup_creates_the_desktop_window(self):
        self.assertIn(0, self.client._id_to_window)
        self.assertEqual(self.event_types(0), ["new"])

    def test_hello_advertises_the_recording_capabilities(self):
        window_caps = typedict(typedict(self.client.make_hello()).dictget("window"))
        for capability in ("enabled", "record", "restack", "sync-position", "sync-focus", "grabs"):
            self.assertTrue(window_caps.boolget(capability), f"{capability!r} should be advertised")

    def test_hello_without_windows(self):
        self.client.windows = False
        self.assertEqual(self.client.make_hello(), {})

    def test_window_lifecycle(self):
        self.process("window-create", 1, 10, 20, 30, 40, {"title": "test"})
        window = self.client.get_window(1)
        self.assertEqual(window.geometry, (10, 20, 30, 40))
        self.process("window-metadata", 1, {"title": "renamed"})
        self.assertEqual(window.metadata.get("title"), "renamed")
        self.process("window-move-resize", 1, 1, 2, 3, 4)
        self.assertEqual(window.geometry, (1, 2, 3, 4))
        self.process("window-resized", 1, 50, 60)
        self.assertEqual(window.geometry, (1, 2, 50, 60))
        self.process("window-destroy", 1)
        self.assertIsNone(self.client.get_window(1))
        self.assertEqual(self.event_types(1), ["new", "metadata", "move-resize", "resize", "destroy"])

    def test_relative_position(self):
        self.new_window(1)
        self.process("window-create", 2, 0, 0, 10, 10, {"parent": 1, "relative-position": (5, 7)})
        self.assertEqual(self.client.get_window(2).geometry, (5, 7, 10, 10))

    def test_focus_follows_new_windows(self):
        self.new_window(1)
        self.assertEqual(self.client.focused, 1)
        # a tooltip never steals the focus:
        self.new_window(2, {"window-type": ("TOOLTIP", )})
        self.assertFalse(can_focus(typedict({"window-type": ("TOOLTIP", )})))
        self.assertEqual(self.client.focused, 1)
        # iconifying the focused window drops it:
        self.process("window-metadata", 1, {"iconic": True})
        self.assertEqual(self.client.focused, 0)

    def test_focus_is_saved_at_sync_points(self):
        self.new_window(1)
        self.new_window(2)
        # window 2 stole the focus, so both windows must record the change:
        self.assertTrue(self.sync(1)["focused"] is False)
        self.assertTrue(self.sync(2)["focused"] is True)

    def test_grab(self):
        self.new_window(1)
        self.process("window-grab", 1)
        self.assertEqual(self.client.grabbed, 1)
        self.assertTrue(self.client.get_window(1).grabbed)
        self.assertIn("grab", self.event_types(1))
        self.process("window-ungrab", 1)
        self.assertEqual(self.client.grabbed, 0)
        self.assertFalse(self.client.get_window(1).grabbed)
        self.assertEqual(self.event_types(1)[-1], "ungrab")

    def test_grab_moves_between_windows(self):
        self.new_window(1)
        self.new_window(2)
        self.process("window-grab", 1)
        # the server does not send an `ungrab` when the grab moves:
        self.process("window-grab", 2)
        self.assertEqual(self.client.grabbed, 2)
        self.assertFalse(self.client.get_window(1).grabbed)
        self.assertTrue(self.client.get_window(2).grabbed)
        self.assertEqual(self.event_types(2)[-1], "grab")

    def test_grab_is_saved_at_sync_points(self):
        self.new_window(1)
        self.process("window-grab", 1)
        self.assertTrue(self.sync(1)["grabbed"])
        self.process("window-ungrab", 1)
        self.assertFalse(self.sync(1)["grabbed"])

    def test_ungrab_all(self):
        self.new_window(1)
        self.process("window-grab", 1)
        # this is what the `ungrab` control command sends:
        self.process("window-ungrab", -1)
        self.assertEqual(self.client.grabbed, 0)
        self.assertFalse(self.client.get_window(1).grabbed)
        self.assertEqual(self.event_types(1)[-1], "ungrab")

    def test_ungrab_unknown_window(self):
        self.new_window(1)
        self.process("window-grab", 1)
        self.process("window-ungrab", 99)
        self.assertEqual(self.client.grabbed, 0)

    def test_destroy_releases_the_grab(self):
        self.new_window(1)
        self.process("window-grab", 1)
        self.process("window-destroy", 1)
        self.assertEqual(self.client.grabbed, 0)
        # the window is gone: the release must not be recorded as an `ungrab`
        self.assertEqual(self.event_types(1)[-1], "destroy")

    def test_grab_unknown_window(self):
        with silence_warn(record_module):
            self.process("window-grab", 99)
        self.assertEqual(self.client.grabbed, 0)

    def test_new_events_carry_the_focus_and_grab_state(self):
        self.new_window(1)
        record = self.last_event(1, "new")
        self.assertTrue(record["focused"])
        self.assertFalse(record["grabbed"])

    def test_restack(self):
        self.new_window(1)
        self.new_window(2)
        # raised to the top of the stack:
        self.process("window-restack", 1, 0, 0)
        self.assertEqual(self.client.focused, 1)
        # lowered:
        self.process("window-restack", 1, 1, 0)
        self.assertEqual(self.client.focused, 0)

    def test_raise_window(self):
        self.new_window(1)
        self.new_window(2)
        # the server only sends this for the windows focused by another client:
        self.process("window-raise", 1)
        self.assertEqual(self.client.focused, 1)

    def test_bell(self):
        self.new_window(1)
        self.process("window-bell", 1, 0, 100, 440, 200, 0, 0, "bell")
        record = self.last_event(1, "bell")
        self.assertEqual(record["pitch"], 440)

    def test_draw_binary_data_is_saved_separately(self):
        self.new_window(1)
        pixels = b"\0" * 16
        self.process("window-draw", 1, 0, 0, 100, 100, "png", pixels, 1, 0, {})
        record = self.last_event(1, "draw")
        self.assertNotIn("png", record)
        with open(os.path.join(self.tmpdir, "1", "%i.png" % record["index"]), "rb") as f:
            self.assertEqual(f.read(), pixels)

    def test_grab_packets_are_registered(self):
        for packet_type in ("window-grab", "window-ungrab"):
            self.assertIsNotNone(self.find_handler(packet_type))

    def test_legacy_grab_packet_names(self):
        if not BACKWARDS_COMPATIBLE:
            self.skipTest("backwards compatibility is disabled")
        self.new_window(1)
        self.find_handler("pointer-grab")(Packet("window-grab", 1))
        self.assertEqual(self.client.grabbed, 1)
        self.find_handler("pointer-ungrab")(Packet("window-ungrab", 1))
        self.assertEqual(self.client.grabbed, 0)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
