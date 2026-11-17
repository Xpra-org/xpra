# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Callable
from weakref import WeakKeyDictionary

from xpra.common import noop
from xpra.exit_codes import ExitCode
from xpra.os_util import force_quit
from xpra.net.common import may_log_packet, Packet, PacketHandlerType, PacketHandlerSpec, PACKET_HANDLER_ATTR
from xpra.log import Logger
from xpra.util.str_fn import repr_ellipsized

log = Logger("network")

PACKET_ERROR_ACTIONS = ("log", "ignore", "disconnect", "exit")


def parse_packet_error_policy(value: str) -> tuple[int, str]:
    """
    Parse a packet handler error policy: `log`, `log=N`, `ignore`, `disconnect`, `exit`,
    or `log=N,disconnect` / `log=N,exit` to log `N` errors before taking the action.
    Returns `(log_count, action)`, where a `log_count` of `-1` means no limit
    and `action` is one of `PACKET_ERROR_ACTIONS`.
    Invalid values fall back to `(-1, "log")`.
    """
    log_count = -1
    action = ""
    if not value.strip():
        return log_count, "log"
    for part in value.lower().split(","):
        name, eq, count = part.strip().partition("=")
        if eq and name == "log" and count.isdigit() and log_count < 0:
            log_count = int(count)
        elif not eq and name in PACKET_ERROR_ACTIONS and not action:
            action = name
        else:
            log.warn(f"Warning: invalid packet error policy {value!r}, using 'log'")
            return -1, "log"
    if action in ("", "log"):
        return log_count, "log"
    if action == "ignore":
        # `log=N,ignore` is the same as `log=N`:
        return (log_count, "log") if log_count >= 0 else (0, action)
    # plain `disconnect` / `exit` act on the first error:
    return max(0, log_count), action


PACKET_ERROR_POLICY = parse_packet_error_policy(os.environ.get("XPRA_PACKET_ERROR_POLICY", "log=10,disconnect"))


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


_specs_cache: dict[type, tuple[tuple[str, PacketHandlerSpec], ...]] = {}


def get_packet_handler_specs(cls) -> tuple[tuple[str, PacketHandlerSpec], ...]:
    # `cls` is deliberately not annotated as `type`:
    # when cythonized, that becomes an exact builtin type check which rejects
    # classes with a metaclass, ie: `GObjectMeta` for all the GObject based servers
    """
    The `(method name, spec)` pairs of the methods decorated with `packet_handler`
    anywhere in this class hierarchy.
    A subclass may re-decorate a method to change its spec, or override it without
    the decorator: the base class spec still applies, and since the handlers are always
    looked up on the instance, the most derived method is the one that gets registered.
    """
    specs = _specs_cache.get(cls)
    if specs is not None:
        return specs
    by_name: dict[str, PacketHandlerSpec] = {}
    for klass in reversed(cls.__mro__):
        for name, value in vars(klass).items():
            # look through `staticmethod` / `classmethod` wrappers:
            spec = getattr(value, PACKET_HANDLER_ATTR, None) or getattr(getattr(value, "__func__", None), PACKET_HANDLER_ATTR, None)
            if isinstance(spec, PacketHandlerSpec):
                by_name[name] = spec
    owners: dict[str, str] = {}
    for name, spec in by_name.items():
        for packet_type in spec.packet_types:
            if (other := owners.setdefault(packet_type, name)) != name:
                raise ValueError(f"{cls.__name__} declares more than one handler for {packet_type!r}: {other} and {name}")
    specs = tuple(by_name.items())
    _specs_cache[cls] = specs
    return specs


_names_cache: dict[type, dict[str, str]] = {}


def get_decorated_handler(obj, packet_type: str) -> Callable | None:
    """
    The method of `obj` decorated with `packet_handler` for this packet type, if any.
    For the endpoints which dispatch their packets themselves, without a `PacketDispatcher`.
    """
    cls = type(obj)
    names = _names_cache.get(cls)
    if names is None:
        names = {}
        for name, spec in get_packet_handler_specs(cls):
            for ptype in spec.packet_types:
                names[ptype] = name
        _names_cache[cls] = names
    name = names.get(packet_type)
    return getattr(obj, name) if name else None


