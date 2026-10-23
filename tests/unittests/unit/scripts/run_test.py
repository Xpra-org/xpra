#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base.command import RunClient
from xpra.client.base.client import XpraClientBase
from xpra.exit_codes import ExitCode
from xpra.net.constants import SocketState
from xpra.config.defaults import make_defaults_struct
from xpra.scripts.main import (
    connect_client_app, create_client_app, do_run_mode, run_proxy_run, run_server_mode, split_start_child_args,
)
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
        for mode in ("run", "exec"):
            opts = make_defaults_struct()
            opts.backend = "gtk"
            desc = {"type": "ssh", "display_as_args": [":100"]}
            client = Mock()
            with patch("xpra.scripts.main.do_pick_display", return_value=desc), \
                 patch("xpra.scripts.main.may_show_progress"), \
                 patch("xpra.scripts.main.connect_to_server") as connect:
                connect_client_app(client, [], opts, ["ssh://host/100"], mode, ["echo", "hi"])
            self.assertEqual(desc["proxy_command"], ["_proxy_exec"] if mode == "exec" else ["_proxy_run"])
            self.assertNotIn("--env=XPRA_RUN_WAIT_TIME=0", desc["display_as_args"])
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


class StartChildArgsTest(unittest.TestCase):

    def split(self, args, cmdline=(), env=None, **kwargs):
        opts = make_defaults_struct()
        opts.start_child = []
        opts.exit_with_children = False
        opts.attach = None
        for k, v in kwargs.items():
            setattr(opts, k, v)
        with patch.dict(os.environ, env or {}, clear=True), \
             patch("xpra.scripts.main.OSX", False), patch("xpra.scripts.main.WIN32", False):
            return split_start_child_args(list(cmdline), opts, args), opts

    def test_connection_args_only(self):
        args = ["ssh://host/", ":10"]
        newargs, opts = self.split(args, env={"DISPLAY": ":0"})
        self.assertIs(newargs, args)
        self.assertEqual(opts.start_child, [])
        self.assertFalse(opts.exit_with_children)
        self.assertIsNone(opts.attach)

    def test_commands(self):
        newargs, opts = self.split(["ssh://host/", "xterm", "fluxbox"], env={"DISPLAY": ":0"})
        self.assertEqual(newargs, ["ssh://host/"])
        self.assertEqual(opts.start_child, ["xterm", "fluxbox"])
        self.assertTrue(opts.exit_with_children)
        self.assertTrue(opts.attach)

    def test_no_display(self):
        _, opts = self.split(["xterm"])
        self.assertFalse(opts.attach)

    def test_cmdline_overrides(self):
        _, opts = self.split(["xterm"], cmdline=["--no-exit-with-children", "--no-attach"], env={"DISPLAY": ":0"})
        self.assertFalse(opts.exit_with_children)
        self.assertIsNone(opts.attach)

    def test_html_open(self):
        _, opts = self.split(["xterm"], env={"DISPLAY": ":0"}, html="open")
        self.assertIsNone(opts.attach)


class ServerModeTest(unittest.TestCase):

    def run_server_mode(self, args, state=SocketState.UNKNOWN, mode="seamless", attach="yes"):
        opts = make_defaults_struct()
        opts.attach = attach
        with patch("xpra.scripts.main.run_remote_server", return_value="remote") as remote, \
             patch("xpra.scripts.main.run_server", return_value="server") as server, \
             patch("xpra.scripts.main.run_client", return_value="client") as client, \
             patch("xpra.scripts.main.pick_display", return_value={"display_name": ":10"}), \
             patch("xpra.scripts.main.DotXpra") as dotxpra:
            dotxpra.return_value.get_display_state.return_value = state
            r = run_server_mode("xpra", [], opts, args, mode, mode, None)
        return r, opts, remote, server, client

    def test_remote(self):
        r, _, remote, server, _ = self.run_server_mode(["ssh://host/10"])
        self.assertEqual(r, "remote")
        server.assert_not_called()
        self.assertEqual(remote.call_args.args[4], "seamless")

    def test_attach_live(self):
        r, opts, _, server, client = self.run_server_mode([":10"], SocketState.LIVE)
        self.assertEqual(r, "client")
        server.assert_not_called()
        self.assertEqual(client.call_args.args[-1], "attach")
        self.assertEqual(opts.mode, "attach")
        self.assertEqual(opts.csc_modules, ["none"])
        self.assertEqual(opts.video_decoders, ["none"])

    def test_start(self):
        for args, state, mode, attach in (
            ([":10"], SocketState.DEAD, "seamless", "yes"),
            ([":10"], SocketState.LIVE, "seamless", "no"),
            ([":10"], SocketState.LIVE, "proxy", "yes"),
            ([], SocketState.LIVE, "desktop", "yes"),
        ):
            r, _, remote, _, client = self.run_server_mode(args, state, mode, attach)
            self.assertEqual(r, "server")
            remote.assert_not_called()
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
