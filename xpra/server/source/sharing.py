# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("server", "auth")


class SharingConnection(StubClientConnection):
    """
    Tracks the client's sharing and lock preferences.
    """
    PREFIX = "sharing"

    def init_state(self) -> None:
        self.share: bool = False
        self.lock: bool = False

    def parse_client_caps(self, c: typedict) -> None:
        self.share = c.boolget("share")
        self.lock = c.boolget("lock")

    def get_info(self) -> dict[str, Any]:
        return {
            "lock": bool(self.lock),
            "share": bool(self.share),
        }
