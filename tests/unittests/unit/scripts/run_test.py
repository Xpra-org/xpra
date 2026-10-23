#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import ast
import inspect
import unittest
from importlib.util import find_spec
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base.command import RunClient
from xpra.client.base.client import XpraClientBase
from xpra.exit_codes import ExitCode
from xpra.net.constants import SocketState
from xpra.config import InitExit
from xpra.config.defaults import make_defaults_struct
from xpra.scripts import main
from xpra.scripts.main import (
    connect_client_app, create_client_app, do_run_mode, run_proxy_run, run_server_mode, split_start_child_args,
    get_mode_handler,
)
from xpra.scripts.parsing import mode_needs_ssh_agent, get_usage, MODE_ALIAS


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


MODE_TABLES = (
    main.NO_ARGS_MODES, main.OPTIONS_MODES, main.ARGS_MODES, main.CMDLINE_MODES,
    main.OPTIONS_ARGS_MODES, main.OPTIONS_ARGS_CMDLINE_MODES,
)
FLAGS = ("no_extra_args", "max_one_arg", "requires_args", "posix", "audio", "x11", "no_gtk", "gtk_client", "gtk")


def explicit_modes() -> set[str]:
    # the modes that `do_run_mode` compares against, ie: `mode == "gui"` or `mode in ("set", "setting")`
    tree = ast.parse(inspect.getsource(do_run_mode))
    modes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "mode":
            for comparator in node.comparators:
                for c in ast.walk(comparator):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        modes.add(c.value)
    return modes


class ModeTableTest(unittest.TestCase):

    def test_tables(self):
        seen = set()
        for table in MODE_TABLES:
            for mode, (flags, handler) in table.items():
                self.assertNotIn(mode, seen, f"{mode!r} is in more than one table")
                seen.add(mode)
                for flag in filter(None, flags.split(",")):
                    self.assertIn(flag, FLAGS, f"invalid flag {flag!r} for {mode!r}")
                if callable(handler):
                    continue
                module_name, function_name = handler.split(":")
                try:
                    spec = find_spec(module_name)
                except ModuleNotFoundError:
                    # Optional parent packages may not be installed.
                    continue
                if not spec:
                    # ie: optional components like nvidia
                    continue
                if spec.origin and spec.origin.endswith(".py"):
                    with open(spec.origin, encoding="utf8") as f:
                        tree = ast.parse(f.read())
                    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
                    self.assertIn(function_name, names, f"{handler!r} not found for {mode!r}")
        self.assertFalse(seen & explicit_modes(), "modes handled twice")
        for mode in main.NO_ARGS_MODES | main.OPTIONS_MODES:
            self.assertIn("no_extra_args", main.NO_ARGS_MODES.get(mode, main.OPTIONS_MODES.get(mode))[0])

    def test_all_modes_dispatchable(self):
        handled = explicit_modes() | set(main.SERVER_SUBCOMMANDS) | set(main.CLIENT_SUBCOMMANDS)
        for table in MODE_TABLES:
            handled |= set(table)
        usage = tuple(line.split(" ")[0] for line in get_usage() if line)
        for mode in main.NO_NETWORK_SUBCOMMANDS + main.STDOUT_SUBCOMMANDS + usage:
            mode = MODE_ALIAS.get(mode, mode)
            if mode.startswith("request-") or mode.startswith("_proxy") or mode.startswith("upgrade-"):
                continue
            self.assertIn(mode, handled, f"{mode!r} cannot be dispatched")

    def test_argument_flags(self):
        def check(flags, args):
            with self.assertRaises(InitExit) as cm:
                get_mode_handler("test", args, flags, noop)
            self.assertEqual(cm.exception.status, ExitCode.ARGUMENT_MISMATCH)

        def noop(*_args):
            return 0

        check("no_extra_args", ["extra"])
        check("max_one_arg", ["one", "two"])
        check("requires_args", [])
        for flags, args in (("no_extra_args", []), ("max_one_arg", ["one"]), ("requires_args", ["one"]), ("", ["a", "b"])):
            self.assertIs(get_mode_handler("test", args, flags, noop), noop)
        with self.assertRaises(ValueError):
            get_mode_handler("test", [], "invalid", noop)

    def test_guard_flags(self):
        for flag, fn, call_args in (
            ("no_gtk", "no_gtk", ()),
            ("gtk_client", "check_gtk_client", ()),
            ("gtk", "check_gtk", ("test", )),
            ("x11", "reqx11", ("test", )),
        ):
            with patch(f"xpra.scripts.main.{fn}") as guard:
                get_mode_handler("test", [], flag, print)
            guard.assert_called_once_with(*call_args)

    def test_audio_flag(self):
        with patch("xpra.scripts.main.has_audio_support", return_value=False):
            with self.assertRaises(InitExit) as cm:
                get_mode_handler("test", [], "audio", print)
            self.assertEqual(cm.exception.status, ExitCode.COMPONENT_MISSING)
        with patch("xpra.scripts.main.has_audio_support", return_value=True):
            self.assertIs(get_mode_handler("test", [], "audio", print), print)

    def test_lazy_handler(self):
        from xpra.scripts.sessions import run_list
        self.assertIs(get_mode_handler("list", [], "", "xpra.scripts.sessions:run_list"), run_list)

    def test_dispatch(self):
        opts = make_defaults_struct()
        with patch("xpra.scripts.main.no_gtk") as no_gtk, patch("xpra.scripts.sessions.run_list_sessions", return_value=0) as handler:
            self.assertEqual(do_run_mode("xpra", [], opts, [], "list-sessions", None), 0)
            no_gtk.assert_called_once()
            handler.assert_called_once_with(opts, [])
            with self.assertRaises(InitExit) as cm:
                do_run_mode("xpra", [], opts, ["unexpected-arg"], "list-sessions", None)
            self.assertEqual(cm.exception.status, ExitCode.ARGUMENT_MISMATCH)
            self.assertIn("usage: xpra list-sessions", str(cm.exception))
            handler.assert_called_once()


if __name__ == "__main__":
    unittest.main()
