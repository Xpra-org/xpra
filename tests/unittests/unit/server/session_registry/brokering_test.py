#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Unit tests for the brokering primitives that can be exercised without
spinning up a real proxy: the `RegPacketDispatcher` swap-and-drain, the
`handover` wiring in the register subsystem, and the registry's
unregister-on-broker semantics.
"""

import unittest
from queue import Queue
from threading import Event, Lock
from unittest.mock import MagicMock

from xpra.net.common import Packet
from xpra.server.session_registry import Session
from xpra.server.session_registry.live import Registry


class FakeProto:
    def __init__(self, target="proxy.example.com:14500"):
        self._conn = MagicMock(target=target)
        self._closed = False
        self.sent: list = []

    def send_now(self, packet):
        self.sent.append(packet)

    def close(self):
        self._closed = True

    def is_closed(self) -> bool:
        return self._closed


class TestRegistryUnregister(unittest.TestCase):

    def test_unregister_removes_endpoint(self):
        r = Registry()
        proto = FakeProto()
        s = Session(uid=1000, gid=1000, displays=[":10"],
                    uuid="u1", session_name="demo", endpoint=proto)
        r.register(s)
        self.assertEqual(r.list_sessions(), [s])
        r.unregister(s)
        self.assertEqual(r.list_sessions(), [])

    def test_session_carries_endpoint(self):
        proto = FakeProto()
        s = Session(uid=0, gid=0, displays=[], uuid="u1", endpoint=proto)
        self.assertIs(s.endpoint, proto)


class TestRegPacketDispatcher(unittest.TestCase):
    """
    Direct tests for the dispatcher object that protects packet routing
    during handover. The atomicity property tested below is the whole
    reason the dispatcher exists.
    """

    def _make(self):
        from xpra.server.subsystem.register import RegPacketDispatcher
        inbox: Queue = Queue()
        server = MagicMock()
        server.process_packet = MagicMock(name="process_packet")
        return RegPacketDispatcher(inbox, server), inbox, server

    def test_pre_handoff_routes_to_inbox(self):
        d, inbox, server = self._make()
        d(FakeProto(), Packet("hello", {}))
        d(FakeProto(), Packet("ping", 0))
        self.assertEqual(inbox.qsize(), 2)
        server.process_packet.assert_not_called()

    def test_post_handoff_routes_directly_to_server(self):
        d, inbox, server = self._make()
        proto = FakeProto()
        d.hand_off(proto)
        d(proto, Packet("hello", {}))
        d(proto, Packet("ping", 0))
        self.assertEqual(inbox.qsize(), 0)
        self.assertEqual(server.process_packet.call_count, 2)

    def test_hand_off_drains_inbox_then_flips(self):
        """
        Three packets are routed before hand_off (they end up on the
        inbox). hand_off must drain them into server.process_packet in
        the order they arrived, and packets dispatched after hand_off
        must arrive *after* the drained ones — i.e. TCP order is
        preserved across the transition.
        """
        d, inbox, server = self._make()
        proto = FakeProto()
        seen_order: list = []
        server.process_packet.side_effect = lambda _p, pkt: seen_order.append(pkt.get_type())

        # pre-handoff arrivals
        d(proto, Packet("hello", {}))
        d(proto, Packet("ping", 1))
        d(proto, Packet("ping", 2))
        self.assertEqual(seen_order, [])

        # handover
        d.hand_off(proto)
        self.assertEqual(seen_order, ["hello", "ping", "ping"])

        # post-handoff arrivals
        d(proto, Packet("ping", 3))
        d(proto, Packet("ping", 4))
        self.assertEqual(seen_order, ["hello", "ping", "ping", "ping", "ping"])
        # inbox is fully drained:
        self.assertEqual(inbox.qsize(), 0)


class TestRegisterHandover(unittest.TestCase):
    """
    Drive `_handle_registration_packets` end-to-end with a fake server,
    inbox and dispatcher, feeding it a `handover` packet, and check that
    the subsystem transfers the proto into the server's accept loop
    without losing packets.
    """

    def _make_subsystem(self, server):
        from xpra.server.subsystem.register import RegisterSubsystem
        sub = RegisterSubsystem.__new__(RegisterSubsystem)
        sub.server = server
        sub._shutdown = Event()
        sub._active = {}
        sub._active_lock = Lock()
        return sub

    def test_handover_packet_promotes_proto(self):
        from xpra.server.subsystem.register import RegPacketDispatcher
        server = MagicMock()
        server._potential_protocols = []
        server._accept_timeout = 30
        server.process_packet = MagicMock()
        server.schedule_verify_connection_accepted = MagicMock()
        sub = self._make_subsystem(server)

        proto = FakeProto()
        inbox: Queue = Queue()
        dispatcher = RegPacketDispatcher(inbox, server)
        # first ack the registration, then deliver handover
        inbox.put(Packet("hello", {}))
        inbox.put(Packet("handover"))

        ack, handed_off = sub._handle_registration_packets(proto, dispatcher, "", inbox)

        self.assertTrue(ack)
        self.assertTrue(handed_off)
        # dispatcher is now in pass-through mode:
        self.assertTrue(dispatcher.handed_off)
        # server bookkeeping:
        self.assertIn(proto, server._potential_protocols)
        server.schedule_verify_connection_accepted.assert_called_once_with(proto, 30)
        # the protocol must NOT have been closed — the server owns it now:
        self.assertFalse(proto.is_closed())

    def test_disconnect_does_not_hand_off(self):
        from xpra.server.subsystem.register import RegPacketDispatcher
        server = MagicMock()
        sub = self._make_subsystem(server)
        proto = FakeProto()
        inbox: Queue = Queue()
        dispatcher = RegPacketDispatcher(inbox, server)
        inbox.put(Packet("hello", {}))
        inbox.put(Packet("disconnect", "bye"))

        ack, handed_off = sub._handle_registration_packets(proto, dispatcher, "", inbox)
        self.assertTrue(ack)
        self.assertFalse(handed_off)
        self.assertFalse(dispatcher.handed_off)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
