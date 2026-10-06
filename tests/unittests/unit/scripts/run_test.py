#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base.command import RunClient
from xpra.client.base.client import XpraClientBase
from xpra.exit_codes import ExitCode
from xpra.net.constants import SocketState
from xpra.scripts.config import make_defaults_struct
from xpra.scripts.main import connect_client_app, create_client_app, do_run_mode, run_proxy_run
from xpra.scripts.parsing import mode_needs_ssh_agent


class RunRoutingTest(unittest.TestCase):
    def test_client_dispatch(self):
        for mode in ("run", "exec"):
            with patch("xpra.scripts.main.basic_client_features"):
                client, displays, command = create_client_app(make_defaults_struct(), ["socket:///tmp/test", "echo", "hi"], mode)
            self.assertIsInstance(client, RunClient)
            self.assertEqual(client.exec_mode, mode == "exec")
            self.assertEqual(displays, ["socket:///tmp/test"])
            self.assertEqual(command, ["echo", "hi"])
            self.assertFalse(mode_needs_ssh_agent(mode))

    def test_ssh_proxy_selection(self):
        for compatible in (False, True):
            for mode in ("run", "exec"):
                opts = make_defaults_struct()
                opts.backend = "gtk"
                desc = {"type": "ssh", "display_as_args": [":100"]}
                client = Mock()
                with patch("xpra.net.common.BACKWARDS_COMPATIBLE", compatible), \
                     patch("xpra.scripts.main.do_pick_display", return_value=desc), \
                     patch("xpra.scripts.main.may_show_progress"), \
                     patch("xpra.scripts.main.connect_to_server") as connect:
                    connect_client_app(client, [], opts, ["ssh://host/100"], mode, ["echo", "hi"])
                self.assertEqual(desc["proxy_command"], ["_proxy_exec"] if mode == "exec" and not compatible else ["_proxy_run"])
                self.assertEqual("--env=XPRA_RUN_WAIT_TIME=0" in desc["display_as_args"], mode == "exec" and compatible)
                self.assertEqual(desc["display_as_args"][-2:], ["echo", "hi"])
                connect.assert_not_called()

    def test_proxy_exec_lifecycle(self):
        client = RunClient.__new__(RunClient)
        client.display_desc = {"proxy_command": ["_proxy_exec"]}
        with patch.object(XpraClientBase, "run") as run, patch("xpra.scripts.picker.connect_or_fail") as connect:
            self.assertEqual(client.run(), ExitCode.OK)
        run.assert_called_once()
        connect.assert_called_once_with(client.display_desc)

    def test_private_and_local_dispatch(self):
        for mode, args, expected in (("_proxy_run", [":100", "true"], "run"),
                                     ("_proxy_exec", [":100", "true"], "exec"),
                                     ("exec", [":100", "true"], "exec")):
            opts = make_defaults_struct()
            opts.systemd_run = "no"
            with patch("xpra.scripts.main.run_proxy_run", return_value=0) as run, \
                 patch("xpra.scripts.main.nox"), patch("xpra.scripts.main.configure_env"), \
                 patch("xpra.scripts.main.configure_logging"):
                do_run_mode("xpra", [], opts, args, mode, make_defaults_struct())
            self.assertEqual(run.call_args.args[-1], expected)

    def test_proxy_exec_live_server_and_fallback(self):
        opts = SimpleNamespace(socket_dirs=[], sessions_dir="", backend="auto")
        for live in (True, False):
            with patch("xpra.scripts.main.pick_display", return_value={"display_name": ":100"}), \
                 patch("xpra.scripts.main.DotXpra") as dotxpra, \
                 patch("xpra.scripts.main.run_client", return_value=0) as client, \
                 patch("xpra.scripts.main.run_daemon") as daemon:
                dotxpra.return_value.get_display_state.return_value = SocketState.LIVE if live else SocketState.UNKNOWN
                run_proxy_run(opts, "xpra", [], [":100", "true"], "exec")
            if live:
                self.assertEqual(client.call_args.args[-1], "exec")
                daemon.assert_not_called()
            else:
                client.assert_not_called()
                self.assertEqual(daemon.call_args.args, (["true"],))
                self.assertEqual(daemon.call_args.kwargs["env"]["DISPLAY"], ":100")


if __name__ == "__main__":
    unittest.main()