def register_packet_handlers(obj, early: bool | None = None) -> None:
    """
    Register the methods of `obj` decorated with `packet_handler` using `obj.add_packet_handler`.
    `early` selects the handlers registered before (`True`) or after (`False`) authentication,
    `None` registers both.
    The `manual` handlers, and those whose `enabled` predicate is false, are skipped.
    """
    for name, spec in get_packet_handler_specs(type(obj)):
        if spec.manual:
            continue
        if early is not None and spec.early != early:
            continue
        if spec.enabled and not spec.enabled(obj):
            log("%s.%s not enabled", type(obj).__name__, name)
            continue
        handler = getattr(obj, name)
        for packet_type in spec.packet_types:
            obj.add_packet_handler(packet_type, handler, spec.main_thread)


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

    def register_packet_handlers(self, early: bool | None = None) -> None:
        """ register the methods decorated with `packet_handler` """
        register_packet_handlers(self, early)

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
        # what to do when a packet handler fails, see `parse_packet_error_policy`:
        self.packet_error_policy: tuple[int, str] = PACKET_ERROR_POLICY
        # number of packet handler errors, per protocol:
        self.packet_errors: WeakKeyDictionary = WeakKeyDictionary()

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

    def register_packet_handlers(self, early: bool | None = None) -> None:
        """ register the methods decorated with `packet_handler` """
        register_packet_handlers(self, early)

    def dispatch_packet(self, proto, packet: Packet, authenticated=False) -> None:
        packet_type = packet.get_type()
        handler: Callable = noop

        def call_handler(main: bool) -> None:
            may_log_packet(False, packet_type, packet)
            self.call_packet_handler(main, handler, proto, packet)

        try:
            if authenticated and not proto.is_closed():
                if handler := self._authenticated_ui_packet_handlers.get(packet_type, noop):
                    log("process ui packet %s", packet_type)
                    call_handler(True)
                    return
                if handler := self._authenticated_packet_handlers.get(packet_type, noop):
                    log("process non-ui packet %s", packet_type)
                    call_handler(False)
                    return
                if found := find_packet_handler(self.subsystems, packet_type):
                    sub, _, handler, main_thread = found
                    log("process %s packet %s", sub.PREFIX, packet_type)
                    call_handler(main_thread)
                    return
            if handler := self._default_ui_packet_handlers.get(packet_type, noop):
                log("process default ui packet %s", packet_type)
                call_handler(True)
                return
            if handler := self._default_packet_handlers.get(packet_type, noop):
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
            except (AssertionError, TypeError, ValueError, IndexError, RuntimeError):
                self.packet_handler_error(proto, packet)

        if main:
            self.call_in_main_thread(call)
        else:
            call()

    def packet_handler_error(self, proto, packet: Packet) -> None:
        """
        Called from the `except` block of a failed packet handler,
        logs the error and applies the `packet_error_policy`.
        """
        log_count, action = self.packet_error_policy
        packet_type = packet.get_type()
        try:
            count = self.packet_errors.get(proto, 0) + 1
            self.packet_errors[proto] = count
        except TypeError:
            # not weak-referenceable:
            count = 1
        message = f"Error processing {packet_type!r} packet"
        if action == "ignore" or action == "log" and 0 <= log_count < count:
            log(message, exc_info=True)
            return
        log.error(message, exc_info=True)
        if action == "log":
            if count == log_count:
                log.error(f" {count} packet handler errors from {proto}, further errors will not be logged")
            return
        if count <= log_count:
            return
        if action == "disconnect":
            if proto.is_closed():
                return
            log.error(f" disconnecting {proto} after {count} packet handler error{'s' if count > 1 else ''}")

            def disconnect() -> None:
                if not proto.is_closed():
                    self.packet_error_disconnect(proto, packet_type)
            self.call_in_main_thread(disconnect)
        elif action == "exit":
            log.error(f" exiting after {count} packet handler error{'s' if count > 1 else ''} from {proto}")
            self.call_in_main_thread(lambda: self.packet_error_exit(packet_type))

    @staticmethod
    def packet_error_disconnect(proto, packet_type: str) -> None:
        log("packet_error_disconnect(%s, %r)", proto, packet_type)
        proto.close()

    @staticmethod
    def packet_error_exit(packet_type: str) -> None:
        log("packet_error_exit(%r)", packet_type)
        force_quit(int(ExitCode.PACKET_FAILURE))

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
