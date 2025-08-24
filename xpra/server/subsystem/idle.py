# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.os_util import gi_import
from xpra.server import ServerExitMode
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("timeout")

GLib = gi_import("GLib")


class IdleTimeoutServer(StubServerMixin):

    def __init__(self):
        StubServerMixin.__init__(self)
        self.server_idle_timeout = 0
        self.server_idle_timer = 0

    def init(self, opts) -> None:
        self.server_idle_timeout = opts.server_idle_timeout

    def threaded_setup(self) -> None:
        self.schedule_server_timeout()

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        self.cancel_server_timeout()

    def last_client_exited(self) -> None:
        self.schedule_server_timeout()

    def cancel_server_timeout(self) -> None:
        log("cancel_server_timeout() timer=%s", self.server_idle_timer)
        if self.server_idle_timeout <= 0:
            return
        if self.server_idle_timer:
            GLib.source_remove(self.server_idle_timer)
            self.server_idle_timer = 0

    def schedule_server_timeout(self) -> None:
        log("schedule_server_timeout() server_idle_timeout=%s", self.server_idle_timeout)
        self.cancel_server_timeout()
        self.server_idle_timer = GLib.timeout_add(self.server_idle_timeout * 1000, self.server_idle_timedout)

    def server_idle_timedout(self) -> None:
        log.info("No valid client connections for %s seconds, exiting the server", self.server_idle_timeout)
        self.clean_quit(ServerExitMode.NORMAL)

    def cleanup(self) -> None:
        self.cancel_server_timeout()

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "idle-timeout": int(self.server_idle_timeout),
        }
