# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex

from xpra.util import typedict
from xpra.os_util import WIN32


class StubServerMixin:
    """
    Base class for server mixins.
    Defines the default interface methods that each mixin may override.
    """

    def init(self, _opts):
        """
        Initialize this instance with the options given.
        Options are usually obtained by parsing the command line,
        or using a default configuration object.
        """

    def init_state(self):
        """
        Initialize state attributes.
        """


    def reset_focus(self):
        """
        Called when we reset the focus.
        """

    def last_client_exited(self):
        """
        Called when the last client has exited,
        so we can reset things to their original state.
        """

    def cleanup(self):
        """
        Free up any resources.
        """

    def setup(self):
        """
        After initialization, prepare to run.
        """

    def threaded_setup(self):
        """
        Prepare to run, this method runs in parallel to save startup time.
        """

    def init_sockets(self, _sockets):
        """
        Prepare to handle connections from the given sockets.
        """

    def get_caps(self, _source) -> dict:
        """
        Capabilities provided by this mixin.
        """
        return {}

    def get_server_features(self, _source) -> dict:
        """
        Features provided by this mixin.
        (the difference with capabilities is that those will only
        be returned if the client requests 'features')
        """
        return {}

    def set_session_driver(self, _source):
        """
        When the user in control of the session changes,
        this method will be called.
        """

    def get_info(self, _proto) -> dict:
        """
        Runtime information on this mixin, includes state and settings.
        Somewhat overlaps with the capabilities and features,
        but the data is returned in a structured format. (ie: nested dictionaries)
        """
        return {}

    def get_ui_info(self, proto, client_uuids=None, *args) -> dict:
        """
        Runtime information on this mixin,
        unlike get_info() this method will be called
        from the UI thread.
        """
        return {}

    def init_packet_handlers(self):
        """
        Register the packet types that this mixin can handle.
        """

    def parse_hello(self, ss, caps : typedict, send_ui):
        """
        Parse capabilities from a new connection.
        """

    def add_new_client(self, ss, c, send_ui, share_count : int):
        """
        A new client is being handled, take any action needed.
        """

    def send_initial_data(self, ss, caps, send_ui, share_count : int):
        """
        A new connection has been accepted, send initial data.
        """

    def cleanup_protocol(self, protocol):
        """
        Cleanup method for a specific connection.
        (to cleanup / free up resources associated with a specific client or connection)
        """


    def get_child_env(self):
        return os.environ.copy()


    def get_full_child_command(self, cmd, use_wrapper : bool=True) -> list:
        #make sure we have it as a list:
        if isinstance(cmd, (list, tuple)):
            return cmd
        if WIN32:
            return [cmd]
        return shlex.split(str(cmd))


    def add_packet_handler(self, packet_type, handler, main_thread=True):
        pass

    def add_packet_handlers(self, defs, main_thread=True):
        pass

    def get_server_source(self, proto):
        return None
