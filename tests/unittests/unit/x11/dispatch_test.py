#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
