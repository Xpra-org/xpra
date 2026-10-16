# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("menu")


class MenuConnection(StubClientConnection):
    """
    Tracks whether the client wants to receive application menu data.
    """
    PREFIX = "menu"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return caps.boolget("menu")

    def init_state(self) -> None:
        self.xdg_menu: bool = False
        self.menu: bool = False

    def parse_client_caps(self, c: typedict) -> None:
        self.menu = c.boolget("menu", False)

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"menu": self.menu}
        return info
