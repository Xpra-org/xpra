#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from gi.repository import GLib  # @UnresolvedImport

from xpra.net.common import Packet, BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict, AdHocStruct
from xpra.util.signal_emitter import SignalEmitter
from xpra.server.source.stub import StubClientConnection


class ServerMixinTest(unittest.TestCase, SignalEmitter):

    @classmethod
    def setUpClass(cls):
        super(ServerMixinTest, cls).setUpClass()
        cls.glib = GLib
        cls.main_loop = cls.glib.MainLoop()
        # we don't want to spawn an X11 server to test the subsystems
        os.environ["XPRA_NOX11"] = "1"

    def setUp(self):
        # SignalEmitter holds per-instance state in `_signal_callbacks`;
        # initialize it so subsystems can `connect` / `emit` against us:
        SignalEmitter.__init__(self)
        self.mixin = None
        self.source = None
        self.protocol = None
        self.packet_handlers = {}
        self.legacy_alias = {}

    def tearDown(self):
        unittest.TestCase.tearDown(self)
        if self.source:
            self.source.cleanup()
            self.source = None
        if self.mixin:
            self.mixin.cleanup()
            self.mixin = None

    def debug_all(self) -> None:
        from xpra.log import enable_debug_for
        enable_debug_for("all")

    def stop(self) -> None:
        self.glib.timeout_add(1000, self.main_loop.quit)

    def add_packets(self, *packet_types: str, main_thread=False) -> None:
        for packet_type in packet_types:
            handler = getattr(self.mixin, "_process_" + packet_type.replace("-", "_"))
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_legacy_alias(self, legacy_name: str, name: str) -> None:
        if BACKWARDS_COMPATIBLE:
            self.legacy_alias[legacy_name] = name

    def add_packet_handler(self, packet_type: str, handler=None, main_thread=True) -> None:
        self.packet_handlers[packet_type] = handler

    def handle_packet(self, packet: Packet | tuple):
        if isinstance(packet, tuple):
            packet = Packet(*packet)
        packet_type = packet.get_type()
        packet_type = self.legacy_alias.get(packet_type, packet_type)
        ph = self.packet_handlers.get(packet_type)
        assert ph is not None, "no packet handler for %s" % packet_type
        ph(self.protocol, packet)

    def verify_packet_error(self, packet):
        try:
            self.handle_packet(packet)
        except Exception:
            pass
        else:
            raise Exception("invalid packet %s should cause an error" % (packet,))

    def get_server_source(self, proto):
        assert proto==self.protocol
        return self.source

    def create_test_sockets(self):
        return {}

    # Server-side helpers that subsystems may delegate to via StubServerMixin.
    # `connect` / `emit` come from `SignalEmitter`. The rest are no-ops:

    def disconnect_client(self, *_args, **_kwargs) -> None:
        pass

    def clean_quit(self, *_args, **_kwargs) -> None:
        pass

    def notify_setup_error(self, _exception) -> None:
        pass

    def get_child_env(self) -> dict[str, str]:
        return dict(os.environ)

    # Variant-overridable display hooks (defaults on `ServerBase` in production):
    def set_desktop_geometry(self, *_args, **_kwargs) -> None:
        pass

    def set_workarea(self, *_args, **_kwargs) -> None:
        pass

    def calculate_desktops(self, *_args, **_kwargs) -> None:
        pass

    def set_dpi(self, *_args, **_kwargs) -> None:
        pass

    def set_screen_size(self, width: int, height: int):
        return width, height

    _closing = False
    session_name = ""
    readonly = False
    unix_socket_paths: list[str] = []
    hello_request_handlers: dict = {}

    def _test_mixin_class(self, mclass, opts, caps=None, source_mixin_class=StubClientConnection):
        # Helper attributes / methods that subsystems expect to find on the
        # owning server. Set on `self` (the test class, acting as the mock
        # server) so instance-based subsystems reach them via `self.server.X`.
        self._socket_info = ()
        self._server_sources = {}   # pylint: disable=protected-access
        self.auth_classes = {}
        self.sockets = self.create_test_sockets()
        self.subsystems: dict = {}
        self.get_sources_by_type = lambda st, exclude=None: [
            ss for ss in self._server_sources.values() if isinstance(ss, st) and ss != exclude
        ]
        # Instance-based subsystems take `server` in their constructor;
        # legacy mixin-style subsystems do not. Inspect the callable's
        # signature directly (works for both classes and factory functions).
        import inspect
        try:
            takes_server = len(inspect.signature(mclass).parameters) >= 1
        except (TypeError, ValueError):
            takes_server = False
        if takes_server:
            x = self.mixin = mclass(self)
            # mirror `_server_sources` on the mixin for tests that write
            # directly to it (e.g. encoding_test): instance-based subsystems
            # reach the same dict via `self.server._server_sources`.
            x._server_sources = self._server_sources
        else:
            x = self.mixin = mclass()
            # legacy wiring: subsystems resolve these names via the dynamic
            # MRO, but in the test there is no enclosing server class. Also
            # override `x.server` (which `StubServerMixin.__init__` set to
            # `x` itself) so delegating helpers like `self.connect` route
            # to this test class's mocks instead of recursing into `x`:
            x.server = self
            x._socket_info = self._socket_info
            x._server_sources = self._server_sources
            x.add_packets = self.add_packets
            x.add_legacy_alias = self.add_legacy_alias
            x.add_packet_handler = self.add_packet_handler
            x.get_server_source = self.get_server_source
            x.get_sources_by_type = self.get_sources_by_type
        # Register the subsystem under its PREFIX so source classes that look
        # up via `server.subsystems[prefix].attr` (instance-based pattern)
        # can find it - and so peer-subsystem lookups via `self.get_subsystem`
        # also work in test contexts:
        prefix = getattr(x, "PREFIX", "") or getattr(mclass, "PREFIX", "")
        if prefix:
            self.subsystems[prefix] = x
        x.init_state()
        x.init(opts)
        if not takes_server:
            x.auth_classes = self.auth_classes
            x.sockets = self.sockets
        x.setup()
        x.init_packet_handlers()
        caps = typedict(caps or {})
        self.source = None
        if source_mixin_class:
            self.source = source_mixin_class()
            self.protocol = AdHocStruct()
            self.protocol.TYPE = "xpra"
            self.source.wants = ("display", "foo")
            self.source.protocol = self.protocol
            # Pass `x` (the subsystem instance) as the server. Source classes
            # that read `server.attr` directly (legacy class-based pattern)
            # find the attr on `x`; source classes that look up
            # `server.subsystems["prefix"].attr` (instance-based pattern)
            # also work because we mirror the test's `subsystems` dict onto
            # `x` here:
            x.subsystems = self.subsystems
            self.source.init_from(self.protocol, x)
            self.source.init_state()
            self.source.hello_sent = 0.0
            self.source.parse_client_caps(caps)
            self.source.get_info()
        x.get_caps(self.source)
        x.get_info(None)
        x.parse_hello(self.source, caps)
        x.get_info(self.source)
