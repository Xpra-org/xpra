#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.net.common import Packet
from xpra.net import dispatch
from xpra.net.dispatch import PacketDispatcher, find_packet_handler, parse_packet_error_policy
from unit.test_util import silence_error, silence_warn


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
        # record the routing decision, but leave the call itself
        # to the dispatcher: that is where the error boundary is
        self.calls.append((main, packet.get_type()))
        super().call_packet_handler(main, handler, proto, packet)


class DeferringDispatcher(PacketDispatcher):
    """ stands in for the client and the glib server: they hand `main` packets to a main loop """

    def __init__(self):
        super().__init__()
        self.deferred = []

    def call_in_main_thread(self, call) -> None:
        self.deferred.append(call)


class DispatchTest(unittest.TestCase):

    def test_handler_registration_and_removal(self):
        dispatcher = Dispatcher()
        handler = Mock()
        dispatcher.add_packet_handler("one", handler)
        dispatcher.add_packet_handler("two", handler, main_thread=True)
        self.assertEqual(dispatcher.get_info()["packet-handlers"], {"authenticated": ["one"], "ui": ["two"]})
        dispatcher.remove_packet_handlers("one", "two")
        self.assertEqual(dispatcher.get_info()["packet-handlers"], {"authenticated": [], "ui": []})

    def test_dispatch_routes(self):
        dispatcher = Dispatcher()
        handlers = {name: Mock() for name in ("auth", "ui", "default", "default-ui")}
        dispatcher.add_packet_handler("auth", handlers["auth"])
        dispatcher.add_packet_handler("ui", handlers["ui"], main_thread=True)
        dispatcher._default_packet_handlers["default"] = handlers["default"]
        dispatcher._default_ui_packet_handlers["default-ui"] = handlers["default-ui"]
        proto = Mock()
        proto.is_closed.return_value = False
        for name, authenticated, main in (
                ("auth", True, False),
                ("ui", True, True),
                ("default", False, False),
                ("default-ui", False, True),
        ):
            dispatcher.dispatch_packet(proto, Packet(name, 1), authenticated)
            self.assertEqual(dispatcher.calls[-1], (main, name))
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

    def test_a_deferred_handler_error_is_contained(self):
        dispatcher = DeferringDispatcher()
        handler = Mock(side_effect=ValueError("bad"))
        dispatcher.add_packet_handler("bad", handler, main_thread=True)
        proto = Mock()
        proto.is_closed.return_value = False
        dispatcher.dispatch_packet(proto, Packet("bad"), authenticated=True)
        # the dispatcher has returned and the handler has not run yet:
        handler.assert_not_called()
        self.assertEqual(len(dispatcher.deferred), 1)
        # so this is the only thing left to catch what it raises:
        with silence_error(dispatch):
            dispatcher.deferred[0]()
        handler.assert_called_once()

    def test_the_handler_arguments_belong_to_the_endpoint(self):
        packets = []

        class ClientLike(DeferringDispatcher):
            # the client's handlers take the packet on its own, see `XpraClientBase`:
            @staticmethod
            def packet_handler_args(_proto, packet):
                return (packet, )

        dispatcher = ClientLike()
        dispatcher.add_packet_handler("one", packets.append)
        proto = Mock()
        proto.is_closed.return_value = False
        packet = Packet("one", 1)
        dispatcher.dispatch_packet(proto, packet, authenticated=True)
        self.assertEqual(packets, [packet])

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


class PolicyDispatcher(PacketDispatcher):
    """ records the packet error policy actions instead of taking them """

    def __init__(self, policy: str):
        super().__init__()
        self.packet_error_policy = parse_packet_error_policy(policy)
        self.actions = []

    def packet_error_disconnect(self, proto, packet_type: str) -> None:
        self.actions.append(("disconnect", proto, packet_type))

    def packet_error_exit(self, packet_type: str) -> None:
        self.actions.append(("exit", packet_type))


