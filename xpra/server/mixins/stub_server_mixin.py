# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
from typing import Callable, Any, List, Dict

from xpra.util import typedict
from xpra.os_util import WIN32
from xpra.net.common import ServerPacketHandlerType


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

    def init_state(self) -> None:
        """
        Initialize state attributes.
        """

    def add_init_thread_callback(self, callback:Callable) -> None:
        """
        Adds a callback that will be executed
        after the init thread has completed.
        """


    def reset_focus(self) -> None:
        """
        Called when we reset the focus.
        """

    def last_client_exited(self) -> None:
        """
        Called when the last client has exited,
        so we can reset things to their original state.
        """

    def cleanup(self) -> None:
        """
        Free up any resources.
        """

    def setup(self) -> None:
        """
        After initialization, prepare to run.
        """

    def threaded_setup(self) -> None:
        """
        Prepare to run, this method runs in parallel to start faster.
        """

    def init_sockets(self, _sockets) -> None:
        """
        Prepare to handle connections from the given sockets.
        """

    def get_caps(self, _source) -> Dict[str,Any]:
        """
        Capabilities provided by this mixin.
        """
        return {}

    def get_server_features(self, _source) -> Dict[str,Any]:
        """
        Features provided by this mixin.
        (the difference with capabilities is that those will only
        be returned if the client requests 'features')
        """
        return {}

    def set_session_driver(self, _source) -> None:
        """
        When the user in control of the session changes,
        this method will be called.
        """

    def get_info(self, _proto) -> Dict[str,Any]:
        """
        Runtime information on this mixin, includes state and settings.
        Somewhat overlaps with the capabilities and features,
        but the data is returned in a structured format. (ie: nested dictionaries)
        """
        return {}

    def get_ui_info(self, proto, client_uuids=None, *args) -> Dict[str,Any]:
        """
        Runtime information on this mixin,
        unlike get_info() this method will be called
        from the UI thread.
        """
        return {}

    def init_packet_handlers(self) -> None:
        """
        Register the packet types that this mixin can handle.
        """

    def parse_hello(self, ss, caps : typedict, send_ui : bool) -> None:
        """
        Parse capabilities from a new connection.
        """

    def add_new_client(self, ss, c, send_ui, share_count : int) -> None:
        """
        A new client is being handled, take any action needed.
        """

    def send_initial_data(self, ss, caps, send_ui, share_count : int) -> None:
        """
        A new connection has been accepted, send initial data.
        """

    def cleanup_protocol(self, protocol) -> None:
        """
        Cleanup method for a specific connection.
        (to clean up / free up resources associated with a specific client or connection)
        """


    def get_child_env(self) -> Dict[str,str]:
        return os.environ.copy()


    def get_full_child_command(self, cmd, _use_wrapper : bool=True) -> List[str]:
        #make sure we have it as a list:
        if isinstance(cmd, (list, tuple)):
            return list(cmd)
        if WIN32:   #pragma: no cover
            return [cmd]
        return shlex.split(str(cmd))


    def get_http_scripts(self) -> Dict[str,Callable]:
        return {}


    def add_packet_handler(self, packet_type : str, handler : ServerPacketHandlerType, main_thread=True) -> None:
        """ register a packet handler """

    def add_packet_handlers(self, defs : Dict[str,ServerPacketHandlerType], main_thread=True) -> None:
        """ register multiple packet handlers """

    def get_server_source(self, proto):
        return None
