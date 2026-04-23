# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.common import noop
from xpra.server import ServerExitMode
from xpra.server.common import get_sources_by_type
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("timeout")

GLib = gi_import("GLib")


class IdleTimeoutServer(StubServerMixin):

    def __init__(self):
        StubServerMixin.__init__(self)
        self.server_idle_timeout = 0
        self.idle_timeout = 0
        self.server_idle_timer = 0

    def init(self, opts) -> None:
        self.server_idle_timeout = opts.server_idle_timeout
        self.idle_timeout = opts.idle_timeout

    def setup(self) -> None:
        self.schedule_server_timeout()
        self.connect("last-client-exited", self.schedule_server_timeout)
        self.add_idle_control_commands()

    def add_idle_control_commands(self) -> None:
        self.args_control("server-idle-timeout", "set the server idle timeout", validation=[int])
        self.args_control("idle-timeout", "set the idle timeout", validation=[int]),

    def add_new_client(self, *_args) -> None:
        self.cancel_server_timeout()

    def cancel_server_timeout(self) -> None:
        log("cancel_server_timeout() timer=%s", self.server_idle_timer)
        if self.server_idle_timeout <= 0:
            return
        if self.server_idle_timer:
            GLib.source_remove(self.server_idle_timer)
            self.server_idle_timer = 0

    def schedule_server_timeout(self, *args) -> None:
        log("schedule_server_timeout%s server_idle_timeout=%s", args, self.server_idle_timeout)
        self.cancel_server_timeout()
        self.server_idle_timer = GLib.timeout_add(self.server_idle_timeout * 1000, self.server_idle_timedout)

    def server_idle_timedout(self) -> None:
        log.info("No valid client connections for %s seconds, exiting the server", self.server_idle_timeout)
        self.clean_quit(ServerExitMode.NORMAL)

    def cleanup(self) -> None:
        self.cancel_server_timeout()

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "server-idle-timeout": int(self.server_idle_timeout),
            "idle-timeout": self.idle_timeout,
        }

    #########################################
    # Control Commands
    #########################################

    def control_command_server_idle_timeout(self, t: int) -> str:
        self.server_idle_timeout = t
        all_sources = get_sources_by_type(self)
        # weak dependency on IdleTimeoutServer:
        if not all_sources:
            schedule_server_timeout = getattr(self, "schedule_server_timeout", noop)
            schedule_server_timeout()
        return f"server-idle-timeout set to {t}"

    def control_command_idle_timeout(self, t: int) -> str:
        self.idle_timeout = t
        try:
            from xpra.server.source.idle_mixin import IdleConnection
        except ImportError:
            return "no idle connection support"
        idle_connections = get_sources_by_type(self, IdleConnection)
        for csource in idle_connections:
            csource.idle_timeout = t
            csource.schedule_idle_timeout()
        return f"idle-timeout set to {t} for {len(idle_connections)} connections"
