# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("server")


class ClientIDConnection(StubClientConnection):
    """
    Every client should provide these
    """

    def cleanup(self) -> None:
        self.init_state()

    def init_state(self) -> None:
        self.uuid = ""
        self.session_id = ""

    def parse_client_caps(self, c: typedict) -> None:
        self.uuid = c.strget("uuid")
        self.session_id = c.strget("session-id")
        log(f"client uuid {self.uuid!r}")

    def get_info(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "session-id": self.session_id,
        }
