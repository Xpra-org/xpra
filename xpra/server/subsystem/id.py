# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from typing import Any

from xpra.net.common import Packet, FULL_INFO
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.server.subsystem.stub import StubSubsystem
from xpra.os_util import get_hex_uuid, get_machine_id
from xpra.scripts.session import load_session_file
from xpra.util.version import XPRA_NUMERIC_VERSION
from xpra.util.objects import typedict
from xpra.log import Logger

# pylint: disable=import-outside-toplevel

log = Logger("server")

SERVER_UUID_FILE = "server.uuid"


# noinspection PyMethodMayBeStatic
class IDServer(StubSubsystem):
    """
    Servers that expose info data via info request.
    """
    PREFIX = "id"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.server.hello_request_handlers["id"] = self._handle_hello_request_id
        self.uuid = ""

    def setup(self) -> None:
        if not self.uuid:
            file_uuid = ""
            if os.environ.get("XPRA_SESSION_DIR"):
                file_uuid = load_session_file(SERVER_UUID_FILE).decode("latin1").strip()
            self.uuid = os.environ.get("XPRA_PROXY_START_UUID", "") or file_uuid or get_hex_uuid()
            if session_files := self.get_subsystem("session-files"):
                session_files.write_session_file(SERVER_UUID_FILE, self.uuid)
        log(f"server uuid is {self.uuid}")

    def get_caps(self, source):
        caps = {}
        if source is None or "versions" in source.wants:
            caps["uuid"] = self.uuid
            mid = get_machine_id()
            if mid:
                caps["machine_id"] = mid
        return caps

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
        }

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
            "session-type": self.server.session_type,
            "session-name": self.server.session_name,
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
