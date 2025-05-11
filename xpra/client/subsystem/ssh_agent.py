# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os.path
from typing import Any

from xpra.client.base.stub import StubClientMixin


class SSHAgentClient(StubClientMixin):
    """
    Exposes ssh agent capability
    """

    def get_caps(self) -> dict[str, Any]:
        ssh_auth_sock = os.environ.get("SSH_AUTH_SOCK", "")
        caps: dict[str, Any] = {}
        if ssh_auth_sock and os.path.isabs(ssh_auth_sock):
            # ensure agent forwarding is actually requested?
            # (checking the socket type is not enough:
            # one could still bind mount the path and connect via tcp! why though?)
            # meh: if the transport doesn't have agent forwarding enabled,
            # then it won't create a server-side socket
            # and nothing will happen,
            # exposing this client-side path is no big deal
            caps["ssh-auth-sock"] = ssh_auth_sock
        return caps
