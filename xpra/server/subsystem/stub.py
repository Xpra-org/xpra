# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import shlex
from typing import Any
from collections.abc import Callable

from xpra.net.constants import ConnectionMessage
from xpra.util.signal_emitter import SignalEmitter
from xpra.util.objects import typedict
from xpra.common import noop
from xpra.os_util import WIN32


class StubSubsystem(SignalEmitter):
    """
    Base class for server subsystems.
    Defines the default interface methods that each subsystem may override.
    """
    # `_signal_callbacks` and `main_loop` belong to `SignalEmitter`, but it cannot
    # declare them itself (see the note there), so they are declared here, where
    # the slots actually take effect:
    __slots__ = ("__weakref__", "_signal_callbacks", "idle_add", "main_loop",
                 "server", "source_remove", "timeout_add")
    # every concrete subsystem should declare a non-empty PREFIX,
    # used as the key in `Server.subsystems`:
    PREFIX: str = ""

    def __init__(self, server=None):
        # Every subsystem holds a reference to its owning server.
        # Subsystem-local signals (e.g. `audio-initialized`,
        # `display-geometry-changed`) use this instance's SignalEmitter;
        # server-wide GObject signals are accessed via `self.server`.
        self.server = server
        # copy scheduler methods from the server if it provides them, GLib otherwise.
        # (unlike the client, subsystems are always constructed with a server,
        # so the case that matters here is a stand-in that has no scheduler)
        source = server
        if not server or not hasattr(server, "idle_add"):
            from xpra.util.glib_scheduler import GLibScheduler
            source = GLibScheduler
        self.idle_add: Callable = source.idle_add
        self.timeout_add: Callable = source.timeout_add
        self.source_remove: Callable = source.source_remove
        SignalEmitter.__init__(self)

    def get_main_loop(self):
        return getattr(self.server, "main_loop", None)

    def get_server_source(self, proto):
        """ delegate to the server's per-protocol client source lookup """
        return self.server.get_server_source(proto)

    def get_subsystem(self, name: str):
        """ look up a peer subsystem on the owning server """
        return self.server.subsystems.get(name)

    def get_sources_by_type(self, subsystem_type=object, exclude=None):
        """ delegate to the server's typed source iterator """
        from xpra.server.common import get_sources_by_type
        return get_sources_by_type(self.server, subsystem_type, exclude)

    def is_readonly(self, proto=None) -> bool:
        if getattr(self.server, "readonly", False):
            return True
        if proto is None:
            return False
        ss = self.get_server_source(proto)
        if ss and hasattr(ss, "effective_readonly"):
            return ss.effective_readonly()
        return False

    def add_packets(self, *packet_types: str, main_thread: bool = False) -> None:
        """
        Register packet handlers for this subsystem. Handlers
        (`_process_<packet_type>`) are looked up on the subsystem
        instance and registered against the server's packet dispatcher.
        """
        for packet_type in packet_types:
            handler = getattr(self, "_process_" + packet_type.replace("-", "_"))
            self.server.add_packet_handler(packet_type, handler, main_thread)

    def add_packet_handler(self, packet_type: str, handler: Callable, main_thread: bool = False) -> None:
        """ register a single packet handler on the owning server """
        self.server.add_packet_handler(packet_type, handler, main_thread)

    def add_legacy_alias(self, legacy_name: str, new_name: str) -> None:
        """ register a backwards-compat packet name alias on the owning server """
        self.server.add_legacy_alias(legacy_name, new_name)

    def setting_changed(self, setting: str, value: Any) -> None:
        """ broadcast a server setting change to all connected clients """
        self.server.setting_changed(setting, value)

    def init(self, opts) -> None:
        """
        Initialize this instance with the options given.
        Options are usually obtained by parsing the command line,
        or using a default configuration object.
        """

    def init_state(self) -> None:
        """
        Initialize state attributes.
        """

    def setup(self) -> None:
        """
        After initialization, prepare to run.
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

    def get_caps(self, _source) -> dict[str, Any]:
        """
        Capabilities provided by this subsystem.
        """
        return {}

    def get_server_features(self, _source) -> dict[str, Any]:
        """
        Features provided by this subsystem.
        (the difference with capabilities is that those will only
        be returned if the client requests 'features')
        """
        return {}

    def get_info(self, _proto) -> dict[str, Any]:
        """
        Runtime information on this subsystem, includes state and settings.
        Somewhat overlaps with the capabilities and features,
        but the data is returned in a structured format. (ie: nested dictionaries)
        """
        return {}

    def get_ui_info(self, _proto, **kwargs) -> dict[str, Any]:
        """
        Runtime information on this subsystem,
        unlike get_info() this method will be called
        from the UI thread.
        """
        return {}

    def init_packet_handlers(self) -> None:
        """
        Register the packet types that this subsystem can handle.
        """

    def parse_hello(self, ss, caps: typedict) -> str | ConnectionMessage:
        """
        Parse capabilities from a new connection.
        """
        return ""

    def add_new_client(self, ss, c: typedict) -> None:
        """
        A new client is being handled, take any action needed.
        """

    def send_initial_data(self, ss) -> None:
        """
        A new connection has been accepted, send initial data.
        """

    def cleanup_protocol(self, protocol) -> None:
        """
        Cleanup method for a specific connection.
        (to clean up / free up resources associated with a specific client or connection)
        """

    def get_child_env(self) -> dict[str, str]:
        # Subsystems contribute *additions* to the child env. The base
        # implementation in `ServerCore` seeds the result with a filtered
        # `os.environ`; `ServerBase.get_child_env` then merges subsystem
        # contributions on top via `_dispatch_merge`.
        return {}

    def get_full_child_command(self, cmd, _use_wrapper: bool = True) -> list[str]:
        # make sure we have it as a list:
        if isinstance(cmd, (list, tuple)):
            return list(cmd)
        if WIN32:  # pragma: no cover
            return [cmd]
        return shlex.split(str(cmd))

    def args_control(self, name: str, descr: str, **kwargs) -> None:
        """
        Register an args-style control command on the `control` subsystem.
        The `control_command_X` implementation is looked up on `self` (the
        subsystem that owns the command), not on the server.
        """
        control = self.get_subsystem("control")
        if not control:
            return
        run = getattr(self, "control_command_%s" % name.replace("-", "_"), noop)
        if run == noop:
            from xpra.log import Logger
            Logger("util").warn("Warning: control command %r not found on %s", name, self)
            return
        kwargs["run"] = run
        from xpra.net.control.common import add_args_control_command
        add_args_control_command(control, name, descr, **kwargs)

    def add_control_command(self, name: str, control) -> None:
        """ register a control command on the `control` subsystem """
        control_subsystem = self.get_subsystem("control")
        if control_subsystem:
            control_subsystem.add_control_command(name, control)
