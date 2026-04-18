# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
from collections.abc import Sequence
from typing import Any

from xpra.util.objects import typedict
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("command")


class ControlConnection(StubClientConnection):

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return bool(caps.strtupleget("control_commands"))

    def init_state(self) -> None:
        self.client_control_commands: Sequence[str] = ()

    def cleanup(self) -> None:
        self.client_control_commands = ()

    def parse_client_caps(self, c: typedict) -> None:
        self.client_control_commands = c.strtupleget("control_commands")

    def get_info(self) -> dict[str, Any]:
        return {
            "control-commands": self.client_control_commands,
        }
