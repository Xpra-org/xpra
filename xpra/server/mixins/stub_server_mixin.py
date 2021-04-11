# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

class StubServerMixin(object):
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
        pass

    def init_state(self):
        """
        Initialize state attributes.
        """
        pass


    def reset_focus(self):
        """
        Called when we reset the focus.
        """
        pass

    def last_client_exited(self):
        """
        Called when the last client has exited,
        so we can reset things to their original state.
        """
        pass

    def cleanup(self):
        """
        Free up any resources.
        """
        pass

    def setup(self):
        """
        After initialization, prepare to run.
        """
        pass

    def threaded_setup(self):
        """
        Prepare to run, this method runs in parallel to save startup time.
        """
        pass

    def init_sockets(self, _sockets):
        """
        Prepare to handle connections from the given sockets.
        """
        pass

    def get_caps(self, _source):
        """
        Capabilities provided by this mixin.
        """
        return {}

    def get_server_features(self, _source):
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
        pass

    def get_info(self, _proto):
        """
        Runtime information on this mixin, includes state and settings.
        Somewhat overlaps with the capabilities and features,
        but the data is returned in a structured format. (ie: nested dictionaries)
        """
        return {}

    def get_ui_info(self, proto, client_uuids=None, *args):
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
        pass

    def parse_hello(self, ss, caps, send_ui):
        """
        Parse capabilities from a new connection.
        """
        pass

    def add_new_client(self, ss, c, send_ui, share_count):
        """
        A new client is being handled, take any action needed.
        """
        pass

    def send_initial_data(self, ss, caps, send_ui, share_count):
        """
        A new connection has been accepted, send initial data.
        """
        pass

    def cleanup_protocol(self, protocol):
        """
        Cleanup method for a specific connection.
        (to cleanup / free up resources associated with a specific client or connection)
        """
        pass

    def add_packet_handler(self, packet_type, handler, main_thread=True):
        pass

    def add_packet_handlers(self, defs, main_thread=True):
        pass

    def get_server_source(self, proto):
        return None
