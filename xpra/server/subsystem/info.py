# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import platform
import threading
from time import time, monotonic
from typing import Any
from collections.abc import Callable, Sequence

from xpra.util.version import (
    XPRA_VERSION, version_str, get_version_info,
    get_build_info, get_host_info, parse_version,
)
from xpra.net.common import is_request_allowed, Packet
from xpra.net.net_util import get_info as get_net_info
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.server.subsystem.stub import StubServerMixin
from xpra.common import FULL_INFO, ConnectionMessage
from xpra.os_util import get_machine_id, POSIX, gi_import
from xpra.util.child_reaper import get_child_reaper
from xpra.util.system import get_env_info, get_sysconfig_info
from xpra.util.thread import start_thread
from xpra.util.pysystem import get_frame_info
from xpra.util.objects import typedict, notypedict, merge_dicts
from xpra.util.env import envbool
from xpra.log import Logger, get_info as get_log_info

# pylint: disable=import-outside-toplevel

GLib = gi_import("GLib")

log = Logger("server")

main_thread = threading.current_thread()

SYSCONFIG = envbool("XPRA_SYSCONFIG", FULL_INFO > 1)
SHOW_NETWORK_ADDRESSES = envbool("XPRA_SHOW_NETWORK_ADDRESSES", True)


def get_server_load_info() -> dict[str, Any]:
    if POSIX:
        try:
            return {"load": tuple(int(x * 1000) for x in os.getloadavg())}
        except OSError:
            log("cannot get load average", exc_info=True)
    return {}


def get_server_exec_info() -> dict[str, Any]:
    info: dict[str, Sequence[str] | str | int | dict] = {
        "argv": sys.argv,
        "path": sys.path,
        "exec_prefix": sys.exec_prefix,
        "executable": sys.executable,
        "pid": os.getpid(),
    }
    logfile = os.environ.get("XPRA_SERVER_LOG", "")
    if logfile:
        info["log-file"] = logfile
    return info


def get_thread_info(proto=None) -> dict[Any, Any]:
    # threads:
    if proto:
        info_threads = proto.get_threads()
    else:
        info_threads = ()
    return get_frame_info(info_threads)


# noinspection PyMethodMayBeStatic
class InfoServer(StubServerMixin):
    """
    Servers that expose info data via info request.
    """

    def __init__(self):
        self.hello_request_handlers["info"] = self._handle_hello_request_info
        self.session_name = ""

    def _handle_hello_request_info(self, proto, _caps: typedict) -> bool:
        self.send_hello_info(proto)
        return True

    def send_version_info(self, proto: SocketProtocol, full: bool = False) -> None:
        version = version_str() if (full and FULL_INFO) else XPRA_VERSION.split(".", 1)[0]
        proto.send_now(Packet("hello", {"version": version}))
        # client is meant to close the connection itself, but just in case:
        GLib.timeout_add(5 * 1000, self.send_disconnect, proto, ConnectionMessage.DONE, "version sent")

    ######################################################################
    # info:
    def send_hello_info(self, proto: SocketProtocol) -> None:
        # Note: this can be overridden in subclasses to pass arguments to get_ui_info()
        # (ie: see server_base)
        if not is_request_allowed(proto, "info"):
            self.do_send_info(proto, {"error": "`info` requests are not enabled for this connection"})
            return

        def cb(proto, info) -> None:
            self.do_send_info(proto, info)

        self.get_all_info(cb, proto)

    def do_send_info(self, proto: SocketProtocol, info: dict[str, Any]) -> None:
        proto.send_now(Packet("hello", notypedict(info)))

    def get_all_info(self, callback: Callable, proto: SocketProtocol | None = None, *args) -> None:
        start = monotonic()
        ui_info: dict[str, Any] = self.get_ui_info(proto, *args)
        end = monotonic()
        log("get_all_info: ui info collected in %ims", (end - start) * 1000)
        start_thread(self._get_info_in_thread, "Info", daemon=True, args=(callback, ui_info, proto, args))

    def _get_info_in_thread(self, callback: Callable, ui_info: dict[str, Any], proto: SocketProtocol, args):
        log("get_info_in_thread%s", (callback, {}, proto, args))
        start = monotonic()
        # this runs in a non-UI thread
        with log.trap_error("Error during info collection"):
            info = self.get_info(proto, *args)
            merge_dicts(ui_info, info)
        end = monotonic()
        log("get_all_info: non ui info collected in %ims", (end - start) * 1000)
        callback(proto, ui_info)

    def get_info(self, proto) -> dict[str, Any]:
        authenticated = bool(proto and proto.authenticators)
        full = FULL_INFO > 0 or authenticated
        info = self.get_server_info(full)
        if full:
            info["threads"] = get_thread_info(proto)
        if self.session_name:
            info["session"] = {"name": self.session_name}
        return info

    def get_ui_info(self, _proto: SocketProtocol, *_args) -> dict[str, Any]:
        # this function is for info which MUST be collected from the UI thread
        return {}

    def get_server_info(self, full=False) -> dict[str, Any]:
        if full:
            info = self.get_full_server_info()
        else:
            info = self.get_minimal_server_info()
        info.update(get_host_info(full))
        return info

    def get_minimal_server_info(self) -> dict[str, Any]:
        return {
            "session-type": self.session_type,
            "uuid": self.uuid,
            "machine-id": get_machine_id(),
        }

    def get_full_server_info(self) -> dict[str, Any]:
        info = self.get_base_server_info()
        info.update(get_server_load_info())
        info.update(get_server_exec_info())
        if SYSCONFIG:
            info["sysconfig"] = get_sysconfig_info()
        ni = get_net_info()
        ni |= {
            "sockets": self.get_socket_info(),
            # "packet-handlers": GLibPacketHandler.get_info(self),
            "www": {
                "": self._html,
                "websocket-upgrade": self.websocket_upgrade,
                "dir": self._www_dir or "",
                "http-headers-dirs": self._http_headers_dirs or "",
            },
        }
        info["network"] = ni
        info["logging"] = get_log_info()
        from xpra.platform.info import get_sys_info
        info["sys"] = get_sys_info()
        info["env"] = get_env_info()
        info.update(get_child_reaper().get_info())
        return info

    def get_base_server_info(self) -> dict[str, Any]:
        # this function is for non UI thread info
        now = time()
        info = {
            "type": "Python",
            "python": {"version": parse_version(platform.python_version())[:FULL_INFO + 1]},
            "start_time": int(self.start_time),
            "current_time": int(now),
            "elapsed_time": int(now - self.start_time),
            "build": self.get_build_info(),
        }
        return info

    def get_build_info(self) -> dict[str, Any]:
        # this function is for non UI thread info
        info = get_version_info()
        if FULL_INFO >= 1:
            info.update(get_build_info())
        return info

    def get_packet_handlers_info(self) -> dict[str, Any]:
        return {
            "default": sorted(self._default_packet_handlers.keys()),
        }

    def get_socket_info(self) -> dict[str, Any]:
        return {}
