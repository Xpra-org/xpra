# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.subsystem.stub import StubServerMixin
from xpra.common import FULL_INFO, ConnectionMessage, BACKWARDS_COMPATIBLE
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.net.common import Packet
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.version import XPRA_VERSION, vparts


class VersionServer(StubServerMixin):
    """
    Servers that expose version data via hello requests.
    """
    PREFIX = "version"

    def __init__(self):
        self.hello_request_handlers["version"] = self._handle_hello_request_version

    def get_caps(self, source) -> dict[str, Any]:
        caps = {
            VersionServer.PREFIX: vparts(XPRA_VERSION, FULL_INFO + 1),
        }
        if source is None or "versions" in source.wants:
            caps |= self.get_minimal_server_info()
        return caps

    def get_info(self, proto) -> dict[str, Any]:
        return {
            VersionServer.PREFIX: vparts(XPRA_VERSION, FULL_INFO + 1),
        }

    def _handle_hello_request_version(self, proto, caps: typedict) -> bool:
        self.send_version_info(proto, (not BACKWARDS_COMPATIBLE) or caps.boolget("full-version-request", True))
        return True

    def send_version_info(self, proto: SocketProtocol, full: bool = False) -> None:
        from xpra.util.version import XPRA_VERSION, version_str
        version = version_str() if (full and FULL_INFO) else XPRA_VERSION.split(".", 1)[0]
        proto.send_now(Packet("hello", {"version": version}))
        # client is meant to close the connection itself, but just in case:
        GLib = gi_import("GLib")
        GLib.timeout_add(5 * 1000, self.send_disconnect, proto, ConnectionMessage.DONE, "version sent")
