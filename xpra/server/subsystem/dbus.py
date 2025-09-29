# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import signal
from typing import Any
from collections.abc import Callable

from xpra.server import features
from xpra.util.pid import load_pid
from xpra.scripts.session import load_session_file, save_session_file
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("dbus")


def reload_dbus_attributes(display_name: str) -> tuple[int, dict[str, str]]:
    session_dir = os.environ.get("XPRA_SESSION_DIR", "")
    dbus_pid = load_pid(os.path.join(session_dir, "dbus.pid"))
    try:
        dbus_env_data = load_session_file("dbus.env").decode("utf8")
        log(f"reload_dbus_attributes({display_name}) dbus_env_data={dbus_env_data}")
    except UnicodeDecodeError:
        log.error("Error decoding dbus.env file", exc_info=True)
        dbus_env_data = ""
    dbus_env = {}
    if dbus_env_data:
        for line in dbus_env_data.splitlines():
            if not line or line.startswith("#") or line.find("=") < 0:
                continue
            parts = line.split("=", 1)
            dbus_env[parts[0]] = parts[1]
    log(f"reload_dbus_attributes({display_name}) dbus_env={dbus_env}")
    dbus_address = dbus_env.get("DBUS_SESSION_BUS_ADDRESS")
    if not (dbus_pid and dbus_address):
        # less reliable: get it from the wminfo output:
        from xpra.scripts.main import exec_wminfo
        wminfo = exec_wminfo(display_name)
        if not dbus_pid:
            try:
                dbus_pid = int(wminfo.get("dbus-pid", 0))
            except ValueError:
                pass
        if not dbus_address:
            dbus_address = wminfo.get("dbus-address", "")
    if dbus_pid and os.path.exists("/proc") and not os.path.exists(f"/proc/{dbus_pid}"):
        log(f"dbus pid {dbus_pid} is no longer valid")
        dbus_pid = 0
    if dbus_pid:
        dbus_env["DBUS_SESSION_BUS_PID"] = str(dbus_pid)
    if dbus_address:
        dbus_env["DBUS_SESSION_BUS_ADDRESS"] = dbus_address
    if dbus_pid and dbus_address:
        log(f"retrieved dbus pid: {dbus_pid}, environment: {dbus_env}")
    return dbus_pid, dbus_env


def save_dbus_x11_properties(dbus_env: dict):
    # now we can save values on the display
    # (we cannot access bindings until dbus has started up)
    from xpra.x11.xroot_props import root_set

    def _save_int(prop_name, intval) -> None:
        root_set(prop_name, "u32", intval)

    def _save_str(prop_name, strval) -> None:
        root_set(prop_name, "latin1", strval)

    # DBUS_SESSION_BUS_ADDRESS=unix:abstract=/tmp/dbus-B8CDeWmam9,guid=b77f682bd8b57a5cc02f870556cbe9e9
    # DBUS_SESSION_BUS_PID=11406
    # DBUS_SESSION_BUS_WINDOWID=50331649
    attributes: list[tuple[str, type, Callable[[str, int | str], None]]] = [
        ("ADDRESS", str, _save_str),
        ("PID", int, _save_int),
        ("WINDOW_ID", int, _save_int),
    ]
    for name, conv, save in attributes:
        k = f"DBUS_SESSION_BUS_{name}"
        v = dbus_env.get(k, "")
        if not v:
            continue
        try:
            tv = conv(v)
            save(k, tv)
        except Exception as e:
            log("save_dbus_env(%s)", dbus_env, exc_info=True)
            log.error(f"Error: failed to save dbus environment variable {k!r}")
            log.error(f" with value {v!r}")
            log.estr(e)


class DbusServer(StubServerMixin):
    """
    Mixin for servers that have a dbus server associated with them
    """
    PREFIX = "dbus"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.dbus = False
        self.dbus_launch = "dbus-launch --sh-syntax --close-stderr"
        self.dbus_pid: int = 0
        self.dbus_env: dict[str, str] = {}
        self.dbus_control: bool = False
        self.dbus_server = None
        self.session_files: list[str] = []

    def init(self, opts) -> None:
        self.dbus = opts.dbus
        self.dbus_launch = opts.dbus_launch
        self.dbus_control = opts.dbus_control

    def setup(self) -> None:
        if self.dbus:
            self.init_dbus_env()
            if self.dbus_control:
                self.init_dbus_server()

    def init_dbus_env(self) -> None:
        log("init_dbus_env()")
        display_name = os.environ.get("DISPLAY", "")
        self.dbus_pid, self.dbus_env = reload_dbus_attributes(display_name)
        if self.dbus_pid and self.dbus_env:
            return
        try:
            from xpra.server.dbus.start import start_dbus
        except ImportError as e:
            log("dbus components are not installed: %s", e)
            return
        self.dbus_pid, self.dbus_env = start_dbus(self.dbus_launch)
        if not self.dbus_env:
            return
        log(f"started new dbus instance: {self.dbus_env}")
        save_session_file("dbus.pid", f"{self.dbus_pid}", self.uid, self.gid)
        dbus_env_data = "\n".join(f"{k}={v}" for k, v in self.dbus_env.items()) + "\n"
        save_session_file("dbus.env", dbus_env_data.encode("utf8"), self.uid, self.gid)
        self.session_files += ["dbus.pid", "dbus.env"]
        os.environ.update(self.dbus_env)
        if features.x11:
            save_dbus_x11_properties(self.dbus_env)

    def init_dbus_server(self) -> None:
        log("init_dbus_server() env: %s", {k: v for k, v in os.environ.items() if k.startswith("DBUS_")})
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
        log(f"cleanup() dbus_server={ds}")
        if ds:
            self.dbus_server = None
            ds.cleanup()

    def late_cleanup(self, stop=True) -> None:
        if stop:
            self.stop_dbus_server()

    def stop_dbus_server(self) -> None:
        log("stop_dbus_server() dbus_pid=%s", self.dbus_pid)
        if not self.dbus_pid:
            return
        try:
            os.kill(self.dbus_pid, signal.SIGINT)
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

    def get_info(self, _proto) -> dict[str, Any]:
        if not self.dbus_pid or not self.dbus_env:
            return {}
        return {
            DbusServer.PREFIX: {
                "pid": self.dbus_pid,
                "env": self.dbus_env,
            }
        }
