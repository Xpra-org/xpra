# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os

from xpra.os_util import gi_import
from xpra.server.common import SSH_AGENT_DISPATCH
from xpra.util.io import is_socket
from xpra.util.objects import typedict
from xpra.util.parsing import FALSE_OPTIONS
from xpra.server.source.ssh_agent import SSHAgentConnection
from xpra.server.subsystem.stub import StubSubsystem
from xpra.net.ssh.agent import setup_ssh_auth_sock, set_ssh_agent, setup_client_ssh_agent_socket, clean_agent_socket
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("network", "ssh")


def accept_client_ssh_agent(uuid: str, ssh_auth_sock: str) -> None:
    sockpath = setup_client_ssh_agent_socket(uuid, ssh_auth_sock)
    if sockpath and os.path.exists(sockpath) and is_socket(sockpath):
        set_ssh_agent(uuid)


SSH_AUTH_SOCK = "SSH_AUTH_SOCK"


class SshAgent(StubSubsystem):
    """
    Mixin for setting up ssh agent forwarding,
    ensures that the symlinks point to the active client,
    and reverts back to the default when the client goes away.
    """
    PREFIX = "ssh-agent"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
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
        self.update_agent_symlinks(ssh_auth_sock)

    def may_update_agent_symlinks(self, source) -> None:
        # called by the `client-session` subsystem: the generic `cleanup_protocol` hook
        # fires after the source has been removed, too late to look up its uuid
        if not self.enabled:
            return
        # revert to the agent of whichever client is left, or back to the default:
        agent = ""
        for ss in self.get_sources_by_type(SSHAgentConnection, exclude=source):
            if ss.uuid and ss.ssh_auth_sock:
                agent = ss.uuid
                break
        self.update_agent_symlinks(agent, remove=source.uuid)

    def update_agent_symlinks(self, agent: str, remove: str = "") -> None:
        # both callers above can fire from the disconnect path
        # (`may_update_agent_symlinks`, and `new-ui-driver` re-emitted when the ui driver goes away),
        # which the server runs inline on the network parse thread - where the seccomp filter
        # denies `unlink` and `symlink`. See `docs/Usage/Seccomp.md`.
        # Retargeting the agent symlink is never urgent, so always do it from the main thread:
        def update() -> None:
            if remove:
                clean_agent_socket(remove)
            set_ssh_agent(agent)

        GLib.idle_add(update)

    def add_new_client(self, ss, _c: typedict) -> None:
        if not self.enabled:
            return
        assert ss
        if ss.uuid:
            accept_client_ssh_agent(ss.uuid, getattr(ss, "ssh_auth_sock", ""))
