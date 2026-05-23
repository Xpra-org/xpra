#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.scripts.session import save_session_file
from xpra.scripts.server import (
    get_server_log_dir,
    is_splash_enabled,
    resolve_x11_display,
    setup_xauthority,
    start_server_vfb,
    write_initial_session_files,
)


class TestMain(unittest.TestCase):

    def test_splash_enabled(self):
        assert is_splash_enabled("foo", True, True, ":10") is False, "splash should not be enabled for daemons"
        assert is_splash_enabled("foo", False, False, ":10") is False, "splash should not be enabled for splash=False"
        assert is_splash_enabled("foo", False, True, ":10") is True, "splash should be enabled for splash=True"

    def test_write_initial_session_files(self):
        with tempfile.TemporaryDirectory() as sessions_dir, patch.dict(os.environ, {}, clear=False):
            session_dir = write_initial_session_files("seamless", sessions_dir, ":42", os.getuid(), os.getgid(),
                                                      None, "SERVER_ENV=1", ("xpra", "start", ":42"))
            assert session_dir == os.path.join(sessions_dir, "42")
            assert os.environ["XPRA_SESSION_DIR"] == session_dir
            with open(os.path.join(session_dir, "server.env"), encoding="utf8") as f:
                assert f.read() == "SERVER_ENV=1"
            with open(os.path.join(session_dir, "cmdline"), encoding="utf8") as f:
                assert f.read() == "xpra\nstart\n:42\n"

    def test_get_server_log_dir(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XPRA_LOG_DIR", None)
            assert get_server_log_dir(False, False, "auto", "/session") == "auto"
            assert "XPRA_LOG_DIR" not in os.environ
            assert get_server_log_dir(True, False, "auto", "/session") == "/session"
            assert os.environ["XPRA_LOG_DIR"] == "/session"

    def test_setup_xauthority_reuses_session_file(self):
        with tempfile.TemporaryDirectory() as session_dir, tempfile.NamedTemporaryFile() as xauth_file:
            with patch.dict(os.environ, {"XPRA_SESSION_DIR": session_dir}, clear=False):
                os.environ.pop("XAUTHORITY", None)
                save_session_file("xauthority", xauth_file.name)
                xauthority = setup_xauthority(":42", "test", os.getuid(), os.getgid(), False, False,
                                              lambda *_args: self.fail("existing xauthority must not be rewritten"),
                                              lambda *_args: None)
                assert xauthority == xauth_file.name
                assert os.environ["XAUTHORITY"] == xauth_file.name

    def test_start_server_vfb_noop_for_proxy(self):
        result = start_server_vfb(SimpleNamespace(), "proxy", ":100", ":100", False, (), "", None,
                                  "/tmp", os.getuid(), os.getgid(), "test", {}, None, False, True,
                                  False, False, False, False, "/session", "/log", lambda *_args: "",
                                  lambda *_args: None, lambda *_args: None)
        assert result.xvfb is None
        assert result.xvfb_pid == 0
        assert result.devices == {}
        assert result.display_name == ":100"
        assert result.session_dir == "/session"
        assert result.log_dir == "/log"

    def test_resolve_x11_display_missing_upgrade(self):
        errors = []
        result = resolve_x11_display("", "/xauth", "", True, None, True, False, False, False, None,
                                     os.getuid(), os.getgid(), errors.append, lambda *_args: None,
                                     lambda *_args: None)
        assert result.start_vfb is True
        assert result.xauth_data == ""
        assert result.use_display is False
        assert errors == ["no displays found to upgrade"]

    def test_resolve_x11_display_verified(self):
        progress = []
        with patch("xpra.scripts.server.no_gtk") as no_gtk, \
                patch("xpra.scripts.server.verify_display", return_value=True):
            result = resolve_x11_display(":42", "/xauth", "abc", True, None, False, False, False, False, None,
                                         os.getuid(), os.getgid(), self.fail, lambda *args: progress.append(args),
                                         lambda *_args: None)
        no_gtk.assert_called_once()
        assert result.start_vfb is False
        assert result.xauth_data == "abc"
        assert result.use_display is None
        assert progress == [(40, "connecting to the display"), (40, "connected to the display")]

    def test_resolve_x11_display_readds_xauth(self):
        pam = SimpleNamespace(items=[])
        pam.set_items = pam.items.append
        with patch("xpra.scripts.server.no_gtk"), \
                patch("xpra.scripts.server.verify_display", side_effect=(False, True)), \
                patch("xpra.scripts.server.stat_display_socket", return_value={"uid": os.getuid()}), \
                patch("xpra.scripts.server.get_hex_uuid", return_value="uuid"), \
                patch("xpra.x11.vfb_util.xauth_add") as xauth_add:
            result = resolve_x11_display(":42", "/xauth", "", True, None, False, False, False, False, pam,
                                         os.getuid(), os.getgid(), self.fail, lambda *_args: None,
                                         lambda *_args: None)
        assert result.start_vfb is False
        assert result.xauth_data == "uuid"
        assert pam.items == [{"XAUTHDATA": "uuid"}]
        xauth_add.assert_called_once_with("/xauth", ":42", "uuid", os.getuid(), os.getgid())


def main():
    unittest.main()


if __name__ == '__main__':
    main()
