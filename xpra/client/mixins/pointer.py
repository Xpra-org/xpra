# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.log import Logger

log = Logger("mouse")

MOUSE_DELAY_AUTO = envbool("XPRA_MOUSE_DELAY_AUTO", True)


class PointerClient(StubClientMixin):
    """
    Utility mixin for clients that handle pointer input
    """
    PREFIX = "mouse"

    def __init__(self):
        self._mouse_position_delay = 5
        self.server_pointer = True

    def init_ui(self, opts) -> None:
        if MOUSE_DELAY_AUTO:
            try:
                # some platforms don't detect the vrefresh correctly
                # (ie: macos in virtualbox?), so use a sane default minimum
                # discount by 5ms to ensure we have time to hit the target
                v = max(60, self.get_vrefresh())
                self._mouse_position_delay = max(5, 1000 // v // 2 - 5)
                log(f"mouse position delay: {self._mouse_position_delay}")
            except (AttributeError, OSError):
                log("failed to calculate automatic delay", exc_info=True)

    def get_info(self) -> dict[str, dict[str, Any]]:
        return {PointerClient.PREFIX: {}}

    def get_caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "mouse": True,
        }
        return {PointerClient.PREFIX: caps}

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_pointer = c.boolget("pointer", True)
        return True
