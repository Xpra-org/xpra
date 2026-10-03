#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base.client import XpraClientBase
from xpra.exit_codes import ExitCode
from xpra.scripts.config import InitExit


class SubsystemDispatchTest(unittest.TestCase):

    @staticmethod
    def make_client(method, error, result=None):
        # These dispatch tests only need the composed subsystem registry.
        client = XpraClientBase.__new__(XpraClientBase)
        failing = Mock(side_effect=error)
        following = Mock(return_value=result)
        client.subsystems = {
            "failing": SimpleNamespace(**{method: failing}),
            "following": SimpleNamespace(**{method: following}),
        }
        return client, failing, following

    def test_lifecycle_init_exit_aborts_startup(self):
        for method in ("init", "init_ui", "load", "run"):
            with self.subTest(method=method):
                error = InitExit(ExitCode.FAILURE, "cannot initialize subsystem")
                client, failing, following = self.make_client(method, error)
                args = (SimpleNamespace(display=":1"),) if method in ("init", "init_ui") else ()
                with patch("xpra.client.base.client.sublog") as log, self.assertRaises(InitExit) as raised:
                    getattr(client, method)(*args)
                self.assertIs(raised.exception, error)
                failing.assert_called_once_with(*args)
                following.assert_not_called()
                log.warn.assert_not_called()

    def test_lifecycle_other_errors_warn_and_continue(self):
        client, failing, following = self.make_client("load", ValueError("optional component failed"))
        with patch("xpra.client.base.client.sublog") as log:
            client.load()
        failing.assert_called_once_with()
        following.assert_called_once_with()
        log.warn.assert_called_once()

    def test_command_recorder_and_webcam_abort_before_main_loop(self):
        from xpra.client.base.command import CommandConnectClient
        from xpra.client.base.gobject import GObjectClientAdapter
        from xpra.client.base.record import RecordClient
        from xpra.client.gtk3.webcam_window import WebcamClient
        for cls in (CommandConnectClient, RecordClient, WebcamClient):
            with self.subTest(client=cls.__name__), tempfile.TemporaryDirectory() as directory:
                error = InitExit(ExitCode.FAILURE, "Landlock unavailable")
                client = cls.__new__(cls)
                client.subsystems = {"landlock": SimpleNamespace(run=Mock(side_effect=error))}
                client.record_directory = directory
                with patch.object(GObjectClientAdapter, "run") as run_loop, self.assertRaises(InitExit) as raised:
                    client.run()
                self.assertIs(raised.exception, error)
                run_loop.assert_not_called()

    def test_merge_init_exit_propagates(self):
        for method in ("get_caps", "get_info"):
            with self.subTest(method=method):
                error = InitExit(ExitCode.FAILURE, "cannot query subsystem")
                client, failing, following = self.make_client(method, error)
                with patch("xpra.client.base.client.sublog") as log, self.assertRaises(InitExit) as raised:
                    client._dispatch_merge(method)
                self.assertIs(raised.exception, error)
                failing.assert_called_once_with()
                following.assert_not_called()
                log.warn.assert_not_called()

    def test_merge_other_errors_warn_and_continue(self):
        expected = {"following": {"enabled": True}}
        client, failing, following = self.make_client("get_caps", ValueError("optional component failed"), expected)
        with patch("xpra.client.base.client.sublog") as log:
            self.assertEqual(client._dispatch_merge("get_caps"), expected)
        failing.assert_called_once_with()
        following.assert_called_once_with()
        log.warn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
