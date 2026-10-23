#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from unittest.mock import patch

from xpra.scripts import parsing


class SSHArgumentsTest(unittest.TestCase):
    def test_exact_backend_arguments(self):
        desc = {"host": "host", "username": "alice", "password": "secret", "port": 2222}
        for backend, expected in (
            ("ssh", ["-l", "alice", "-p", "2222", "-T", "host"]),
            ("plink.exe", ["-pw", "secret", "-l", "alice", "-P", "2222", "-T", "host"]),
            ("putty", ["-pw", "secret", "-l", "alice", "-P", "2222", "-T", "host"]),
            ("paramiko", []), ("asyncssh", []),
        ):
            with self.subTest(backend=backend):
                self.assertEqual(parsing.get_ssh_args(desc, [backend]), expected)
        with self.assertRaisesRegex(RuntimeError, "missing host"):
            parsing.get_ssh_args({})

    def test_proxy_arguments_mutate_original_command(self):
        desc = {"proxy_host": "jump", "proxy_username": "bob", "proxy_port": 2222, "proxy_password": "a&b"}
        for command, tail, expected in (
            (["ssh", "-x"], ["-W", "%h:%p", "-l", "bob", "-p", "2222", "-T", "jump"],
             ["-o", "ProxyCommand ssh -x -W %h:%p -l bob -p 2222 -T jump"]),
            (["plink"], ["-nc", "%host:%port", "-pw", "a&b", "-l", "bob", "-P", "2222", "-T", "jump"],
             ["-proxycmd", "plink -nc %host:%port -pw a&b -l bob -P 2222 -T jump"]),
            (["paramiko"], [], []), (["asyncssh"], [], []),
        ):
            original = command[:]
            with self.subTest(command=command):
                self.assertEqual(parsing.get_ssh_proxy_args(desc, command), expected)
                self.assertEqual(command, original + tail)

    def test_agent_forwarding_and_uuid_lookup(self):
        for setting, mode, env, expected in (
            ("ssh -x", "attach", {}, False), ("ssh -A", "run", {}, True),
            ("paramiko", "attach", {}, True), ("asyncssh", "request-start", {}, False),
            ("paramiko:agent=no", "attach", {}, False), ("asyncssh:agent=yes", "info", {}, True),
            ("paramiko", "exec", {"XPRA_SSH_AGENT": "1"}, True),
            ("paramiko", "attach", {"XPRA_SSH_AGENT": "0"}, True),
        ):
            with self.subTest(setting=setting, mode=mode, env=env), \
                    patch.dict(os.environ, env, clear=True), \
                    patch.object(parsing, "get_user_uuid", return_value="test-uuid") as uuid:
                args = ["10"]
                desc = parsing.get_ssh_display_attributes(args, setting, mode)
            self.assertIs(desc["agent"], expected)
            self.assertEqual(args, ["10", "--env=SSH_AGENT_UUID=test-uuid"] if expected else ["10"])
            self.assertEqual(uuid.call_count, int(expected))
            if expected:
                self.assertEqual(desc["ssh-agent-uuid"], "test-uuid")

    def test_key_paths(self):
        desc = {"host": "host", "key": "relative/key"}
        with patch.object(parsing, "WIN32", False):
            self.assertEqual(parsing.get_ssh_args(desc, ["ssh"]), ["-T", "host", "-i", os.path.abspath("relative/key")])
        with patch.object(parsing, "WIN32", True):
            desc["key"] = "relative\\key"
            self.assertEqual(parsing.get_ssh_args(desc, ["plink"]), ["-T", "host", "-i", '"relative/key"'])


if __name__ == "__main__":
    unittest.main()
