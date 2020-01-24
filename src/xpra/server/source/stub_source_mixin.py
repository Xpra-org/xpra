# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import typedict

"""
Base class for client-connection mixins.
Defines the default interface methods that each mixin may override.
"""
class StubSourceMixin:

    """
    Is this mixin needed for the caps given?
    """
    @classmethod
    def is_needed(cls, caps : typedict) -> bool:
        return True

    def __init__(self, *_args):
        pass

    def init_state(self):
        """
        Initialize state attributes.
        """

    def init_from(self, _protocol, _server):
        """
        Initialize setting inherited from the server or connection.
        """

    def cleanup(self):
        """
        Free up any resources.
        """

    def is_closed(self) -> bool:
        """
        When the connection is closed or closing, this method returns True.
        """
        return False

    def parse_client_caps(self, c : typedict):
        """
        Parse client attributes specified in the hello capabilities.
        """

    def get_caps(self) -> dict:
        """
        Return the capabilities provided by this mixin.
        """
        return {}

    def get_info(self) -> dict:
        """
        Runtime information on this mixin, includes state and settings.
        Somewhat overlaps with the capabilities,
        but the data is returned in a structured format. (ie: nested dictionaries)
        """
        return {}

    def user_event(self):
        """
        This method is called every time a user action (keyboard, mouse, etc) is being handled.
        """

    def may_notify(self, *args, **kwargs):
        """
        The actual source implementation will handle these notification requests
        by forwarding them to the client.
        This dummy implementation makes it easier to test without a network connection.
        """

    def queue_encode(self, item):
        pass

    def send_more(self, *parts, **kwargs):
        pass

    def send_async(self, *parts, **kwargs):
        pass
