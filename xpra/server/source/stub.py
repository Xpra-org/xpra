# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable
from xpra.util.objects import typedict
from xpra.util.signal_emitter import SignalEmitter
from xpra.net.common import PacketElement


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

    def init_state(self) -> None:
        """
        Initialize state attributes.
        """

    def init_from(self, _protocol, _server) -> None:
        """
        Initialize setting inherited from the server or connection.
        """

    def cleanup(self) -> None:
        """
        Free up any resources.
        """

    def is_closed(self) -> bool:
        """
        When the connection is closed or closing, this method returns True.
        """
        return False

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

    def may_notify(self, *args, **kwargs) -> None:
        """
        The actual source implementation will handle these notification requests
        by forwarding them to the client.
        This dummy implementation makes it easier to test without a network connection.
        """

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
