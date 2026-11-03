# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
from typing import Any

from xpra.client.base.stub import StubClientSubsystem
from xpra.net.common import BACKWARDS_COMPATIBLE


class SSHAgentClient(StubClientSubsystem):
    """
    Exposes ssh agent capability
    """
    __slots__ = ()
    PREFIX = "ssh-agent"

    def get_caps(self) -> dict[str, Any]:
        ssh_auth_sock = os.environ.get("SSH_AUTH_SOCK", "")
        if not ssh_auth_sock or not os.path.isabs(ssh_auth_sock):
            return {}
        agent_caps: dict[str, Any] = {"socket": ssh_auth_sock}
        try:
            sockstat = os.stat(ssh_auth_sock)
        except (OSError, ValueError):
            pass
        else:
            device = getattr(sockstat, "st_dev", None)
            inode = getattr(sockstat, "st_ino", None)
            if isinstance(device, int) and device >= 0 and isinstance(inode, int) and inode > 0:
                # Allows the server to reject accidental matches to another
                # machine's socket at the same path. This is not authentication.
                agent_caps.update({"device": device, "inode": inode})
        caps: dict[str, Any] = {SSHAgentClient.PREFIX: agent_caps}
        if BACKWARDS_COMPATIBLE:
            caps["ssh-auth-sock"] = ssh_auth_sock
        return caps
