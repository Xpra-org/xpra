#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import tempfile
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from xpra.scripts.session import save_session_file
from xpra.scripts.server import (
    VFBStartResult,
    add_desktop_greeter,
    check_vfb_startup,
    get_server_log_dir,
    has_child_arg,
    init_virtual_devices,
    is_splash_enabled,
    make_server_app,
    resolve_x11_display,
    set_vfb_startup_state,
    setup_pam_session,
    setup_runtime_dir,
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

    def test_setup_pam_session_disabled(self):
        stderr = SimpleNamespace(write=self.fail)
        with patch("xpra.scripts.server.POSIX", True), \
                patch("xpra.scripts.server.envbool", return_value=False):
            result = setup_pam_session("alice", ":42", "abc", True, 1000, stderr)
        assert result.pam is None
        assert result.protected_env == {}

    def test_setup_pam_session(self):
        class FakePam:
            def __init__(self):
                self.env = {}
                self.items = {}

            def start(self):
                return True

            def set_env(self, env):
                self.env = env

            def set_items(self, items):
                self.items = items

            def open(self):
                return True

            def get_envlist(self):
                return {"PAM_ENV": "1"}

        fake_pam = FakePam()
        pam_module = ModuleType("xpra.platform.pam")
        pam_module.pam_session = lambda username: fake_pam
        stderr = SimpleNamespace(write=self.fail)
        with patch.dict(sys.modules, {"xpra.platform.pam": pam_module}), \
                patch.dict(os.environ, {}, clear=False), \
                patch("xpra.scripts.server.POSIX", True), \
                patch("xpra.scripts.server.envbool", return_value=True):
            os.environ.pop("PAM_ENV", None)
            result = setup_pam_session("alice", ":42", "abc", True, 1000, stderr)
            assert os.environ["PAM_ENV"] == "1"
        assert result.pam is fake_pam
        assert result.protected_env == {"PAM_ENV": "1"}
        assert fake_pam.env == {
            "XDG_SESSION_TYPE": "x11",
            "XDG_SESSION_DESKTOP": "xpra",
        }
        assert fake_pam.items == {"XDISPLAY": ":42", "XAUTHDATA": "abc"}

    def test_setup_runtime_dir_from_env_options(self):
        with patch("xpra.scripts.server.create_runtime_dir", return_value="/tmp/xpra-runtime") as create_runtime_dir:
            result = setup_runtime_dir(("XDG_RUNTIME_DIR=/tmp/xpra-runtime",), True, 1000, 1000, {"PAM_ENV": "1"})
        create_runtime_dir.assert_called_once_with("/tmp/xpra-runtime", 1000, 1000)
        assert result.xrd == "/tmp/xpra-runtime"
        assert result.protected_env == {
            "PAM_ENV": "1",
            "XDG_RUNTIME_DIR": "/tmp/xpra-runtime",
        }

    def test_setup_runtime_dir_filters_unsafe_root_path(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/tmp/fallback-runtime"}, clear=False), \
                patch("xpra.scripts.server.create_runtime_dir", return_value="/tmp/fallback-runtime") as create_runtime_dir:
            result = setup_runtime_dir(("XDG_RUNTIME_DIR=/run/unsafe",), True, 1000, 1000, {})
        create_runtime_dir.assert_called_once_with("/tmp/fallback-runtime", 1000, 1000)
        assert result.xrd == "/tmp/fallback-runtime"
        assert result.protected_env == {"XDG_RUNTIME_DIR": "/tmp/fallback-runtime"}

    def make_greeter_opts(self):
        return SimpleNamespace(
            start=[],
            start_late=[],
            start_child=[],
            start_child_late=[],
            start_after_connect=[],
            start_child_after_connect=[],
            start_on_connect=[],
            start_child_on_connect=[],
            start_on_disconnect=[],
            start_child_on_disconnect=[],
            start_on_last_client_exit=[],
            start_child_on_last_client_exit=[],
        )

    def test_add_desktop_greeter(self):
        opts = self.make_greeter_opts()
        with patch("xpra.scripts.server.POSIX", True), \
                patch("xpra.scripts.server.DESKTOP_GREETER", True):
            add_desktop_greeter(opts, True, False)
        assert opts.start == ["xpra desktop-greeter"]

    def test_add_desktop_greeter_preserves_existing_commands(self):
        opts = self.make_greeter_opts()
        opts.start_child.append("xterm")
        with patch("xpra.scripts.server.POSIX", True), \
                patch("xpra.scripts.server.DESKTOP_GREETER", True):
            add_desktop_greeter(opts, True, False)
        assert opts.start == []
        assert opts.start_child == ["xterm"]

    def test_has_child_arg(self):
        opts = self.make_greeter_opts()
        assert has_child_arg(opts) is False
        opts.start_child_on_last_client_exit.append("xterm")
        assert has_child_arg(opts) is True

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
        assert result.xvfb_cmd == ()
        assert result.displayfd == 0

    def test_set_vfb_startup_state(self):
        state_calls = []
        displayfd_calls = []
        state = VFBStartResult(None, 123, {}, ":42", "/session", "/log", ("Xvfb",), 7)
        display = SimpleNamespace(set_vfb_startup_state=state_calls.append,
                                  publish_displayfd=lambda display_name, fd: displayfd_calls.append((display_name, fd)))
        app = SimpleNamespace(get_subsystem=lambda name: display if name == "display" else None)
        set_vfb_startup_state(app, state)
        assert state_calls == [state]
        assert displayfd_calls == [(":42", 7)]

    def test_publish_displayfd(self):
        from xpra.server.subsystem.display import DisplayManager
        with patch("xpra.platform.displayfd.write_displayfd", return_value=True) as write_displayfd:
            DisplayManager.publish_displayfd(":42", 7)
        write_displayfd.assert_called_once_with(7, "42")

    def test_publish_vfb_pid(self):
        from xpra.x11.subsystem.display import X11DisplayManager
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XVFB_PID", None)
            X11DisplayManager.publish_vfb_pid(123)
            assert os.environ["XVFB_PID"] == "123"

    def test_x11_display_startup_state_publishes_vfb_pid(self):
        from xpra.x11.subsystem.display import X11DisplayManager
        state = VFBStartResult(None, 123, {}, ":42", "/session", "/log", ("Xvfb",), 7)
        display = X11DisplayManager.__new__(X11DisplayManager)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XVFB_PID", None)
            X11DisplayManager.set_vfb_startup_state(display, state)
            assert os.environ["XVFB_PID"] == "123"
        assert display.vfb_startup_state is state
        assert display.xvfb is None
        assert display.xvfb_cmd == ("Xvfb",)
        assert display.display_pid == 123

    def test_make_server_app(self):
        opts = SimpleNamespace(backend="x11")
        attrs = {}
        with patch("xpra.scripts.server.make_proxy_server", return_value="proxy"):
            app = make_server_app(attrs, opts, 0, "proxy", ":42")
        assert app == "proxy"
        assert attrs["backend"] == "x11"

        attrs = {}
        with patch("xpra.scripts.server.make_shadow_server", return_value="shadow") as make_shadow:
            app = make_server_app(attrs, opts, 0, "shadow", ":42")
        assert app == "shadow"
        make_shadow.assert_called_once_with(":42", {"backend": "x11", "multi-window": "True"})

        attrs = {}
        with patch("xpra.scripts.server.make_seamless_server", return_value="seamless"):
            app = make_server_app(attrs, opts, 0, "upgrade", ":42")
        assert app == "seamless"

    def test_check_vfb_startup(self):
        display = SimpleNamespace(check_vfb_process=lambda timeout=0: timeout == 7)
        app = SimpleNamespace(get_subsystem=lambda name: display if name == "display" else None)
        assert check_vfb_startup(app, timeout=7) is True
        assert check_vfb_startup(app, timeout=1) is False

    def test_init_virtual_devices(self):
        calls = []
        pointer = SimpleNamespace(init_virtual_devices=calls.append)
        app = SimpleNamespace(get_subsystem=lambda name: pointer if name == "pointer" else None)
        devices = {"pointer": {"device": "/dev/input/event0"}}
        init_virtual_devices(app, {})
        init_virtual_devices(app, devices)
        assert calls == [devices]

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
