# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.net.common import gsettings_key
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("server", "gsettings")


class GSettingsConnection(StubClientConnection):
    """
    Holds the GSettings values requested by this client,
    for the server's `gsettings` subsystem to apply.
    """

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return caps.boolget("gsettings")

    def init_state(self) -> None:
        # {(schema, key): gvariant_text}
        self.gsettings: dict[tuple[str, str], str] = {}

    def get_info(self) -> dict[str, Any]:
        if not self.gsettings:
            return {}
        return {
            "gsettings": {gsettings_key(schema, key): value for (schema, key), value in self.gsettings.items()},
        }
