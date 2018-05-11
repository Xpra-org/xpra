# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Base class for client-connection mixins.
Defines the default interface methods that each mixin may override.
"""
class StubSourceMixin(object):

    """
    Initialize state attributes.
    """
    def init_state(self):
        pass

    """
    Initialize setting inherited from the server or connection.
    """
    def init_from(self, _protocol, _server):
        pass

    """
    Free up any resources.
    """
    def cleanup(self):
        pass

    """
    When the connection is closed or closing, this method returns True.
    """
    def is_closed(self):
        return False

    """
    Parse client attributes specified in the hello capabilities.
    """
    def parse_client_caps(self, c):
        pass

    """
    Return the capabilities provided by this mixin.
    """
    def get_caps(self):
        return {}

    """
    Runtime information on this mixin, includes state and settings.
    Somewhat overlaps with the capabilities,
    but the data is returned in a structured format. (ie: nested dictionaries)
    """
    def get_info(self):
        return {}

    """
    This method is called every time a user action (keyboard, mouse, etc) is being handled.
    """
    def user_event(self):
        pass

    """
    The actual source implementation will handle these notification requests
    by forwarding them to the client.
    This dummy implementation makes it easier to test without a network connection.
    """
    def may_notify(self, *args, **kwargs):
        pass
