# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
from typing import Any
from collections.abc import Callable

from xpra.util.env import envbool
from xpra.os_util import getuid, getgid
from xpra.util.objects import typedict
from xpra.os_util import WIN32

# when running the unit tests,
# we inject the signal emitter into the signal hierarchy,
# whereas regular server classes inherit the GObject methods:
if envbool("XPRA_UNIT_TEST"):
    from xpra.util.signal_emitter import SignalEmitter
    superclass = SignalEmitter
else:
    superclass = object


class StubServerMixin(superclass):
    """
    Base class for server subsystem.
    Defines the default interface methods that each mixin may override.
    """
    __signals__: dict[str, int] = {}
    uid = getuid()
    gid = getgid()
    hello_request_handlers: dict[str, Callable[[Any, typedict], bool]] = {}

    def init(self, opts) -> None:
        """
        Initialize this instance with the options given.
        Options are usually obtained by parsing the command line,
        or using a default configuration object.
        """
        self.uid = opts.uid
        self.gid = opts.gid

    def init_state(self) -> None:
        """
        Initialize state attributes.
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

    def late_cleanup(self, stop=True) -> None:
        """
        Free up any resources, after main cleanup.
        `stop` is set to True when we are meant to stop all subprocesses we are responsible for.
        (ie: `Xvfb` and such)
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

    def get_caps(self, _source) -> dict[str, Any]:
        """
        Capabilities provided by this mixin.
        """
        return {}

    def get_server_features(self, _source) -> dict[str, Any]:
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

    def get_info(self, _proto) -> dict[str, Any]:
        """
        Runtime information on this mixin, includes state and settings.
        Somewhat overlaps with the capabilities and features,
        but the data is returned in a structured format. (ie: nested dictionaries)
        """
        return {}

    def get_ui_info(self, _proto, **kwargs) -> dict[str, Any]:
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

    def parse_hello(self, ss, caps: typedict, send_ui: bool) -> None:
        """
        Parse capabilities from a new connection.
        """

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        """
        A new client is being handled, take any action needed.
        """

    def remove_client(self, ss) -> None:
        """
        A client is being removed, take any action needed.
        """

    def send_initial_data(self, ss, caps, send_ui, share_count: int) -> None:
        """
        A new connection has been accepted, send initial data.
        """

    def cleanup_protocol(self, protocol) -> None:
        """
        Cleanup method for a specific connection.
        (to clean up / free up resources associated with a specific client or connection)
        """

    def get_child_env(self) -> dict[str, str]:
        return os.environ.copy()

    def get_full_child_command(self, cmd, _use_wrapper: bool = True) -> list[str]:
        # make sure we have it as a list:
        if isinstance(cmd, (list, tuple)):
            return list(cmd)
        if WIN32:  # pragma: no cover
            return [cmd]
        return shlex.split(str(cmd))

    @staticmethod
    def get_server_source(_proto):
        """ returns the client connection source object for the given protocol """
        return None
