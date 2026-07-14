# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os

from xpra.server.common import get_sources_by_type, SSH_AGENT_DISPATCH
from xpra.util.io import is_socket
from xpra.util.objects import typedict
from xpra.util.parsing import FALSE_OPTIONS
from xpra.server.subsystem.stub import StubServerMixin
from xpra.server.source.ssh_agent import SSHAgentConnection
from xpra.net.ssh.agent import setup_ssh_auth_sock, set_ssh_agent, setup_client_ssh_agent_socket, clean_agent_socket
from xpra.log import Logger

log = Logger("network", "ssh")


def accept_client_ssh_agent(uuid: str, ssh_auth_sock: str) -> None:
    sockpath = setup_client_ssh_agent_socket(uuid, ssh_auth_sock)
    if sockpath and os.path.exists(sockpath) and is_socket(sockpath):
        set_ssh_agent(uuid)


SSH_AUTH_SOCK = "SSH_AUTH_SOCK"


class SshAgent(StubServerMixin):
    """
    Mixin for setting up ssh agent forwarding,
    ensures that the symlinks point to the active client,
    and reverts back to the default when the client goes away.
    """
    PREFIX = "ssh-agent"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.ssh_agent = False
        self.session_files: list[str] = []

    def init(self, opts) -> None:
        self.ssh_agent = SSH_AGENT_DISPATCH and opts.ssh.lower() not in FALSE_OPTIONS
        session_dir = os.environ.get("XPRA_SESSION_DIR", "")
        if not session_dir:
            log.warn(f"Warning: unable to configure {SSH_AUTH_SOCK} without a valid session directory")
            return
        if self.ssh_agent:
            self.session_files.append("ssh/agent")
            self.session_files.append("ssh/agent.default")
            # glob that matches agent uuid symlinks:
            self.session_files.append("ssh/????????????????????????????????????????????????????????????????")
            self.session_files.append("ssh")
            try:
                ssh_auth_sock = setup_ssh_auth_sock(session_dir)
            except OSError:
                log.error(f"Error setting up ssh agent forwarding to {session_dir!r}", exc_info=True)
            else:
                cur = os.environ.get(SSH_AUTH_SOCK, "")
                log(f"updating SSH_AUTH_SOCK from {cur!r} to {ssh_auth_sock!r}")
                os.environ[SSH_AUTH_SOCK] = ssh_auth_sock

    def setup(self) -> None:
        self.connect("new-ui-driver", self.set_agent)

    def get_agent_uuid(self, exclude=None) -> str:
        # the client driving the session gets to provide the agent,
        # failing that, any client that has one:
        agent = ""
        for ss in get_sources_by_type(self, SSHAgentConnection, exclude=exclude):
            if not ss.uuid or not ss.ssh_auth_sock:
                continue
            if ss.uuid == self.ui_driver:
                return ss.uuid
            agent = agent or ss.uuid
        return agent

    def set_agent(self, server, source) -> None:
        log("set_agent(%s, %s) ssh-agent=%s", server, source, self.ssh_agent)
        if not self.ssh_agent:
            return
        self.update_agent_symlinks(self.get_agent_uuid())

    def may_update_agent_symlinks(self, source) -> None:
        # called from `ServerBase.cleanup_protocol`: the generic `cleanup_protocol` mixin
        # hook fires after the source has been removed, too late to look up its uuid
        if not self.ssh_agent:
            return
        self.update_agent_symlinks(self.get_agent_uuid(exclude=source), remove=source.uuid)

    @staticmethod
    def update_agent_symlinks(uuid: str, remove: str = "") -> None:
        # `uuid` is always a client uuid or an empty string for the default agent:
        # never a raw `ssh_auth_sock` path, so that `agent` keeps pointing
        # at the `ssh/$UUID` symlink validated by `accept_client_ssh_agent`
        if remove:
            clean_agent_socket(remove)
        set_ssh_agent(uuid)

    def add_new_client(self, ss, _c: typedict) -> None:
        if not self.ssh_agent:
            return
        assert ss
        if ss.uuid:
            accept_client_ssh_agent(ss.uuid, getattr(ss, "ssh_auth_sock", ""))
