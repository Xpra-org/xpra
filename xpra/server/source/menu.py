# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.net.common import BACKWARDS_COMPATIBLE
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
        return caps.boolget("menu") or (BACKWARDS_COMPATIBLE and caps.boolget("xdg-menu"))

    def init_state(self) -> None:
        self.xdg_menu: bool = False
        self.menu: bool = False

    def parse_client_caps(self, c: typedict) -> None:
        if BACKWARDS_COMPATIBLE:
            self.xdg_menu = c.boolget("xdg-menu", False)
        self.menu = c.boolget("menu", False)

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"menu": bool(self.menu)}
        if BACKWARDS_COMPATIBLE:
            info["xdg-menu"] = bool(self.xdg_menu)
        return info
