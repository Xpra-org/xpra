#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import socket
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.client.subsystem.ssh_agent import SSHAgentClient
from xpra.net.ssh.agent import get_ssh_agent_path, setup_ssh_auth_sock
from xpra.server.source.ssh_agent import SSHAgentConnection
from xpra.server.subsystem.ssh_agent import SshAgent
from xpra.util.objects import typedict


@unittest.skipUnless(os.name == "posix", "Unix agent sockets require POSIX")
class SSHAgentTest(unittest.TestCase):

    def setUp(self):
        tempdir = tempfile.TemporaryDirectory(prefix="xpra-agent-test-")
        self.addCleanup(tempdir.cleanup)
        self.session_dir = tempdir.name
        env = patch.dict(os.environ, {"XPRA_SESSION_DIR": self.session_dir, "SSH_AUTH_SOCK": ""})
        env.start()
        self.addCleanup(env.stop)
        self.sources = []
        self.pending = []
        self.server = SimpleNamespace(
            ui_driver=None,
            idle_add=lambda fn: self.pending.append(fn),
            timeout_add=lambda *args: None,
            source_remove=lambda *args: None,
            get_sources_by_type=lambda cls=object, exclude=None: tuple(
                ss for ss in self.sources if isinstance(ss, cls) and (exclude is None or ss.uuid != exclude.uuid)
            ),
        )
        self.agent = SshAgent(self.server)
        self.agent.enabled = True
        self.default = self.make_socket("default")
        os.environ["SSH_AUTH_SOCK"] = self.default
        self.active = setup_ssh_auth_sock(self.session_dir)

    def make_socket(self, name):
        path = os.path.join(self.session_dir, name)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        sock.bind(path)
        sock.listen(1)
        return path

    def add_source(self, name, forwarded=False, advertise=True):
        uuid = name * 64
        if advertise:
            ss = SSHAgentConnection()
            ss.init_state()
            ss.parse_client_caps(typedict({"ssh-agent": {"socket": os.path.join(self.session_dir, f"client-{name}")}}))
            ss.uuid = uuid
        else:
            # Windows clients can forward an agent without advertising SSH_AUTH_SOCK.
            ss = SimpleNamespace(uuid=uuid)
        if forwarded:
            os.symlink(self.make_socket(f"forwarded-{name}"), get_ssh_agent_path(uuid))
        self.sources.append(ss)
        return ss

    def run_pending(self):
        while self.pending:
            self.pending.pop(0)()

    def advertise_local_agent(self, source, path):
        with patch.dict(os.environ, {"SSH_AUTH_SOCK": path}):
            caps = SSHAgentClient(self.server).get_caps()
        source.parse_client_caps(typedict(caps))

    def test_matching_local_agent_is_registered(self):
        source = self.add_source("a")
        path = self.make_socket("local-agent")
        self.advertise_local_agent(source, path)
        self.agent.add_new_client(source, typedict())
        self.assertTrue(os.path.samefile(self.active, path))
        self.assertEqual(self.agent.get_agent_uuid(), source.uuid)

    def test_mismatched_or_missing_identity_does_not_reuse_path(self):
        source = self.add_source("a")
        path = self.make_socket("local-agent")
        sockstat = os.stat(path)
        for identity in ((), (sockstat.st_dev+1, sockstat.st_ino), (sockstat.st_dev, sockstat.st_ino+1)):
            with self.subTest(identity=identity):
                agent_caps = {"socket": path}
                if identity:
                    agent_caps.update(zip(("device", "inode"), identity))
                source.parse_client_caps(typedict({"ssh-agent": agent_caps}))
                self.agent.add_new_client(source, typedict())
                self.assertFalse(os.path.lexists(get_ssh_agent_path(source.uuid)))
                self.assertTrue(os.path.samefile(self.active, self.default))

    def test_socket_owner_must_match_server_effective_uid(self):
        source = self.add_source("a")
        path = self.make_socket("local-agent")
        self.advertise_local_agent(source, path)
        with patch("xpra.net.ssh.agent.os.geteuid", return_value=os.geteuid()+1):
            self.agent.add_new_client(source, typedict())
        self.assertFalse(os.path.lexists(get_ssh_agent_path(source.uuid)))
        self.assertTrue(os.path.samefile(self.active, self.default))

    def test_identity_follows_socket_symlinks(self):
        source = self.add_source("a")
        path = self.make_socket("local-agent")
        symlink = os.path.join(self.session_dir, "client-agent")
        os.symlink(path, symlink)
        self.advertise_local_agent(source, symlink)
        sockstat = os.stat(path)
        self.assertEqual(source.ssh_auth_sock_stat, (sockstat.st_dev, sockstat.st_ino))
        self.agent.add_new_client(source, typedict())
        self.assertTrue(os.path.samefile(self.active, path))

    def test_matching_regular_file_is_rejected(self):
        source = self.add_source("a")
        path = os.path.join(self.session_dir, "regular-file")
        with open(path, "w", encoding="utf8"):
            pass
        self.advertise_local_agent(source, path)
        self.agent.add_new_client(source, typedict())
        self.assertFalse(os.path.lexists(get_ssh_agent_path(source.uuid)))
        self.assertTrue(os.path.samefile(self.active, self.default))

    def test_existing_forwarded_socket_does_not_require_matching_identity(self):
        source = self.add_source("a", forwarded=True)
        self.advertise_local_agent(source, self.default)
        source.ssh_auth_sock_stat = (source.ssh_auth_sock_stat[0], source.ssh_auth_sock_stat[1]+1)
        self.agent.add_new_client(source, typedict())
        self.assertTrue(os.path.samefile(self.active, get_ssh_agent_path(source.uuid)))

    def test_unusable_ui_driver_does_not_mask_forwarded_agent(self):
        forwarded = self.add_source("a", forwarded=True)
        remote = self.add_source("b")
        self.server.ui_driver = remote.uuid
        self.assertEqual(self.agent.get_agent_uuid(), forwarded.uuid)

    def test_selection_checks_registered_socket(self):
        remote = self.add_source("a")
        path = get_ssh_agent_path(remote.uuid)
        for kind in ("missing", "file", "directory", "dangling-symlink"):
            with self.subTest(kind=kind):
                if kind == "file":
                    with open(path, "w", encoding="utf8"):
                        pass
                elif kind == "directory":
                    os.mkdir(path)
                elif kind == "dangling-symlink":
                    os.symlink(remote.ssh_auth_sock, path)
                try:
                    self.assertEqual(self.agent.get_agent_uuid(), "")
                finally:
                    if kind == "directory":
                        os.rmdir(path)
                    elif os.path.lexists(path):
                        os.unlink(path)

    def test_forwarded_agent_with_no_advertised_path(self):
        forwarded = self.add_source("a", forwarded=True, advertise=False)
        self.assertEqual(self.agent.get_agent_uuid(), forwarded.uuid)

    def test_usable_ui_driver_is_preferred(self):
        self.add_source("a", forwarded=True)
        driver = self.add_source("b", forwarded=True)
        self.server.ui_driver = driver.uuid
        self.assertEqual(self.agent.get_agent_uuid(), driver.uuid)

    def test_disconnect_restores_default_with_unusable_client_remaining(self):
        forwarded = self.add_source("a", forwarded=True)
        self.agent.add_new_client(forwarded, typedict())
        remote = self.add_source("b")
        self.server.ui_driver = remote.uuid
        self.sources.remove(forwarded)
        self.agent.may_update_agent_symlinks(forwarded)
        self.run_pending()
        self.assertTrue(os.path.samefile(self.active, self.default))
        self.assertFalse(os.path.lexists(get_ssh_agent_path(forwarded.uuid)))

    def test_disconnect_selects_another_usable_client(self):
        departing = self.add_source("a", forwarded=True)
        self.agent.add_new_client(departing, typedict())
        remaining = self.add_source("b", forwarded=True)
        remote = self.add_source("c")
        self.server.ui_driver = remote.uuid
        self.sources.remove(departing)
        self.agent.may_update_agent_symlinks(departing)
        self.run_pending()
        self.assertTrue(os.path.samefile(self.active, get_ssh_agent_path(remaining.uuid)))

    def test_selection_is_rechecked_when_idle_callback_runs(self):
        forwarded = self.add_source("a", forwarded=True)
        self.agent.add_new_client(forwarded, typedict())
        self.agent.set_agent(self.server, forwarded)
        # The forwarded socket can disappear while the symlink update is queued.
        os.unlink(get_ssh_agent_path(forwarded.uuid))
        self.run_pending()
        self.assertTrue(os.path.samefile(self.active, self.default))


