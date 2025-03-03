# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import signal
from typing import Any

from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("dbus")


class DbusServer(StubServerMixin):
    """
    Mixin for servers that have a dbus server associated with them
    """
    PREFIX = "dbus"

    def __init__(self):
        self.dbus_pid: int = 0
        self.dbus_env: dict[str, str] = {}
        self.dbus_control: bool = False
        self.dbus_server = None

    def init(self, opts) -> None:
        self.dbus_control = opts.dbus_control

    def init_dbus(self, dbus_pid: int, dbus_env: dict[str, str]) -> None:
        log("init_dbus(%i, %s)", dbus_pid, dbus_env)
        self.dbus_pid = dbus_pid
        self.dbus_env = dbus_env

    def setup(self) -> None:
        log("init_dbus_server() dbus_control=%s", self.dbus_control)
        log("init_dbus_server() env: %s", {k: v for k, v in os.environ.items() if k.startswith("DBUS_")})
        if not self.dbus_control:
            return
        try:
            from xpra.server.dbus.common import dbus_exception_wrap
            self.dbus_server = dbus_exception_wrap(self.make_dbus_server, "setting up server dbus instance")
        except Exception as e:
            log("init_dbus_server()", exc_info=True)
            log.error("Error: cannot load dbus server:")
            log.estr(e)
            self.dbus_server = None

    def cleanup(self) -> None:
        ds = self.dbus_server
        log(f"cleanup_dbus_server() dbus_server={ds}")
        if ds:
            ds.cleanup()
            self.dbus_server = None

    def late_cleanup(self, stop=True) -> None:
        if stop:
            self.stop_dbus_server()

    def stop_dbus_server(self) -> None:
        log("stop_dbus_server() dbus_pid=%s", self.dbus_pid)
        if not self.dbus_pid:
            return
        try:
            os.kill(self.dbus_pid, signal.SIGINT)
            self.do_clean_session_files("dbus.pid", "dbus.env")
        except ProcessLookupError:
            log("os.kill(%i, SIGINT)", self.dbus_pid, exc_info=True)
            log.warn(f"Warning: dbus process not found (pid={self.dbus_pid})")
        except Exception as e:
            log("os.kill(%i, SIGINT)", self.dbus_pid, exc_info=True)
            log.warn(f"Warning: error trying to stop dbus with pid {self.dbus_pid}:")
            log.warn(" %s", e)

    def make_dbus_server(self):  # pylint: disable=useless-return
        log(f"make_dbus_server() no dbus server for {self}")
        return None

    def get_info(self, _proto=None) -> dict[str, Any]:
        if not self.dbus_pid or not self.dbus_env:
            return {}
        return {
            DbusServer.PREFIX: {
                "pid": self.dbus_pid,
                "env": self.dbus_env,
            }
        }
