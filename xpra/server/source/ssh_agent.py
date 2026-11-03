# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict
from xpra.server.source.stub import StubClientConnection
from xpra.log import Logger

log = Logger("network", "ssh")


def get_ssh_agent_caps(caps: typedict) -> typedict:
    if agent_caps := caps.dictget("ssh-agent", None):
        return typedict(agent_caps)
    if BACKWARDS_COMPATIBLE and "ssh-agent" not in caps:
        return typedict({"socket": caps.strget("ssh-auth-sock")})
    return typedict()


class SSHAgentConnection(StubClientConnection):
    """
    Stores the SSH agent socket path and identity advertised by the client.
    """
    PREFIX = "ssh-agent"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return bool(get_ssh_agent_caps(caps).strget("socket"))

    def init_state(self) -> None:
        self.ssh_auth_sock: str = ""
        self.ssh_auth_sock_stat: tuple[int, ...] = ()

    def parse_client_caps(self, c: typedict) -> None:
        agent_caps = get_ssh_agent_caps(c)
        self.ssh_auth_sock = agent_caps.strget("socket")
        sockstat = (agent_caps.get("device"), agent_caps.get("inode"))
        if all(isinstance(v, int) for v in sockstat) and sockstat[0] >= 0 and sockstat[1] > 0:
            self.ssh_auth_sock_stat = sockstat
        else:
            self.ssh_auth_sock_stat = ()

    def get_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"socket": self.ssh_auth_sock}
        if self.ssh_auth_sock_stat:
            info.update(zip(("device", "inode"), self.ssh_auth_sock_stat))
        return {SSHAgentConnection.PREFIX: info}