class SSHAgentCapsTest(unittest.TestCase):

    def setUp(self):
        self.source = SSHAgentConnection()
        self.source.init_state()

    def test_socket_identity_is_parsed_and_reported(self):
        caps = typedict({"ssh-agent": {"socket": "/agent", "device": 0, "inode": 2**64-1}})
        for compatible in (True, False):
            with self.subTest(compatible=compatible), patch("xpra.server.source.ssh_agent.BACKWARDS_COMPATIBLE", compatible):
                self.assertTrue(SSHAgentConnection.is_needed(caps))
                self.source.parse_client_caps(caps)
                self.assertEqual(self.source.ssh_auth_sock, "/agent")
                self.assertEqual(self.source.ssh_auth_sock_stat, (0, 2**64-1))
                self.assertEqual(self.source.get_info(), caps)

    def test_legacy_path_requires_compatibility_mode(self):
        # The temporary top-level metadata format is never read, even in compatibility mode.
        caps = typedict({"ssh-auth-sock": "/legacy-agent", "ssh-auth-sock-stat": (1, 2)})
        for compatible in (True, False):
            with self.subTest(compatible=compatible), patch("xpra.server.source.ssh_agent.BACKWARDS_COMPATIBLE", compatible):
                self.assertEqual(SSHAgentConnection.is_needed(caps), compatible)
                self.source.parse_client_caps(caps)
                self.assertEqual(self.source.ssh_auth_sock, "/legacy-agent" if compatible else "")
                self.assertEqual(self.source.ssh_auth_sock_stat, ())

    def test_modern_dictionary_takes_precedence(self):
        for agent_caps in ({"socket": "/modern-agent", "device": 1, "inode": 2}, {}):
            with self.subTest(agent_caps=agent_caps), patch("xpra.server.source.ssh_agent.BACKWARDS_COMPATIBLE", True):
                caps = typedict({"ssh-agent": agent_caps, "ssh-auth-sock": "/legacy-agent"})
                self.assertEqual(SSHAgentConnection.is_needed(caps), bool(agent_caps))
                self.source.parse_client_caps(caps)
                self.assertEqual(self.source.ssh_auth_sock, agent_caps.get("socket", ""))
                self.assertEqual(self.source.ssh_auth_sock_stat, (1, 2) if agent_caps else ())

    def test_malformed_identity_is_ignored(self):
        for device, inode in ((None, None), (None, 2), (1, None), ("1", "2"), (1, float("inf")), (-1, 2), (1, 0)):
            with self.subTest(device=device, inode=inode):
                # Invalid or absent metadata must also clear any previous value.
                self.source.ssh_auth_sock_stat = (1, 2)
                self.source.parse_client_caps(typedict({"ssh-agent": {"socket": "/agent", "device": device, "inode": inode}}))
                self.assertEqual(self.source.ssh_auth_sock_stat, ())


if __name__ == "__main__":
    unittest.main()
