# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.common import noop
from xpra.net.common import may_log_packet, Packet, PacketHandlerType
from xpra.log import Logger
from xpra.util.str_fn import repr_ellipsized

log = Logger("network")


def find_packet_handler(subsystems: dict[str, Any], packet_type: str) -> tuple[Any, str, Callable, bool] | None:
    """
    Route a `$SUBSYSTEM-$PACKETTYPE` packet to the subsystem registered under `$SUBSYSTEM`,
    which owns the handler for `$PACKETTYPE` (see `StubSubsystem.add_packet_handler`).
    A subsystem may also own its bare `PREFIX` as a packet type (`ping`, `suspend`, ...),
    in which case the sub-type is the empty string.
    Some prefixes contain a '-' themselves (`ssh-agent`, `client-session`, `session-files`,
    `ssl-upgrade`, ...), so try increasingly long prefixes: the common single-dash case
    costs one `partition` and one dictionary lookup.
    Returns `(subsystem, subtype, handler, main_thread)`, or `None` if no subsystem claims it.
    """
    prefix, sep, subtype = packet_type.partition("-")
    while True:
        sub = subsystems.get(prefix)
        if sub is not None:
            if handler_def := sub.get_packet_handler(subtype):
                return sub, subtype, handler_def[0], handler_def[1]
        if not sep:
            return None
        more, sep, subtype = subtype.partition("-")
        prefix = f"{prefix}-{more}"


class SubsystemPacketHandlers:
    """
    The packet handlers a subsystem owns, keyed by the packet type with its own
    `PREFIX` stripped: the `bell` subsystem stores `bell-set` under `set`.
    `find_packet_handler` above is the other half of the contract: it is how the
    owning server / client finds these handlers when a packet arrives.

    Shared by both subsystem stubs (`StubSubsystem` and `StubClientSubsystem`).
    The handler signature differs between the two sides (`(proto, packet)` server-side,
    `(packet)` client-side), but nothing here calls the handlers,
    so `Callable` is as specific as this class can be.

    `ClipboardProtocolHelperCore` also uses it, without being a subsystem:
    it owns the whole `clipboard` namespace and dispatches to itself.
    """
    # this class must stay layout-neutral: `ClipboardProtocolHelperCore` mixes it into
    # classes which also derive from `GObject.GObject`, and a non-empty `__slots__` here
    # would be an instance lay-out conflict. `_packet_handlers` is therefore declared by
    # whichever subclass wants it slotted (both stubs do), like `SignalEmitter` does.
    __slots__ = ()
    # declared (with its default and the note on what it keys) by the stubs:
    PREFIX: str

    def owns_packet(self, packet_type: str) -> bool:
        """ is this packet type part of this subsystem's namespace? """
        prefix = self.PREFIX
        return bool(prefix) and (packet_type == prefix or packet_type.startswith(f"{prefix}-"))

    def packet_subtype(self, packet_type: str) -> str:
        """ strip our own `PREFIX`: `bell-set` -> `set`, `suspend` -> `` """
        return "" if packet_type == self.PREFIX else packet_type[len(self.PREFIX) + 1:]

    def packet_handler_name(self, packet_type: str) -> str:
        """
        The name of the method handling this packet type.
        Packets in this subsystem's namespace drop the redundant `PREFIX`:
        the `bell` subsystem handles `bell-set` with `_process_set`.
        Packets we do not own - unprefixed packet types - keep their full name,
        and so does a subsystem's bare `PREFIX`
        (`ping` -> `_process_ping`), which has nothing left to strip.
        """
        subtype = self.packet_subtype(packet_type) if self.owns_packet(packet_type) else ""
        return "_process_" + (subtype or packet_type).replace("-", "_")

    def add_packets(self, *packet_types: str, main_thread: bool = False) -> None:
        """
        Register packet handlers for this subsystem.
        Handlers are looked up on this instance, see `packet_handler_name`.
        """
        for packet_type in packet_types:
            handler = getattr(self, self.packet_handler_name(packet_type))
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_packet_handler(self, packet_type: str, handler: Callable, main_thread: bool = False) -> None:
        """
        Register a single packet handler.
        Every packet a subsystem registers must be in its own namespace (`$PREFIX-$PACKETTYPE`)
        so that the owner's dispatcher can route it here via `find_packet_handler` (see #4972):
        rename the packet, or move its handler to the subsystem owning its prefix.
        """
        if not self.owns_packet(packet_type):
            raise ValueError(f"{type(self).__name__} cannot register the {packet_type!r} packet:"
                             f" it is outside its own {self.PREFIX!r} namespace")
        self._packet_handlers[self.packet_subtype(packet_type)] = (handler, main_thread)

    def add_packet_handlers(self, defs: dict[str, Callable], main_thread: bool = False) -> None:
        """ register multiple packet handlers """
        for packet_type, handler in defs.items():
            self.add_packet_handler(packet_type, handler, main_thread)

    def get_packet_handler(self, subtype: str) -> tuple[Callable, bool] | None:
        """ the `(handler, main_thread)` pair for this packet sub-type, if we have one """
        return self._packet_handlers.get(subtype)

    def remove_packet_handler(self, subtype: str) -> None:
        self._packet_handlers.pop(subtype, None)

    def remove_packet_handlers(self, *keys: str) -> None:
        """
        Remove packet handlers by their full packet type name.
        """
        for packet_type in keys:
            if self.owns_packet(packet_type):
                self.remove_packet_handler(self.packet_subtype(packet_type))

    def get_packet_types(self) -> tuple[str, ...]:
        """ the full packet type names registered by this subsystem """
        return tuple(f"{self.PREFIX}-{subtype}" if subtype else self.PREFIX for subtype in self._packet_handlers)


