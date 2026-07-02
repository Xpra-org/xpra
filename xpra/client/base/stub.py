# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from typing import Any, NoReturn

from xpra.util.env import envbool
from xpra.util.objects import typedict
from xpra.exit_codes import ExitValue
from xpra.net.compression import Compressed
from xpra.net.common import ClientPacketHandlerType, PacketElement

# Subsystems inherit `SignalEmitter` so that a *composed* subsystem instance can
# own its own signals (emit/connect on itself) rather than routing through the
# client GObject. On the concrete client, `StubClientMixin` is still in the MRO
# (via the transitional flatten), but the real `GObject` connect/emit precede
# `SignalEmitter` in the MRO, so the client keeps using GObject signals.
# Under the unit tests we also mix in `GLibScheduler` (isolated subsystems have
# no owning client to borrow `idle_add`/`timeout_add`/`source_remove` from).
from xpra.util.signal_emitter import SignalEmitter
if envbool("XPRA_UNIT_TEST"):
    from xpra.util.glib_scheduler import GLibScheduler
    superclass = type("StubSignalScheduler", (SignalEmitter, GLibScheduler), {})
else:
    superclass = SignalEmitter


class StubClientMixin(superclass):
    __signals__: list[str] = []
    # every concrete subsystem should declare a non-empty PREFIX,
    # used as the key in `client.subsystems`:
    PREFIX: str = ""

    # main-loop scheduling helpers provided by the owning client; they are
    # copied onto the subsystem when it is attached to a client (see the
    # `client` setter) so subsystems call `self.timeout_add(...)` directly
    # rather than reaching through `self.client`:
    SCHEDULER_METHODS = ("idle_add", "timeout_add", "source_remove")

    @property
    def client(self):
        # while subsystems are still mixed into a single client object,
        # `self.client` is the client itself.
        # Phase 2 (composition) will set `_client` to the owning client instance.
        return getattr(self, "_client", None) or self

    @client.setter
    def client(self, value) -> None:
        self._client = value
        if value is not None and value is not self:
            # a real, separate owning client: borrow its main-loop scheduler:
            for name in self.SCHEDULER_METHODS:
                setattr(self, name, getattr(value, name))

    def __getattr__(self, name: str):
        # transitional Phase-2 aid: once a subsystem becomes a real instance
        # (its `_client` points at a *different* client object), any attribute
        # that the Phase-1 routing missed falls back to the owning client
        # rather than raising `AttributeError`, with a loud one-time warning so
        # the missed routing gets fixed. While still muxed (`_client is self`)
        # or in isolated unit tests (`_client` unset) this is completely inert.
        client = self.__dict__.get("_client")
        if client is None or client is self or name.startswith("__"):
            raise AttributeError(name)
        from xpra.util.env import first_time
        if first_time(f"{type(self).__name__}.{name}-client-fallback"):
            from xpra.log import Logger
            Logger("subsystems").warn(
                "Warning: %s.%s resolved on the client (missed Phase-2 routing)",
                type(self).__name__, name,
            )
        return getattr(client, name)

    def _should_call_direct(self) -> bool:
        # `SignalEmitter` hook: a *composed* subsystem owns its own signals but
        # has no main loop of its own; it fires them on the owning client's main
        # loop (deferring via `idle_add` when emitted off the UI thread, exactly
        # as the base `SignalEmitter` does with `self.main_loop`).
        main_loop = getattr(self.client, "main_loop", None)
        if main_loop is None or not main_loop.is_running():
            return True
        return main_loop.get_context().is_owner()

    def get_subsystem(self, name: str):
        """ look up a peer subsystem on the owning client """
        return getattr(self.client, "subsystems", {}).get(name)

    def get_window(self, wid: int):
        """ look up a window by id on the `window` subsystem """
        window = self.get_subsystem("window")
        return window.get_window(wid) if window else None

    def get_windows(self) -> tuple:
        """ all the windows currently registered with the `window` subsystem """
        window = self.get_subsystem("window")
        return tuple(window._id_to_window.values()) if window else ()

    def window_registered(self, wid: int, window) -> None:
        """
        Per-client hook called after the `window` subsystem registers a new window.
        Concrete clients (ie: win32) override this to connect toolkit signals; the
        default does nothing.
        """

    def init(self, opts) -> None:
        """
        Initialize this instance with the options given.
        Options are usually obtained by parsing the command line,
        or using a default configuration object.
        """

    def init_ui(self, opts) -> None:
        """
        Initialize the user interface,
        creating windows and widgets if needed.
        """

    def load(self) -> None:
        """
        Slower initialization that may load external components
        """

    def run(self) -> ExitValue:
        """
        run the main loop.
        """

    def quit(self, exit_code: ExitValue) -> NoReturn:  # pragma: no cover
        """
        Terminate the client with the given exit code.
        (the exit code is ignored if we already have one)
        """
        self.exit_code = exit_code
        sys.exit(exit_code)

    def cleanup(self) -> None:
        """
        Free up any resources.
        """

    def send(self, packet_type: str, *parts: PacketElement) -> None:
        """
        Send a packet to the server.
        When this subsystem is a composed instance, delegate to the owning
        client; while still muxed the concrete client's own `send` overrides
        this (and isolated tests inject their own), so this is only reached on
        a real separate instance.
        """
        client = self.client
        if client is not self:
            client.send(packet_type, *parts)

    def send_now(self, packet_type: str, *parts: PacketElement) -> None:
        """
        Send a packet to the server,
        this takes precedence over packets sent via send().
        Delegates to the owning client (see `send`).
        """
        client = self.client
        if client is not self:
            client.send_now(packet_type, *parts)

    def setup_connection(self, _conn) -> None:
        """
        Prepare to run using this connection to the server.
        """

    def get_caps(self) -> dict[str, Any]:
        """
        Return the capabilities provided by this mixin.
        """
        return {}

    def get_info(self) -> dict[str, Any]:
        """
        Information contained in this mixin
        """
        return {}

    def parse_server_capabilities(self, c: typedict) -> bool:  # pylint: disable=unused-argument
        """
        Parse server attributes specified in the hello capabilities.
        This runs in a non-UI thread.
        """
        return True

    # noinspection PyMethodMayBeStatic
    def compressed_wrapper(self, datatype, data, level=5, **_kwargs) -> Compressed:
        """
        Dummy utility method for compressing data.
        Actual client implementations will provide compression
        based on the client and server capabilities (ie: lz4, brotli).
        subclasses should override this method.
        """
        assert level >= 0
        return Compressed("raw %s" % datatype, data)

    def init_packet_handlers(self) -> None:
        """
        Register the packet types that this mixin can handle, even before authentication.
        """

    def init_authenticated_packet_handlers(self) -> None:
        """
        Register the packet types that this mixin can handle after authentication.
        """

    def add_packets(self, *packet_types: str, main_thread: bool = False) -> None:
        """
        Register packet handlers for this subsystem. Handlers
        (`_process_<packet_type>`) are looked up on this instance and
        registered against the client's packet dispatcher.
        (mirror of the server's `StubSubsystem.add_packets`)
        """
        for packet_type in packet_types:
            handler = getattr(self, "_process_" + packet_type.replace("-", "_"))
            self.client.add_packet_handler(packet_type, handler, main_thread)

    def add_packet_handler(self, packet_type: str, handler: ClientPacketHandlerType,
                           main_thread: bool = False) -> None:
        """ register a single packet handler on the owning client """
        self.client.add_packet_handler(packet_type, handler, main_thread)

    def add_packet_handlers(self, defs: dict[str, ClientPacketHandlerType], main_thread: bool = False) -> None:
        """ register multiple packet handlers on the owning client """
        self.client.add_packet_handlers(defs, main_thread)

    def add_legacy_alias(self, legacy_name: str, new_name: str) -> None:
        """ register a backwards-compat packet name alias on the owning client """
        self.client.add_legacy_alias(legacy_name, new_name)

    def remove_packet_handlers(self, *keys: str) -> None:
        """ remove packet handlers from the owning client's dispatcher """
        self.client.remove_packet_handlers(*keys)
