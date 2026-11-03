#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.client.subsystem.ssh_agent import SSHAgentClient


class SSHAgentClientTest(unittest.TestCase):

    def setUp(self):
        client = SimpleNamespace(idle_add=lambda *a: None, timeout_add=lambda *a: None, source_remove=lambda *a: None)
        self.agent = SSHAgentClient(client)
        self.path = os.path.join(tempfile.gettempdir(), "xpra-test-agent")
        env = patch.dict(os.environ, {"SSH_AUTH_SOCK": self.path})
        env.start()
        self.addCleanup(env.stop)
        compatibility = patch("xpra.client.subsystem.ssh_agent.BACKWARDS_COMPATIBLE", False)
        compatibility.start()
        self.addCleanup(compatibility.stop)

    def test_stat_identity_is_advertised(self):
        # Device zero is valid; inode numbers need not fit in signed 64 bits.
        sockstat = SimpleNamespace(st_dev=0, st_ino=2**64-1)
        with patch("xpra.client.subsystem.ssh_agent.os.stat", return_value=sockstat) as stat:
            caps = self.agent.get_caps()
        stat.assert_called_once_with(self.path)
        self.assertEqual(caps, {"ssh-agent": {"socket": self.path, "device": 0, "inode": 2**64-1}})

    def test_legacy_path_is_advertised_only_in_compatibility_mode(self):
        sockstat = SimpleNamespace(st_dev=1, st_ino=2)
        for compatible in (True, False):
            with self.subTest(compatible=compatible), \
                    patch("xpra.client.subsystem.ssh_agent.BACKWARDS_COMPATIBLE", compatible), \
                    patch("xpra.client.subsystem.ssh_agent.os.stat", return_value=sockstat):
                caps = self.agent.get_caps()
                expected = {"ssh-agent": {"socket": self.path, "device": 1, "inode": 2}}
                if compatible:
                    expected["ssh-auth-sock"] = self.path
                self.assertEqual(caps, expected)

    def test_no_absolute_agent_path(self):
        for path in ("", "relative-agent"):
            with self.subTest(path=path), patch.dict(os.environ, {"SSH_AUTH_SOCK": path}), \
                    patch("xpra.client.subsystem.ssh_agent.os.stat") as stat:
                self.assertEqual(self.agent.get_caps(), {})
                stat.assert_not_called()

    def test_stat_failure_keeps_path_without_identity(self):
        for error in (FileNotFoundError(), PermissionError(), ValueError()):
            with self.subTest(error=type(error)), patch("xpra.client.subsystem.ssh_agent.os.stat", side_effect=error):
                self.assertEqual(self.agent.get_caps(), {"ssh-agent": {"socket": self.path}})

    def test_unavailable_identity_is_not_advertised(self):
        for fields in (
            {}, {"st_dev": 1}, {"st_ino": 1},
            {"st_dev": None, "st_ino": 1}, {"st_dev": -1, "st_ino": 1},
            {"st_dev": 1, "st_ino": None}, {"st_dev": 1, "st_ino": 0}, {"st_dev": 1, "st_ino": -1},
        ):
            with self.subTest(fields=fields), \
                    patch("xpra.client.subsystem.ssh_agent.os.stat", return_value=SimpleNamespace(**fields)):
                self.assertEqual(self.agent.get_caps(), {"ssh-agent": {"socket": self.path}})


if __name__ == "__main__":
    unittest.main()
