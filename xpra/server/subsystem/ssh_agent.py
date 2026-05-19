# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os

from xpra.server.common import SSH_AGENT_DISPATCH
from xpra.util.io import is_socket
from xpra.util.objects import typedict
from xpra.util.parsing import FALSE_OPTIONS
from xpra.server.subsystem.stub import StubServerMixin
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

    def __init__(self, server=None):
        StubServerMixin.__init__(self, server)
        self.enabled = False

    def init(self, opts) -> None:
        self.enabled = SSH_AGENT_DISPATCH and opts.ssh.lower() not in FALSE_OPTIONS
        session_dir = os.environ.get("XPRA_SESSION_DIR", "")
        if not session_dir:
            log.warn(f"Warning: unable to configure {SSH_AUTH_SOCK} without a valid session directory")
            return
        if self.enabled:
            if sf := self.get_subsystem("session-files"):
                sf.session_files.extend((
                    "ssh/agent",
                    "ssh/agent.default",
                    # glob that matches agent uuid symlinks:
                    "ssh/????????????????????????????????????????????????????????????????",
                    "ssh",
                ))
            try:
                ssh_auth_sock = setup_ssh_auth_sock(session_dir)
            except OSError:
                log.error(f"Error setting up ssh agent forwarding to {session_dir!r}", exc_info=True)
            else:
                cur = os.environ.get(SSH_AUTH_SOCK, "")
                log(f"updating SSH_AUTH_SOCK from {cur!r} to {ssh_auth_sock!r}")
                os.environ[SSH_AUTH_SOCK] = ssh_auth_sock

    def setup(self) -> None:
        self.server.connect("new-ui-driver", self.set_agent)

    def set_agent(self, server, source) -> None:
        log("set_agent(%s, %s) ssh-agent=%s", server, source, self.enabled)
        if not self.enabled:
            return
        ssh_auth_sock = getattr(source, "ssh_auth_sock", "")
        set_ssh_agent(ssh_auth_sock)

    def cleanup_protocol(self, protocol) -> None:
        if not self.enabled:
            return
        source = self.get_server_source(protocol)
        if source and source.uuid:
            clean_agent_socket(source.uuid)
        remaining_sources = self.get_sources_by_type(exclude=source)
        for ss in remaining_sources:
            ssh_auth_sock = getattr(ss, "ssh_auth_sock", "")
            if ss.uuid and ssh_auth_sock:
                set_ssh_agent(ss.uuid)
                return
        set_ssh_agent("")

    def add_new_client(self, ss, _c: typedict) -> None:
        if not self.enabled:
            return
        assert ss
        if ss.uuid:
            accept_client_ssh_agent(ss.uuid, getattr(ss, "ssh_auth_sock", ""))
