# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server import ServerExitMode
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("timeout")


class IdleTimeoutManager(StubSubsystem):
    PREFIX = "idle"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.server_timeout = 0
        self.timeout = 0
        self.server_timer = 0

    def init(self, opts) -> None:
        self.server_timeout = opts.server_idle_timeout
        self.timeout = opts.idle_timeout

    def setup(self) -> None:
        self.schedule_server_timeout()
        self.server.connect("last-client-exited", self.schedule_server_timeout)
        self.add_idle_control_commands()

    def add_idle_control_commands(self) -> None:
        self.args_control("server-idle-timeout", "set the server idle timeout", validation=[int])
        self.args_control("idle-timeout", "set the idle timeout", validation=[int]),

    def add_new_client(self, *_args) -> None:
        self.cancel_server_timeout()

    def cancel_server_timeout(self) -> None:
        log("cancel_server_timeout() timer=%s", self.server_timer)
        if self.server_timeout <= 0:
            return
        if self.server_timer:
            self.source_remove(self.server_timer)
            self.server_timer = 0

    def schedule_server_timeout(self, *args) -> None:
        log("schedule_server_timeout%s server_idle_timeout=%s", args, self.server_timeout)
        self.cancel_server_timeout()
        self.server_timer = self.timeout_add(self.server_timeout * 1000, self.server_idle_timedout)

    def server_idle_timedout(self) -> None:
        log.info("No valid client connections for %s seconds, exiting the server", self.server_timeout)
        self.server.clean_quit(ServerExitMode.NORMAL)

    def cleanup(self) -> None:
        self.cancel_server_timeout()

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "server-idle-timeout": int(self.server_timeout),
            "idle-timeout": self.timeout,
        }

    #########################################
    # Control Commands
    #########################################

    def control_command_server_idle_timeout(self, t: int) -> str:
        self.server_timeout = t
        all_sources = self.get_sources_by_type()
        if not all_sources:
            self.schedule_server_timeout()
        return f"server-idle-timeout set to {t}"

    def control_command_idle_timeout(self, t: int) -> str:
        self.timeout = t
        try:
            from xpra.server.source.idle_mixin import IdleConnection
        except ImportError:
            return "no idle connection support"
        idle_connections = self.get_sources_by_type(IdleConnection)
        for csource in idle_connections:
            csource.idle_timeout = t
            csource.schedule_idle_timeout()
        return f"idle-timeout set to {t} for {len(idle_connections)} connections"