class PacketErrorPolicyTest(unittest.TestCase):

    def test_parse(self):
        for value, expected in {
            "log": (-1, "log"),
            "": (-1, "log"),
            "log=3": (3, "log"),
            "ignore": (0, "ignore"),
            "log=2,ignore": (2, "log"),
            "disconnect": (0, "disconnect"),
            "exit": (0, "exit"),
            "log=2,disconnect": (2, "disconnect"),
            " Disconnect , log=2 ": (2, "disconnect"),
            "log=5,exit": (5, "exit"),
        }.items():
            self.assertEqual(parse_packet_error_policy(value), expected, f"parsing {value!r}")
        with silence_warn(dispatch):
            for value in ("foo", "log=x", "log=-1", "disconnect,exit", "log=1,log=2", "exit=2", "log,,exit"):
                self.assertEqual(parse_packet_error_policy(value), (-1, "log"), f"parsing {value!r}")

    @staticmethod
    def fail(dispatcher, proto, count=1) -> None:
        handler = Mock(side_effect=ValueError("bad"))
        dispatcher.add_packet_handler("bad", handler)
        with silence_error(dispatch):
            for _ in range(count):
                dispatcher.dispatch_packet(proto, Packet("bad"), authenticated=True)

    @staticmethod
    def make_proto(closed=False):
        proto = Mock()
        proto.is_closed.return_value = closed
        return proto

    def test_log_takes_no_action(self):
        for policy in ("log", "log=2", "ignore"):
            dispatcher = PolicyDispatcher(policy)
            proto = self.make_proto()
            self.fail(dispatcher, proto, 5)
            self.assertEqual(dispatcher.actions, [])
            self.assertEqual(dispatcher.packet_errors[proto], 5)
            proto.close.assert_not_called()

    def test_disconnect_after_n_errors(self):
        dispatcher = PolicyDispatcher("log=2,disconnect")
        proto = self.make_proto()
        self.fail(dispatcher, proto, 2)
        self.assertEqual(dispatcher.actions, [])
        self.fail(dispatcher, proto)
        self.assertEqual(dispatcher.actions, [("disconnect", proto, "bad")])

    def test_disconnect_counts_per_protocol(self):
        dispatcher = PolicyDispatcher("log=1,disconnect")
        proto1 = self.make_proto()
        proto2 = self.make_proto()
        self.fail(dispatcher, proto1)
        self.fail(dispatcher, proto2)
        self.assertEqual(dispatcher.actions, [])
        self.fail(dispatcher, proto2)
        self.assertEqual(dispatcher.actions, [("disconnect", proto2, "bad")])

    def test_disconnect_closed_protocol(self):
        dispatcher = PolicyDispatcher("disconnect")
        proto = self.make_proto(closed=True)
        # the dispatcher only calls the handlers of open protocols, so call it directly:
        dispatcher.add_packet_handler("bad", Mock(side_effect=ValueError("bad")))
        with silence_error(dispatch):
            dispatcher.call_packet_handler(False, dispatcher._authenticated_packet_handlers["bad"], proto, Packet("bad"))
        self.assertEqual(dispatcher.actions, [])

    def test_exit(self):
        dispatcher = PolicyDispatcher("exit")
        self.fail(dispatcher, self.make_proto())
        self.assertEqual(dispatcher.actions, [("exit", "bad")])

    def test_short_packet(self):
        dispatcher = PolicyDispatcher("exit")
        # reading a field which the packet does not have raises an `IndexError`:
        dispatcher.add_packet_handler("short", lambda _proto, packet: packet.get_str(1))
        with silence_error(dispatch):
            dispatcher.dispatch_packet(self.make_proto(), Packet("short"), authenticated=True)
        self.assertEqual(dispatcher.actions, [("exit", "short")])

    def test_default_disconnect_closes(self):
        dispatcher = PacketDispatcher()
        dispatcher.packet_error_policy = parse_packet_error_policy("disconnect")
        proto = self.make_proto()
        self.fail(dispatcher, proto)
        proto.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
