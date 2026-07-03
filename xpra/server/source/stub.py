# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable
from xpra.util.objects import typedict
from xpra.util.signal_emitter import SignalEmitter
from xpra.net.common import PacketElement


def is_recording_allowed(server_source, subsystem: str) -> bool:
    proto = getattr(server_source, "protocol", None)
    conn = getattr(proto, "_conn", None)
    options = getattr(conn, "options", None) or {}
    record = options.get("record", "no")
    from xpra.log import Logger
    log = Logger("server", "auth")
    log("client wants to record %r events", subsystem)
    log(" proto=%s, conn=%s, options=%s, record=%s", proto, conn, options, record)
    from xpra.util.parsing import str_to_bool
    if str_to_bool(record) or subsystem in record.split(",") or "all" in record.split(","):
        log.info("%r recording enabled for connection %s", subsystem, conn)
        return True
    log.warn("Warning: client %s is not allowed to record %r events", conn, subsystem)
    return False


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
