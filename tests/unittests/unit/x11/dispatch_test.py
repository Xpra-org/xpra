#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.util.signal_emitter import SignalEmitter
from xpra.util.gobject import one_arg_signal
from xpra.os_util import gi_import
from xpra.x11.common import X11Event
from xpra.x11 import dispatch

GObject = gi_import("GObject")

XID = 0x1234


class Receiver(SignalEmitter):
    __signals__ = ("x11-test-event", )


class Other(SignalEmitter):
    __signals__ = ("x11-other-event", )


class ParentReceiver(SignalEmitter):
    __signals__ = ("x11-parent-event", )


class GReceiver(GObject.GObject):
    __gsignals__ = {
        "x11-test-event": one_arg_signal,
    }

    def __init__(self):
        super().__init__()
        self.events = []

    def do_x11_test_event(self, event) -> None:
        self.events.append(event)


GObject.type_register(GReceiver)


def make_event(window: int = XID) -> X11Event:
    event = X11Event(0, "Test", False, 0, window)
    event.window = window
    return event


class TestDispatch(unittest.TestCase):

    def tearDown(self):
        dispatch.cleanup_all_event_receivers()
        dispatch.catchall_receivers.clear()
        dispatch.fallback_receivers.clear()
        dispatch.debug_route_events.clear()

    def receiver(self, signal="x11-test-event"):
        events = []
        receiver = ParentReceiver() if signal == "x11-parent-event" else Receiver()
        receiver.connect(signal, lambda _emitter, event: events.append(event))
        return receiver, events

    def test_signal_emitter_receiver(self):
        events = []
        receiver = Receiver()
        receiver.connect("x11-test-event", lambda _emitter, event: events.append(event))
        other = Other()
        other.connect("x11-other-event", lambda *args: self.fail("should not be called"))
        dispatch.add_event_receiver(XID, receiver)
        dispatch.add_event_receiver(XID, other)
        event = make_event()
        dispatch.route_event(0, event, "x11-test-event", "")
        self.assertEqual(events, [event])
        dispatch.remove_event_receiver(XID, receiver)
        dispatch.route_event(0, make_event(), "x11-test-event", "")
        self.assertEqual(len(events), 1)

    def test_gobject_receiver(self):
        receiver = GReceiver()
        dispatch.add_event_receiver(XID, receiver)
        event = make_event()
        dispatch.route_event(0, event, "x11-test-event", "")
        self.assertEqual(receiver.events, [event])

    def test_catchall(self):
        events = []
        receiver = Receiver()
        receiver.connect("x11-test-event", lambda _emitter, event: events.append(event))
        dispatch.add_catchall_receiver("x11-test-event", receiver)
        dispatch.route_event(0, make_event(0x5678), "x11-test-event", "")
        self.assertEqual(len(events), 1)
        dispatch.remove_catchall_receiver("x11-test-event", receiver)
        # removing twice is harmless:
        dispatch.remove_catchall_receiver("x11-test-event", receiver)
        dispatch.route_event(0, make_event(0x5678), "x11-test-event", "")
        self.assertEqual(len(events), 1)

    def test_receiver_removal(self):
        receiver, _events = self.receiver()
        dispatch.remove_event_receiver(XID, receiver)
        dispatch.add_event_receiver(XID, receiver)
        dispatch.add_event_receiver(XID, receiver)
        self.assertEqual(dispatch.event_receivers_map[XID], {receiver})
        dispatch.remove_event_receiver(XID, receiver)
        self.assertNotIn(XID, dispatch.event_receivers_map)

    def test_parent_delivery(self):
        child, child_events = self.receiver()
        parent, parent_events = self.receiver("x11-parent-event")
        dispatch.add_event_receiver(XID, child)
        dispatch.add_event_receiver(0x5678, parent)
        event = make_event()
        event.delivered_to = 0x5678
        dispatch.add_debug_route_event(12)
        with patch.object(dispatch, "log"):
            dispatch.route_event(12, event, "x11-test-event", "x11-parent-event")
        self.assertEqual(child_events, [])
        self.assertEqual(parent_events, [event])

    def test_fallback_and_catchall_precedence(self):
        normal, normal_events = self.receiver()
        fallback, fallback_events = self.receiver()
        parent, parent_events = self.receiver("x11-parent-event")
        catchall, catchall_events = self.receiver()
        catchparent, catchparent_events = self.receiver("x11-parent-event")
        dispatch.add_fallback_receiver("x11-test-event", fallback)
        dispatch.add_fallback_receiver("x11-parent-event", parent)
        dispatch.add_catchall_receiver("x11-test-event", catchall)
        dispatch.add_catchall_receiver("x11-parent-event", catchparent)
        first = make_event()
        dispatch.route_event(0, first, "x11-test-event", "x11-parent-event")
        self.assertEqual(fallback_events, [first])
        self.assertEqual(parent_events, [first])
        dispatch.add_event_receiver(XID, normal)
        second = make_event()
        dispatch.route_event(0, second, "x11-test-event", "x11-parent-event")
        self.assertEqual(normal_events, [second])
        self.assertEqual(fallback_events, [first])
        self.assertEqual(parent_events, [first])
        self.assertEqual(catchall_events, [first, second])
        self.assertEqual(catchparent_events, [first, second])
        dispatch.remove_event_receiver(XID, normal)
        dispatch.remove_fallback_receiver("x11-test-event", fallback)
        dispatch.remove_fallback_receiver("x11-parent-event", parent)
        dispatch.remove_fallback_receiver("absent", fallback)
        dispatch.route_event(0, make_event(), "x11-test-event", "x11-parent-event")
        self.assertEqual(fallback_events, [first])
        self.assertEqual(parent_events, [first])
        self.assertEqual(len(catchall_events), 3)

    def test_callbacks_can_change_receiver_set(self):
        received = []
        first = Receiver()
        second = Receiver()
        late = Receiver()

        def callback(receiver, event):
            received.append(receiver)
            dispatch.remove_event_receiver(XID, receiver)
            dispatch.add_event_receiver(XID, late)

        first.connect("x11-test-event", callback)
        second.connect("x11-test-event", callback)
        late.connect("x11-test-event", lambda receiver, _event: received.append(receiver))
        dispatch.add_event_receiver(XID, first)
        dispatch.add_event_receiver(XID, second)
        dispatch.route_event(0, make_event(), "x11-test-event", "")
        self.assertCountEqual(received, [first, second])
        dispatch.route_event(0, make_event(), "x11-test-event", "")
        self.assertEqual(received[-1], late)
        self.assertEqual(len(received), 3)

    def test_debug_delivery_and_unhandled_events(self):
        receiver, events = self.receiver()
        dispatch.add_event_receiver(XID, receiver)
        dispatch.add_event_receiver(XID, Other())
        dispatch.add_debug_route_event(12)
        event = make_event()
        with patch.object(dispatch, "log") as log:
            dispatch.route_event(12, event, "x11-test-event", "")
            self.assertEqual(events, [event])
            self.assertTrue(log.info.called)
            dispatch.route_event(12, event, "", "")
            dispatch.route_event(12, make_event(0), "x11-test-event", "")
            dispatch.route_event(12, make_event(999), "x11-test-event", "")
            event.delivered_to = 0
            dispatch.route_event(12, event, "x11-test-event", "x11-parent-event")
            dispatch.route_event(12, event, "x11-test-event", "")
        self.assertEqual(events, [event])
        dispatch.remove_debug_route_event(12)
        self.assertEqual(dispatch.debug_route_events, [])

    def test_debug_event_configuration(self):
        names = {"MapNotify": 19, "UnmapNotify": 18, "PropertyNotify": 28}
        for value, expected in (
            ("", set()), (" MapNotify, unknown, ", {19}),
            ("*, -UnmapNotify", {19, 28}), ("all,-all", set()),
            ("MapNotify,MapNotify", {19}),
        ):
            with self.subTest(value=value), patch.dict("os.environ", {"XPRA_X11_DEBUG_EVENTS": value}), \
                    patch("xpra.x11.bindings.events.names_to_event_type", names), patch.object(dispatch, "log"):
                dispatch.set_debug_events()
                self.assertEqual(set(dispatch.debug_route_events), expected)

    def test_root_detection_and_receiver_limits(self):
        with patch("xpra.x11.bindings.core.get_root_xid", return_value=XID):
            self.assertTrue(dispatch.is_root(XID))
            self.assertFalse(dispatch.is_root(999))
        with patch.object(dispatch, "log") as log, patch.object(dispatch, "is_root", return_value=False), \
                patch("xpra.x11.window_info.window_info", return_value="window"):
            for _ in range(3):
                dispatch.add_event_receiver(XID, Receiver(), max_receivers=1)
            self.assertEqual(log.warn.call_count, 3)
            log.reset_mock()
            dispatch.add_event_receiver(XID, Receiver(), max_receivers=0)
            log.warn.assert_not_called()
            with patch.object(dispatch, "is_root", return_value=True):
                dispatch.add_event_receiver(XID, Receiver(), max_receivers=1)
            log.warn.assert_not_called()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
