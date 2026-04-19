# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("network", "ssh")


class SSHAgentConnection(StubClientConnection):
    """
    Stores the SSH agent socket path advertised by the client.
    """
    PREFIX = "ssh-agent"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return bool(caps.strget("ssh-auth-sock"))

    def init_state(self) -> None:
        self.ssh_auth_sock: str = ""

    def parse_client_caps(self, c: typedict) -> None:
        self.ssh_auth_sock = c.strget("ssh-auth-sock")

    def get_info(self) -> dict[str, Any]:
        return {"ssh-auth-sock": self.ssh_auth_sock}
