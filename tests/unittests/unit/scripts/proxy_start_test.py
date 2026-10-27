#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

from xpra.scripts import main as scripts_main
from xpra.scripts.config import make_defaults_struct


@unittest.skipUnless(scripts_main.POSIX and not scripts_main.OSX, "displayfd startup requires POSIX without macOS")
class TestServerDisplayFD(unittest.TestCase):

    def test_display_names(self):
        for payload, display in ((b"77\n", ":77"), (b"wayland-12\n", "wayland-12")):
            with self.subTest(payload=payload):
                opts = make_defaults_struct()
                process = Mock()
                dotxpra = Mock()
                dotxpra.socket_paths.return_value = ()

                def spawn(_cmd, **kwargs):
                    os.write(kwargs["pass_fds"][0], payload)
                    return process

                with patch.object(scripts_main, "Popen", side_effect=spawn), \
                        patch.object(scripts_main, "add_process"), \
                        patch.object(scripts_main, "DotXpra", return_value=dotxpra), \
                        patch.object(scripts_main, "get_start_server_args", return_value=[]), \
                        patch.object(scripts_main, "identify_new_socket", return_value=("/tmp/xpra-test", display)) as identify:
                    result = scripts_main.start_server_subprocess("/usr/bin/xpra", [], "seamless", opts)
                self.assertEqual(identify.call_args.args[3], display)
                self.assertEqual(result, (process, "/tmp/xpra-test", display))


class TestStartOnExisting(unittest.TestCase):

    def run_start(self, start=(), start_child=(), returncode=0, default_start=()):
        opts = make_defaults_struct()
        defaults = make_defaults_struct()
        opts.start = list(default_start) + list(start)
        opts.start_child = list(start_child)
        defaults.start = list(default_start)
        defaults.start_child = []
        result = CompletedProcess([], returncode, b"", b"new command started with pid=1\n")
        with patch.object(scripts_main, "run", return_value=result) as run, \
                patch.object(scripts_main, "stderr_print") as stderr_print:
            scripts_main.start_commands_on_existing("/usr/bin/xpra", ":100", opts, defaults)
        return run, stderr_print

    def test_commands(self):
        run, _ = self.run_start(start=["xterm -T 'a title'"], start_child=["xclock"], default_start=["ibus-daemon"])
        cmds = [c.args[0] for c in run.call_args_list]
        # the defaults from the config files are not started again:
        self.assertEqual(cmds, [
            ["/usr/bin/xpra", "control", ":100", "start", "--", "xterm", "-T", "a title"],
            ["/usr/bin/xpra", "control", ":100", "start-child", "--", "xclock"],
        ])
        for c in run.call_args_list:
            # our stdout is the connection to the client:
            self.assertTrue(c.kwargs.get("capture_output"))
            self.assertNotIn("stdout", c.kwargs)

    def test_nothing_to_start(self):
        run, _ = self.run_start(default_start=["ibus-daemon"])
        run.assert_not_called()

    def test_failure_reported(self):
        _, stderr_print = self.run_start(start=["nosuchcommand"], returncode=1)
        messages = " ".join(str(c.args[0]) for c in stderr_print.call_args_list)
        self.assertIn("failed to start 'nosuchcommand' on display :100", messages)


class TestProxyStartedClient(unittest.TestCase):

    def make_client(self, show_display: bool):
        from xpra.client.base import command
        client = command.ProxyStartedClient(make_defaults_struct(), show_display=show_display)
        client.hello_extra |= {"connect": False}
        return command, client

    def test_identifies_without_detaching(self):
        _, client = self.make_client(False)
        # a `detach` request would disconnect the clients already attached to the session:
        self.assertEqual(client.hello_extra.get("request"), "id")

    def test_shows_chosen_display(self):
        from xpra.exit_codes import ExitCode
        from xpra.util.objects import typedict
        for show_display, expected in ((True, ["session available on display :101"]), (False, [])):
            command, client = self.make_client(show_display)
            with patch.object(command, "log") as log, patch.object(client, "quit") as quit_fn:
                client.do_command(typedict({"display": ":101"}))
            self.assertEqual([c.args[0] for c in log.info.call_args_list], expected)
            quit_fn.assert_called_once_with(ExitCode.OK)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
