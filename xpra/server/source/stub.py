# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable
from xpra.util.objects import typedict
from xpra.util.signal_emitter import SignalEmitter
from xpra.net.common import PacketElement


def is_option_allowed(server_source, option: str, subsystem: str, default: str) -> bool:
    """
    Is this client allowed to `option` the events of the `subsystem` given?
    This is controlled by the socket option of the same name,
    which can be a boolean, `all`, or a comma separated list of subsystem names.
    """
    proto = getattr(server_source, "protocol", None)
    conn = getattr(proto, "_conn", None)
    options = getattr(conn, "options", None) or {}
    value = str(options.get(option, default))
    from xpra.log import Logger
    log = Logger("server", "auth")
    log("client wants to %s %r events", option, subsystem)
    log(" proto=%s, conn=%s, options=%s, %s=%s", proto, conn, options, option, value)
    from xpra.util.parsing import str_to_bool
    values = tuple(x.strip() for x in value.split(","))
    if str_to_bool(value, False) or subsystem in values or "all" in values:
        if option in options:
            # only worth reporting when the option was set explicitly:
            log.info("%r %s enabled for connection %s", subsystem, option, conn)
        return True
    log.warn("Warning: client %s is not allowed to %s %r events", conn, option, subsystem)
    return False


def is_recording_allowed(server_source, subsystem: str) -> bool:
    """ recording the events of the other clients is denied unless the `record` socket option allows it """
    return is_option_allowed(server_source, "record", subsystem, "no")


def is_sync_allowed(server_source, subsystem: str) -> bool:
    """ synchronizing with the other clients is allowed unless the `sync` socket option denies it """
    return is_option_allowed(server_source, "sync", subsystem, "yes")


class PointerSource:
    """
    Marker base for any server-side source that can receive server-driven
    pointer-position updates.

    Lives in this always-importable module so the shadow polling loop can
    iterate by base class without importing the pointer or rfb subsystems
    directly (either may be disabled by `enforce_features`).
    """
    __slots__ = ()

    def update_mouse(self, wid: int, x: int, y: int, rx: int, ry: int) -> None:
        """ Override to push the new pointer position to the client. """


class StubClientConnection(SignalEmitter):
    """
    Base class for client-connection subsystem.
    Defines the default interface methods that each mixin may override.
    """

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:  # pylint: disable=unused-argument
        """
        Is this mixin needed for the caps given?
        """
        return True

    def get_main_loop(self):
        server = getattr(self, "server", None)
        return getattr(server, "main_loop", None)

    def init_state(self) -> None:
        """
        Initialize state attributes.
        """

    def init_from(self, _protocol, server) -> None:
        """
        Initialize setting inherited from the server or connection.
        """
        self.server = server

    def cleanup(self) -> None:
        """
        Free up any resources.
        """

    def is_closed(self) -> bool:
        """
        When the connection is closed or closing, this method returns True.
        """
        return False

    def requires_sharing(self) -> bool:
        """
        Does this subsystem require 'sharing' to be enabled for multiple active clients?
        """
        return False

    def user_event(self, msg: str) -> None:
        """
        Notify the idle mixin, when it is present, that this connection has seen
        user activity.
        """
        if "user-event" in getattr(self, "__signals__", ()):
            self.emit("user-event", msg)

    def parse_client_caps(self, c: typedict) -> None:
        """
        Parse client attributes specified in the hello capabilities.
        """

    def get_caps(self) -> dict[str, Any]:
        """
        Return the capabilities provided by this mixin.
        """
        return {}

    def get_info(self) -> dict[str, Any]:
        """
        Runtime information on this mixin, includes state and settings.
        Somewhat overlaps with the capabilities,
        but the data is returned in a structured format. (ie: nested dictionaries)
        """
        return {}

    def queue_encode(self, item: None | tuple[bool, Callable, tuple]) -> None:
        """
        Used by the window source to send data to be processed in the encode thread
        """

    def send_more(self, packet_type: str, *parts: PacketElement, **kwargs) -> None:
        """
        Send a packet to the client,
        the `will_have_more` argument will be set to `True`
        """

    def send_async(self, packet_type: str, *parts: PacketElement, **kwargs) -> None:
        """
        Send a packet to the client,
        the `synchronous` and `will_have_more` arguments will be set to `False`
        """