class PacketDispatcher:

    def __init__(self):
        self._authenticated_packet_handlers: dict[str, Callable] = {}
        self._authenticated_ui_packet_handlers: dict[str, Callable] = {}
        self._default_packet_handlers: dict[str, Callable] = {}
        self._default_ui_packet_handlers: dict[str, Callable] = {}
        # subsystem instances keyed by `PREFIX`: each one owns the handlers
        # for the packet types in its own namespace
        self.subsystems: dict[str, Any] = {}

    def get_info(self) -> dict[str, Any]:
        routed: dict[str, Any] = {}
        for prefix, sub in self.subsystems.items():
            if packet_types := sub.get_packet_types():
                routed[prefix] = sorted(packet_types)
        handlers: dict[str, Any] = {
            "authenticated": sorted(self._authenticated_packet_handlers.keys()),
            "ui": sorted(self._authenticated_ui_packet_handlers.keys()),
        }
        if routed:
            handlers["subsystems"] = routed
        return {"packet-handlers": handlers}

    def get_packet_types(self) -> list[str]:
        """ every packet type we can handle once authenticated, flat registry and subsystems """
        packet_types = list(self._authenticated_ui_packet_handlers)
        packet_types += list(self._authenticated_packet_handlers)
        for sub in self.subsystems.values():
            packet_types += sub.get_packet_types()
        return packet_types

    def remove_packet_handlers(self, *keys) -> None:
        for k in keys:
            for d in (
                    self._authenticated_packet_handlers,
                    self._authenticated_ui_packet_handlers,
                    self._default_packet_handlers,
                    self._default_ui_packet_handlers,
            ):
                d.pop(k, None)
            # the handler may belong to a subsystem's own registry:
            if found := find_packet_handler(self.subsystems, k):
                sub, subtype = found[0], found[1]
                sub.remove_packet_handler(subtype)

    def add_packet_handlers(self, defs: dict[str, PacketHandlerType], main_thread=False) -> None:
        for packet_type, handler in defs.items():
            self.add_packet_handler(packet_type, handler, main_thread)

    def add_packet_handler(self, packet_type: str, handler: PacketHandlerType, main_thread=False) -> None:
        # replace any previously defined handlers:
        self.remove_packet_handlers(packet_type)
        log("add_packet_handler%s", (packet_type, handler, main_thread))
        handlers = self._authenticated_ui_packet_handlers if main_thread else self._authenticated_packet_handlers
        handlers[packet_type] = handler

    def add_packets(self, *packet_types: str, main_thread=False) -> None:
        for packet_type in packet_types:
            handler = getattr(self, "_process_" + packet_type.replace("-", "_"))
            self.add_packet_handler(packet_type, handler, main_thread)

    def dispatch_packet(self, proto, packet: Packet, authenticated=False) -> None:
        packet_type = packet.get_type()
        handler: Callable = noop

        def call_handler(main: bool) -> None:
            may_log_packet(False, packet_type, packet)
            self.call_packet_handler(main, handler, proto, packet)

        try:
            if authenticated and not proto.is_closed():
                if handler := self._authenticated_ui_packet_handlers.get(packet_type):
                    log("process ui packet %s", packet_type)
                    call_handler(True)
                    return
                if handler := self._authenticated_packet_handlers.get(packet_type):
                    log("process non-ui packet %s", packet_type)
                    call_handler(False)
                    return
                if found := find_packet_handler(self.subsystems, packet_type):
                    sub, _, handler, main_thread = found
                    log("process %s packet %s", sub.PREFIX, packet_type)
                    call_handler(main_thread)
                    return
            if handler := self._default_ui_packet_handlers.get(packet_type):
                log("process default ui packet %s", packet_type)
                call_handler(True)
                return
            if handler := self._default_packet_handlers.get(packet_type):
                log("process default packet %s", packet_type)
                call_handler(False)
                return

            self.handle_invalid_packet(proto, packet)
        except (RuntimeError, AssertionError):
            log.error(f"Error processing a {packet_type!r} packet")
            log.error(f" received from {proto}:")
            log.error(f" using {handler}", exc_info=True)

    def call_packet_handler(self, main: bool, handler: PacketHandlerType, proto, packet: Packet) -> None:
        args = self.packet_handler_args(proto, packet)

        def call() -> None:
            # the errors of a packet handler have to stop here, rather than in
            # `dispatch_packet`: `main` hands this call to a main loop, so by the time
            # it runs, the dispatcher has long returned and is no longer on the stack
            try:
                handler(*args)
            except (AssertionError, TypeError, ValueError, RuntimeError):
                log.error(f"Error processing {packet.get_type()!r} packet", exc_info=True)

        if main:
            self.call_in_main_thread(call)
        else:
            call()

    @staticmethod
    def packet_handler_args(proto, packet: Packet) -> tuple:
        # what the handlers of this endpoint expect to be called with
        return proto, packet

    @staticmethod
    def call_in_main_thread(call: Callable) -> None:
        # there is no main loop to hand this to here:
        # the endpoints which have one override this and defer to it
        call()

    @staticmethod
    def handle_invalid_packet(proto, packet: Packet) -> None:
        if proto.is_closed():
            return
        packet_type = packet.get_type()
        log("invalid packet: %s", packet)
        log.error(f"Error: unknown or invalid packet type {packet_type!r}")
        log.error(" %s", repr_ellipsized(packet))
        log.error(f" received from {proto}")
        proto.close()
