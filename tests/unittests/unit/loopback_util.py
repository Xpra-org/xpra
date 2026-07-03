#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side ("loopback") subsystem test harness.

Now that both client and server subsystems are self-contained composition
objects (rather than mixins that need the whole client/server class assembled),
a single subsystem from each side can be instantiated in isolation and wired
together in one process. This harness builds a client subsystem and the matching
server subsystem (+ its per-client source), then crosses their "send" paths so
that a packet sent by one side is delivered to the matching ``_process_*``
handler on the other side - no sockets and no serialization (direct object
pass-through).

This exercises the packet contract *between* the two sides, which the isolated
client-only / server-only subsystem tests cannot: packet name/shape drift,
capability negotiation, and request/response round-trips.
"""

import os
# StubClientSubsystem decides at import time whether to mix in the signal/scheduler
# helpers, so this must be set before any client subsystem is imported:
os.environ.setdefault("XPRA_UNIT_TEST", "1")

import unittest

from xpra.net.common import Packet

from unit.client.subsystem.clientmixintest_util import ClientMixinTest
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class _ServerHarness(ServerMixinTest):
    # ServerMixinTest is a TestCase; give it a runnable method name so it can be
    # instantiated as a plain helper (we drive its lifecycle manually):
    def runTest(self):  # pragma: no cover
        pass


class _ClientHarness(ClientMixinTest):
    def runTest(self):  # pragma: no cover
        pass


class LoopbackTest(unittest.TestCase):
    """
    Base class for tests that wire a client subsystem to a server subsystem.

    Subclasses call ``self.connect(...)`` and then drive the subsystems
    directly, asserting on ``self.c2s`` / ``self.s2c`` (the packets that crossed
    the wire) and on the resulting subsystem state.
    """

    def setUp(self):
        self._srv = None
        self._cli = None
        # packets that crossed the wire, as (packet_type, *args) tuples:
        self.c2s = []   # client -> server
        self.s2c = []   # server -> client

    def tearDown(self):
        if self._cli:
            self._cli.tearDown()
            self._cli = None
        if self._srv:
            self._srv.tearDown()
            self._srv = None

    def connect(self, client_class, server_class, source_class,
                client_opts, server_opts, caps=None):
        """
        Build both subsystems and cross-wire their send paths.

        Returns ``(client_subsystem, server_subsystem, server_source)``.
        """
        caps = caps or {}

        srv = self._srv = _ServerHarness()
        srv.setUpClass()
        srv.setUp()
        srv._test_mixin_class(server_class, server_opts, caps, source_class)

        cli = self._cli = _ClientHarness()
        cli.setUpClass()
        cli.setUp()
        cli._test_mixin_class(client_class, client_opts, caps)

        self._wire()
        return cli.mixin, srv.mixin, srv.source

    def _wire(self):
        srv = self._srv
        cli = self._cli

        # client subsystem -> server subsystem packet handler.
        # server handlers take (proto, packet):
        def to_server(packet_type, *args):
            self.c2s.append((packet_type, ) + args)
            pt = srv.legacy_alias.get(packet_type, packet_type)
            handler = srv.packet_handlers.get(pt)
            assert handler, "no server packet handler for %r" % packet_type
            handler(srv.protocol, Packet(packet_type, *args))

        cli.mixin.send = to_server
        cli.mixin.send_now = to_server

        # Some client subsystems (notably pointer) do not call send() directly:
        # they queue packets on the owning client for the network thread and
        # trigger a flush via client.have_more(). Emulate the protocol's
        # next_packet() drain so those packets reach the server too. The queues
        # live on the assembled client base in production; here the client
        # harness stands in for the owning client (see `_test_mixin_class`).
        cli._priority_packets = []
        cli._ordinary_packets = []

        def have_more() -> None:
            while cli._priority_packets:
                p = cli._priority_packets.pop(0)
                to_server(p[0], *p[1:])
            while cli._ordinary_packets:
                p = cli._ordinary_packets.pop(0)
                to_server(p[0], *p[1:])
            mp = getattr(cli.mixin, "position", None)
            if mp is not None:
                cli.mixin.position = None
                to_server(mp[0], *mp[1:])

        cli.have_more = have_more

        # server source -> client subsystem packet handler.
        # client handlers take just (packet); strip will_have_more/synchronous:
        def to_client(packet_type, *args, **_kwargs):
            self.s2c.append((packet_type, ) + args)
            pt = cli.legacy_alias.get(packet_type, packet_type)
            handler = cli.packet_handlers.get(pt)
            assert handler, "no client packet handler for %r" % packet_type
            handler(Packet(packet_type, *args))

        # server -> client wiring is only possible when a source object exists:
        if srv.source is not None:
            src = srv.source
            src.send = to_client
            src.send_now = to_client
            src.send_async = to_client
            src.send_more = to_client
