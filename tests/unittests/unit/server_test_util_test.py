#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import signal
import unittest
from unittest.mock import Mock, mock_open, patch

from unit import server_test_util


class TestDisplayDbusCleanup(unittest.TestCase):

    def make_helper(self, output=b"dbus-pid=42\n"):
        helper = server_test_util.ServerTestUtil()
        helper.get_run_env = Mock(return_value={"KEEP": "value"})
        helper.get_xpra_cmd = Mock(return_value=["xpra"])
        helper.get_command_output = Mock(return_value=output)
        return helper

    def test_exit_cleans_only_the_local_display(self):
        for subcommand, args, expected in (
            ("exit", (":100",), True), ("stop", (":100",), False),
            ("exit", ("ssh://host/100",), False), ("exit", (), False),
        ):
            with self.subTest(subcommand=subcommand, args=args):
                helper = self.make_helper()
                helper.run_xpra = Mock()
                helper.stop_display_dbus = Mock()
                server = Mock()
                server.poll.return_value = None
                with patch.object(server_test_util, "pollwait", return_value=0):
                    helper.stop_server(server, subcommand, *args)
                if expected:
                    helper.stop_display_dbus.assert_called_once_with(":100")
                else:
                    helper.stop_display_dbus.assert_not_called()

    def test_confirmed_dbus_daemon_is_stopped(self):
        helper = self.make_helper()
        with patch("builtins.open", mock_open(read_data=b"dbus-daemon\n")) as opened, \
                patch.object(server_test_util.os, "kill") as kill:
            helper.stop_display_dbus(":100")
        opened.assert_called_once_with("/proc/42/comm", "rb")
        kill.assert_called_once_with(42, signal.SIGTERM)
        helper.get_command_output.assert_called_once_with(
            ["xpra", "wminfo"], env={"KEEP": "value", "DISPLAY": ":100"},
        )

    def test_other_or_missing_process_is_not_stopped(self):
        for command in (b"unrelated\n", None):
            with self.subTest(command=command):
                opened = mock_open(read_data=command or b"")
                if command is None:
                    opened.side_effect = FileNotFoundError()
                with patch("builtins.open", opened), patch.object(server_test_util.os, "kill") as kill:
                    self.make_helper().stop_display_dbus(":100")
                kill.assert_not_called()

    def test_missing_or_invalid_pid_is_ignored(self):
        for output in (b"", b"dbus-pid=0", b"dbus-pid=-1", b"dbus-pid=invalid", b"other=42", b"\xff"):
            with self.subTest(output=output), patch("builtins.open") as opened, \
                    patch.object(server_test_util.os, "kill") as kill:
                self.make_helper(output).stop_display_dbus(":100")
                opened.assert_not_called()
                kill.assert_not_called()

    def test_daemon_exit_during_cleanup_is_ignored(self):
        with patch("builtins.open", mock_open(read_data=b"dbus-daemon\n")), \
                patch.object(server_test_util.os, "kill", side_effect=ProcessLookupError()) as kill:
            self.make_helper().stop_display_dbus(":100")
        kill.assert_called_once_with(42, signal.SIGTERM)


if __name__ == '__main__':
    unittest.main()
