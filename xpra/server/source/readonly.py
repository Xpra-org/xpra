# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.util.parsing import str_to_bool
from xpra.server.source.stub import StubClientConnection


class ReadonlyConnection(StubClientConnection):
    """
    Tracks readonly policy for a single authenticated client connection.
    """

    def init_from(self, protocol, server) -> None:
        self.server = server
        self.client_readonly = False
        self.control_readonly = False
        conn = getattr(protocol, "_conn", None)
        options = getattr(conn, "options", None) or {}
        self.connection_readonly = bool(str_to_bool(options.get("readonly", False)))

    def parse_client_caps(self, c: typedict) -> None:
        self.client_readonly = c.boolget("readonly", self.client_readonly)
        window = typedict(c.dictget("window", {}))
        if window:
            self.client_readonly = window.boolget("read-only", self.client_readonly)

    def effective_readonly(self) -> bool:
        return bool(getattr(self.server, "readonly", False) or self.connection_readonly or self.control_readonly or self.client_readonly)

    def server_enforced_readonly(self) -> bool:
        return bool(getattr(self.server, "readonly", False) or self.connection_readonly or self.control_readonly)

    def set_client_readonly(self, readonly: bool) -> None:
        self.client_readonly = bool(readonly)

    def set_control_readonly(self, readonly: bool) -> None:
        self.control_readonly = bool(readonly)

    def get_caps(self) -> dict[str, Any]:
        return {
            "readonly": self.server_enforced_readonly(),
        }

    def get_info(self) -> dict[str, Any]:
        return {
            "readonly": {
                "effective": self.effective_readonly(),
                "client": self.client_readonly,
                "connection": self.connection_readonly,
                "control": self.control_readonly,
                "server": bool(getattr(self.server, "readonly", False)),
            },
        }
