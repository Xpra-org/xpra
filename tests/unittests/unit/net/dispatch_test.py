#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.net.common import Packet
from xpra.net import dispatch
from xpra.net.dispatch import (
    PacketDispatcher, find_packet_handler, parse_packet_error_policy,
    MAIN_THREAD_BACKLOG, MAIN_THREAD_BACKLOG_DELAY,
)
from unit.test_util import silence_error, silence_warn


def make_proto():
    # a stand-in connection: open, and carrying the two per-connection
    # main-thread back-pressure counters that the server/client set at creation
    proto = Mock()
    proto.is_closed.return_value = False
    proto.main_calls_queued = 0
    proto.main_calls_done = 0
    return proto


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
        proto = make_proto()
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
        proto = make_proto()
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
        proto = make_proto()
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
        proto = make_proto()
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
        proto = make_proto()
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
        proto = make_proto()
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


class MainThreadBacklogTest(unittest.TestCase):
    """ a connection flooding `main_thread=True` handlers is back-pressured per connection """

    @staticmethod
    def flood(dispatcher, proto, count):
        for _ in range(count):
            dispatcher.dispatch_packet(proto, Packet("slow", 1), authenticated=True)

    def test_counter_tracks_queued_main_calls(self):
        dispatcher = DeferringDispatcher()
        dispatcher.add_packet_handler("slow", Mock(), main_thread=True)
        proto = make_proto()
        self.flood(dispatcher, proto, 5)
        # all five are queued (not yet run) and counted as in-flight:
        self.assertEqual(len(dispatcher.deferred), 5)
        self.assertEqual(proto.main_calls_queued, 5)
        self.assertEqual(proto.main_calls_done, 0)
        # running the queued calls brings the in-flight count back to zero:
        for call in dispatcher.deferred:
            call()
        self.assertEqual(proto.main_calls_done, 5)
        self.assertEqual(proto.main_calls_queued - proto.main_calls_done, 0)

    def test_counter_is_per_connection(self):
        dispatcher = DeferringDispatcher()
        dispatcher.add_packet_handler("slow", Mock(), main_thread=True)
        proto1 = make_proto()
        proto2 = make_proto()
        self.flood(dispatcher, proto1, 7)
        self.flood(dispatcher, proto2, 2)
        self.assertEqual(proto1.main_calls_queued, 7)
        self.assertEqual(proto2.main_calls_queued, 2)

    def test_non_main_calls_are_not_counted(self):
        dispatcher = DeferringDispatcher()
        dispatcher.add_packet_handler("fast", Mock())
        proto = make_proto()
        for _ in range(5):
            dispatcher.dispatch_packet(proto, Packet("fast", 1), authenticated=True)
        self.assertEqual(proto.main_calls_queued, 0)

    def test_throttle_sleeps_only_over_threshold_off_main_thread(self):
        over = MAIN_THREAD_BACKLOG + 10
        with patch.object(dispatch, "sleep") as sleep, patch.object(dispatch, "is_main_thread", return_value=False):
            # below the threshold: no back-pressure
            PacketDispatcher.throttle_pending_main_calls(MAIN_THREAD_BACKLOG)
            sleep.assert_not_called()
            # above the threshold: sleep grows with the backlog (2ms per call over)
            PacketDispatcher.throttle_pending_main_calls(over)
            sleep.assert_called_once_with(10 * 2 / 1000)
        # the main thread (which drains the queue) must never sleep, even deep in backlog:
        with patch.object(dispatch, "sleep") as sleep, patch.object(dispatch, "is_main_thread", return_value=True):
            PacketDispatcher.throttle_pending_main_calls(over)
            sleep.assert_not_called()

    def test_throttle_delay_is_capped(self):
        huge = MAIN_THREAD_BACKLOG + 100_000
        with patch.object(dispatch, "sleep") as sleep, patch.object(dispatch, "is_main_thread", return_value=False):
            PacketDispatcher.throttle_pending_main_calls(huge)
            sleep.assert_called_once_with(MAIN_THREAD_BACKLOG_DELAY / 1000)


class RealProto:
    """ a real (not Mock) stand-in connection carrying the two back-pressure counters """

    def __init__(self):
        self.main_calls_queued = 0
        self.main_calls_done = 0

    def is_closed(self) -> bool:
        return False


class MainThreadBacklogIntegrationTest(unittest.TestCase):
    """ end-to-end with a real GLib main loop: a background parse thread floods
        main-thread packets and the per-connection back-pressure bounds the idle queue """

    THRESHOLD = 20
    COUNT = 1000

    @classmethod
    def run_flood(cls, threshold: int):
        """ flood a fixed number of packets through a real GLib loop and drain fully;
            return (peak_pending, sent, processed). Each run drains completely so it
            leaves no idle sources behind on GLib's shared default context. """
        import threading
        from time import monotonic, sleep
        from xpra.os_util import gi_import
        from xpra.util.glib_scheduler import GLibScheduler
        GLib = gi_import("GLib")
        count = cls.COUNT

        class RealLoopDispatcher(PacketDispatcher, GLibScheduler):
            # wired exactly as `GLibServer`: main-thread handlers go to the idle queue
            def call_in_main_thread(self, call) -> None:
                self.idle_add(call)

        processed = [0]

        def handler(_proto, _packet) -> None:
            # takes real time, so the single main loop is outrun by the flood:
            sleep(0.0005)
            processed[0] += 1

        dispatcher = RealLoopDispatcher()
        dispatcher.add_packet_handler("flood", handler, main_thread=True)
        loop = GLib.MainLoop()
        proto = RealProto()
        peak = [0]
        sent = [0]
        deadline = monotonic() + 20  # safety net so the test can never hang

        def sample() -> bool:
            peak[0] = max(peak[0], proto.main_calls_queued - proto.main_calls_done)
            if (sent[0] >= count and processed[0] >= count) or monotonic() > deadline:
                loop.quit()
                return False
            return True
        GLib.timeout_add(2, sample)

        def flood() -> None:
            for _ in range(count):
                dispatcher.dispatch_packet(proto, Packet("flood", 1), authenticated=True)
                sent[0] += 1

        with patch.object(dispatch, "MAIN_THREAD_BACKLOG", threshold), \
                patch.object(dispatch, "MAIN_THREAD_BACKLOG_DELAY", 5):
            threading.Thread(target=flood, daemon=True).start()
            loop.run()
        return peak[0], sent[0], processed[0]

    def test_backpressure_bounds_a_real_flood(self):
        # throttle effectively off: the one connection's idle queue grows toward `COUNT`
        off_peak, _, _ = self.run_flood(10 ** 12)
        # throttle on: back-pressure pins the queue near the threshold
        on_peak, on_sent, on_processed = self.run_flood(self.THRESHOLD)

        # the throttled queue stays near the threshold, far below the unthrottled one:
        self.assertLessEqual(on_peak, self.THRESHOLD + 50, f"idle queue was not bounded: peaked at {on_peak}")
        self.assertGreater(off_peak, on_peak * 3, f"no back-pressure effect: off={off_peak} on={on_peak}")
        # and the throttle drops nothing - every queued call ran:
        self.assertEqual(on_processed, on_sent)


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
