# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any

from xpra.net.common import Packet
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.server.subsystem.stub import StubServerMixin
from xpra.common import FULL_INFO
from xpra.os_util import get_machine_id, gi_import, get_user_uuid
from xpra.util.version import XPRA_NUMERIC_VERSION
from xpra.util.objects import typedict
from xpra.log import Logger

# pylint: disable=import-outside-toplevel

GLib = gi_import("GLib")

log = Logger("server")


# noinspection PyMethodMayBeStatic
class IDServer(StubServerMixin):
    """
    Servers that expose info data via info request.
    """

    def __init__(self):
        self.hello_request_handlers["id"] = self._handle_hello_request_id
        self.uuid = ""

    def get_caps(self, source):
        caps = {}
        if source is None or "versions" in source.wants:
            caps["uuid"] = get_user_uuid()
            mid = get_machine_id()
            if mid:
                caps["machine_id"] = mid
        return caps

    def _handle_hello_request_id(self, proto, _caps: typedict) -> bool:
        self.send_id_info(proto)
        return True

    def send_id_info(self, proto: SocketProtocol) -> None:
        log("id info request from %s", proto._conn)
        proto._log_stats = False
        proto.send_now(Packet("hello", self.get_session_id_info()))

    def get_session_id_info(self) -> dict[str, Any]:
        # minimal information for identifying the session
        id_info = {
            "session-type": self.session_type,
            "session-name": self.session_name,
            "uuid": self.uuid,
            "platform": sys.platform,
            "pid": os.getpid(),
            "machine-id": get_machine_id(),
            "version": XPRA_NUMERIC_VERSION[:FULL_INFO+1],
        }
        display = os.environ.get("DISPLAY", "")
        if display:
            id_info["display"] = display
        return id_info
