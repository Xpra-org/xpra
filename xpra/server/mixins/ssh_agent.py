# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os

from xpra.util.io import is_socket
from xpra.util.objects import typedict
from xpra.common import SSH_AGENT_DISPATCH
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.net.ssh.agent import set_ssh_agent, setup_client_ssh_agent_socket, clean_agent_socket
from xpra.log import Logger

log = Logger("network", "ssh")


def accept_client_ssh_agent(uuid: str, ssh_auth_sock: str) -> None:
    sockpath = setup_client_ssh_agent_socket(uuid, ssh_auth_sock)
    if sockpath and os.path.exists(sockpath) and is_socket(sockpath):
        set_ssh_agent(uuid)


class SshAgent(StubServerMixin):
    """
    Mixin for setting up ssh agent forwarding,
    ensures that the symlinks point to the active client,
    and reverts back to the default when the client goes away.
    """
    PREFIX = "ssh-agent"

    def set_session_driver(self, source) -> None:
        if not SSH_AGENT_DISPATCH:
            return
        ssh_auth_sock = getattr(source, "ssh_auth_sock", "")
        set_ssh_agent(ssh_auth_sock)

    def cleanup_protocol(self, protocol) -> None:
        if not SSH_AGENT_DISPATCH:
            return
        source = self.get_server_source(protocol)
        if source and source.uuid:
            clean_agent_socket(source.uuid)
        remaining_sources = tuple(ss for ss in self._server_sources.values() if ss != source)
        for ss in remaining_sources:
            ssh_auth_sock = getattr(ss, "ssh_auth_sock", "")
            if ss.uuid and ssh_auth_sock:
                set_ssh_agent(ss.uuid)
                return
        set_ssh_agent("")

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        if not SSH_AGENT_DISPATCH:
            return
        assert ss
        if ss.uuid and send_ui:
            accept_client_ssh_agent(ss.uuid, c.strget("ssh-auth-sock"))
