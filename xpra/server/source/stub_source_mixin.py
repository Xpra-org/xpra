# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable
from xpra.util.objects import typedict
from xpra.net.common import PacketElement


class StubSourceMixin:
    """
    Base class for client-connection mixins.
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

    def threaded_init_complete(self, server) -> None:
        """
        This method is called after the server's threaded initialization is complete,
        and after `get_caps()` has already been called to send the `hello` packet to the client.
        """

    def get_info(self) -> dict[str, Any]:
        """
        Runtime information on this mixin, includes state and settings.
        Somewhat overlaps with the capabilities,
        but the data is returned in a structured format. (ie: nested dictionaries)
        """
        return {}

    def user_event(self) -> None:
        """
        This method is called every time a user action (keyboard, mouse, etc) is being handled.
        """

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

    def suspend(self) -> None:
        """
        The client is not interacting with the window and may even suspend the session completely,
        take appropriate measures to handle this.
        Typically this means we stop sending screen and cursor updates.
        """

    def resume(self) -> None:
        """
        The client is resuming the session, so whatever was suspended needs resuming.
        """
