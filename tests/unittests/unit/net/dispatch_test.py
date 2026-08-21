#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.net.common import Packet
from xpra.net import dispatch
from xpra.net.dispatch import PacketDispatcher, find_packet_handler
from unit.test_util import silence_error


class Subsystem:
    """ minimal stand-in for `StubSubsystem` / `StubClientSubsystem` """

    def __init__(self, prefix: str):
        self.PREFIX = prefix
        self._packet_handlers: dict[str, tuple] = {}

    def add_packet_handler(self, packet_type: str, handler, main_thread=False) -> None:
        subtype = "" if packet_type == self.PREFIX else packet_type[len(self.PREFIX) + 1:]
        self._packet_handlers[subtype] = (handler, main_thread)

    def get_packet_handler(self, subtype: str):
        return self._packet_handlers.get(subtype)

    def remove_packet_handler(self, subtype: str) -> None:
        self._packet_handlers.pop(subtype, None)

    def get_packet_types(self) -> tuple[str, ...]:
        return tuple(f"{self.PREFIX}-{st}" if st else self.PREFIX for st in self._packet_handlers)


class Dispatcher(PacketDispatcher):
    def __init__(self):
        super().__init__()
        self.calls = []

    def call_packet_handler(self, main, handler, proto, packet):
        self.calls.append((main, packet.get_type()))
        handler(proto, packet)


class DispatchTest(unittest.TestCase):

    def test_handler_registration_and_removal(self):
        dispatcher = Dispatcher()
        handler = Mock()
        dispatcher.add_packet_handler("one", handler)
        dispatcher.add_packet_handler("two", handler, main_thread=True)
        self.assertEqual(dispatcher.get_info()["packet-handlers"], {"authenticated": ["one"], "ui": ["two"]})
        dispatcher.remove_packet_handlers("one", "two")
        self.assertEqual(dispatcher.get_info()["packet-handlers"], {"authenticated": [], "ui": []})

    def test_dispatch_routes_and_alias(self):
        dispatcher = Dispatcher()
        handlers = {name: Mock() for name in ("auth", "ui", "default", "default-ui")}
        dispatcher.add_packet_handler("auth", handlers["auth"])
        dispatcher.add_packet_handler("ui", handlers["ui"], main_thread=True)
        dispatcher._default_packet_handlers["default"] = handlers["default"]
        dispatcher._default_ui_packet_handlers["default-ui"] = handlers["default-ui"]
        dispatcher.packet_alias["old"] = "auth"
        proto = Mock()
        proto.is_closed.return_value = False
        for name, authenticated, main in (
                ("old", True, False),
                ("ui", True, True),
                ("default", False, False),
                ("default-ui", False, True),
        ):
            dispatcher.dispatch_packet(proto, Packet(name, 1), authenticated)
            self.assertEqual(dispatcher.calls[-1], (main, "auth" if name == "old" else name))
        for handler in handlers.values():
            handler.assert_called_once()

    def test_invalid_closed_and_handler_error(self):
        dispatcher = Dispatcher()
        proto = Mock()
        proto.is_closed.return_value = False
        dispatcher.dispatch_packet(proto, Packet("missing"))
        proto.close.assert_called_once()
        proto.reset_mock()
        proto.is_closed.return_value = True
        dispatcher.dispatch_packet(proto, Packet("missing"))
        proto.close.assert_not_called()
        handler = Mock(side_effect=ValueError("bad"))
        dispatcher.add_packet_handler("bad", handler)
        proto.is_closed.return_value = False
        with silence_error(dispatch):
            dispatcher.dispatch_packet(proto, Packet("bad"), authenticated=True)
        handler.assert_called_once()

    def make_subsystems(self, dispatcher) -> dict[str, Subsystem]:
        subsystems = {}
        for prefix in ("window", "ping", "ssh-agent"):
            subsystems[prefix] = dispatcher.subsystems[prefix] = Subsystem(prefix)
        return subsystems

    def test_subsystem_routing(self):
        dispatcher = Dispatcher()
        subsystems = self.make_subsystems(dispatcher)
        handlers = {name: Mock() for name in ("draw", "ping", "agent-request")}
        # a regular `$PREFIX-$PACKETTYPE` packet:
        subsystems["window"].add_packet_handler("window-draw", handlers["draw"], main_thread=True)
        # a subsystem which owns its bare `PREFIX` as a packet type:
        subsystems["ping"].add_packet_handler("ping", handlers["ping"])
        # a subsystem whose `PREFIX` contains a '-' itself:
        subsystems["ssh-agent"].add_packet_handler("ssh-agent-request", handlers["agent-request"])
        proto = Mock()
        proto.is_closed.return_value = False
        for packet_type, main in (("window-draw", True), ("ping", False), ("ssh-agent-request", False)):
            dispatcher.dispatch_packet(proto, Packet(packet_type, 1), authenticated=True)
            self.assertEqual(dispatcher.calls[-1], (main, packet_type))
        for handler in handlers.values():
            handler.assert_called_once()
        # routed handlers are only reachable once authenticated:
        with silence_error(dispatch):
            dispatcher.dispatch_packet(proto, Packet("window-draw", 1), authenticated=False)
        proto.close.assert_called_once()

    def test_subsystem_enumeration_and_removal(self):
        dispatcher = Dispatcher()
        subsystems = self.make_subsystems(dispatcher)
        handler = Mock()
        subsystems["window"].add_packet_handler("window-draw", handler)
        subsystems["ssh-agent"].add_packet_handler("ssh-agent", handler)
        dispatcher.add_packet_handler("flat", handler)
        self.assertEqual(sorted(dispatcher.get_packet_types()), ["flat", "ssh-agent", "window-draw"])
        self.assertEqual(dispatcher.get_info()["packet-handlers"]["subsystems"],
                         {"ssh-agent": ["ssh-agent"], "window": ["window-draw"]})
        # removal reaches into the subsystem that owns the name:
        dispatcher.remove_packet_handlers("window-draw", "ssh-agent")
        self.assertEqual(dispatcher.get_packet_types(), ["flat"])
        self.assertNotIn("subsystems", dispatcher.get_info()["packet-handlers"])

    def test_flat_registry_wins_over_routing(self):
        # `x11/desktop/monitor_server.py` and the one-shot CLI clients register
        # prefixed names on the server / client object itself:
        dispatcher = Dispatcher()
        subsystems = self.make_subsystems(dispatcher)
        routed = Mock()
        flat = Mock()
        subsystems["window"].add_packet_handler("window-draw", routed)
        dispatcher.add_packet_handler("window-draw", flat)
        proto = Mock()
        proto.is_closed.return_value = False
        dispatcher.dispatch_packet(proto, Packet("window-draw", 1), authenticated=True)
        flat.assert_called_once()
        routed.assert_not_called()

    def test_find_packet_handler_misses(self):
        subsystems = {"window": Subsystem("window")}
        subsystems["window"].add_packet_handler("window-draw", Mock())
        # unknown prefix, and a known prefix with an unknown sub-type:
        self.assertIsNone(find_packet_handler(subsystems, "audio-data"))
        self.assertIsNone(find_packet_handler(subsystems, "window-eos"))
        self.assertIsNone(find_packet_handler(subsystems, "window"))
        self.assertIsNone(find_packet_handler({}, "window-draw"))


if __name__ == "__main__":
    unittest.main()
