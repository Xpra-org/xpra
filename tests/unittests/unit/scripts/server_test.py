#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from io import StringIO
import tempfile
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from xpra.scripts.config import InitException
from xpra.scripts.session import save_session_file
from xpra.scripts.server import (
    VFBStartResult,
    add_desktop_greeter,
    harden_server_process,
    has_child_arg,
    init_virtual_devices,
    is_splash_enabled,
    make_server_app,
    request_upgrade_display,
    resolve_server_display_name,
    sanitize_dbus_env,
    set_vfb_startup_state,
)
from xpra.server.subsystem.process import setup_pam_session, setup_runtime_dir


class TestMain(unittest.TestCase):

    def test_harden_server_process(self):
        harden_process = Mock()
        security_module = ModuleType("xpra.platform.posix.security")
        security_module.harden_process = harden_process
        with patch.dict(sys.modules, {"xpra.platform.posix.security": security_module}), \
             patch("xpra.scripts.server.LINUX", False):
            harden_server_process()
        harden_process.assert_not_called()
        with patch.dict(sys.modules, {"xpra.platform.posix.security": security_module}), \
             patch("xpra.scripts.server.LINUX", True):
            harden_server_process()
        harden_process.assert_called_once_with()

    def test_harden_server_process_failure(self):
        security_module = ModuleType("xpra.platform.posix.security")
        security_module.harden_process = Mock(side_effect=OSError(1, "not permitted"))
        with patch.dict(sys.modules, {"xpra.platform.posix.security": security_module}), \
             patch("xpra.scripts.server.LINUX", True), \
             self.assertRaisesRegex(InitException, "failed to harden the server process"):
            harden_server_process()

    def test_splash_enabled(self):
        assert is_splash_enabled("foo", True, True, ":10") is False, "splash should not be enabled for daemons"
        assert is_splash_enabled("foo", False, False, ":10") is False, "splash should not be enabled for splash=False"
        assert is_splash_enabled("foo", False, True, ":10") is True, "splash should be enabled for splash=True"

    def test_setup_session_dir(self):
        from xpra.server.subsystem.sessionfiles import SessionFilesServer
        session_files = SessionFilesServer(SimpleNamespace(subsystems={}))
        session_files.init(SimpleNamespace(uid=os.getuid(), gid=os.getgid()))
        with tempfile.TemporaryDirectory() as sessions_dir, patch.dict(os.environ, {}, clear=False):
            session_dir = session_files.setup_session_dir("seamless", sessions_dir, ":42")
            assert session_dir == os.path.join(sessions_dir, "42")
            assert os.environ["XPRA_SESSION_DIR"] == session_dir

    def test_get_server_log_dir(self):
        from xpra.server.subsystem.daemon import DaemonServer
        with patch.dict(os.environ, {"XPRA_SESSION_DIR": "/session"}, clear=False):
            os.environ.pop("XPRA_LOG_DIR", None)
            assert DaemonServer.get_server_log_dir(False, False, "auto") == "auto"
            assert "XPRA_LOG_DIR" not in os.environ
            assert DaemonServer.get_server_log_dir(True, False, "auto") == "/session"
            assert os.environ["XPRA_LOG_DIR"] == "/session"

    def test_daemon_init_does_not_write_pidfile(self):
        from xpra.server.subsystem.daemon import DaemonServer
        opts = SimpleNamespace(
            pidfile="/tmp/xpra-test.pid",
            daemon=True,
            log_dir="auto",
            log_file="",
            uid=os.getuid(),
            gid=os.getgid(),
        )
        daemon = DaemonServer()
        with patch("xpra.server.subsystem.daemon.write_pidfile", return_value=123) as write_pidfile:
            daemon.init(opts)
            daemon.init(opts)
            write_pidfile.assert_not_called()
            daemon.write_pid()
        write_pidfile.assert_called_once_with("/tmp/xpra-test.pid")
        assert daemon.daemon is True
        assert daemon.pidinode == 123

    def test_daemon_session_dir_changed_logs_final_dir(self):
        from xpra.server.subsystem.daemon import DaemonServer
        daemon = DaemonServer()
        daemon.daemon = True
        daemon.session_dir = "/run/user/1000/xpra/S123"
        daemon.stderr = StringIO()
        daemon.session_dir_changed("/run/user/1000/xpra/42")
        assert daemon.log_dir == "/run/user/1000/xpra/42"
        assert daemon.stderr.getvalue() == "Actual session directory is now: '/run/user/1000/xpra/42'\n"

    def test_non_daemon_session_dir_changed_is_quiet(self):
        from xpra.server.subsystem.daemon import DaemonServer
        daemon = DaemonServer()
        daemon.session_dir = "/run/user/1000/xpra/S123"
        daemon.stderr = StringIO()
        daemon.session_dir_changed("/run/user/1000/xpra/42")
        assert daemon.stderr.getvalue() == ""

    def test_daemon_display_name_changed_reports_display(self):
        from xpra.server.subsystem.daemon import DaemonServer

        class NonClosingStringIO(StringIO):
            def close(self):
                pass

        daemon = DaemonServer()
        daemon.daemon = True
        daemon.display_name = "S123"
        daemon.log_filename = "/run/user/1000/xpra/42/log"
        daemon.stdout = NonClosingStringIO()
        daemon.stderr = NonClosingStringIO()
        with patch("xpra.server.subsystem.daemon.get_username_for_uid", return_value="user"), \
                patch("xpra.util.daemon.select_log_file", return_value=daemon.log_filename):
            daemon.display_name_changed(":42")
        assert daemon.stderr.getvalue() == "Actual display used: :42\n"

    def test_setup_pam_session_disabled(self):
        with patch("xpra.server.subsystem.process.POSIX", True), \
                patch("xpra.server.subsystem.process.envbool", return_value=False):
            pam, protected_env = setup_pam_session(":42", "abc", 1000)
        assert pam is None
        assert protected_env == {}

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
        pam_usernames = []
        pam_module = ModuleType("xpra.platform.pam")
        pam_module.pam_session = lambda username: pam_usernames.append(username) or fake_pam
        with patch.dict(sys.modules, {"xpra.platform.pam": pam_module}), \
                patch.dict(os.environ, {}, clear=False), \
                patch("xpra.server.subsystem.process.POSIX", True), \
                patch("xpra.server.subsystem.process.envbool", return_value=True), \
                patch("xpra.server.subsystem.process.get_username_for_uid", return_value="alice"):
            os.environ.pop("PAM_ENV", None)
            pam, protected_env = setup_pam_session(":42", "abc", 1000)
            assert os.environ["PAM_ENV"] == "1"
        assert pam is fake_pam
        assert protected_env == {"PAM_ENV": "1"}
        assert pam_usernames == ["alice"]
        assert fake_pam.env == {
            "XDG_SESSION_TYPE": "x11",
            "XDG_SESSION_DESKTOP": "xpra",
        }
        assert fake_pam.items == {"XDISPLAY": ":42", "XAUTHDATA": "abc"}

    def test_setup_runtime_dir_from_env_options(self):
        with patch("xpra.server.subsystem.process.getuid", return_value=0), \
                patch("xpra.server.subsystem.process.create_runtime_dir",
                      return_value="/tmp/xpra-runtime") as create_runtime_dir:
            xrd, protected_env = setup_runtime_dir(("XDG_RUNTIME_DIR=/tmp/xpra-runtime",), 1000, 1000,
                                                   {"PAM_ENV": "1"})
        create_runtime_dir.assert_called_once_with("/tmp/xpra-runtime", 1000, 1000)
        assert xrd == "/tmp/xpra-runtime"
        assert protected_env == {
            "PAM_ENV": "1",
            "XDG_RUNTIME_DIR": "/tmp/xpra-runtime",
        }

    def test_setup_runtime_dir_filters_unsafe_root_path(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/tmp/fallback-runtime"}, clear=False), \
                patch("xpra.server.subsystem.process.getuid", return_value=0), \
                patch("xpra.server.subsystem.process.create_runtime_dir",
                      return_value="/tmp/fallback-runtime") as create_runtime_dir:
            xrd, protected_env = setup_runtime_dir(("XDG_RUNTIME_DIR=/run/unsafe",), 1000, 1000, {})
        create_runtime_dir.assert_called_once_with("/tmp/fallback-runtime", 1000, 1000)
        assert xrd == "/tmp/fallback-runtime"
        assert protected_env == {"XDG_RUNTIME_DIR": "/tmp/fallback-runtime"}

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
            add_desktop_greeter(opts, "desktop", False)
        assert opts.start == ["xpra desktop-greeter"]

    def test_add_desktop_greeter_preserves_existing_commands(self):
        opts = self.make_greeter_opts()
        opts.start_child.append("xterm")
        with patch("xpra.scripts.server.POSIX", True), \
                patch("xpra.scripts.server.DESKTOP_GREETER", True):
            add_desktop_greeter(opts, "desktop", False)
        assert opts.start == []
        assert opts.start_child == ["xterm"]

    def test_has_child_arg(self):
        opts = self.make_greeter_opts()
        assert has_child_arg(opts) is False
        opts.start_child_on_last_client_exit.append("xterm")
        assert has_child_arg(opts) is True

    def test_sanitize_dbus_env(self):
        with patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "keep-me", "OTHER": "1"}, clear=True):
            sanitize_dbus_env("keep")
            assert os.environ == {"DBUS_SESSION_BUS_ADDRESS": "keep-me", "OTHER": "1"}
            sanitize_dbus_env("yes")
            assert os.environ == {"OTHER": "1"}

    def test_resolve_server_display_name_with_options(self):
        opts = SimpleNamespace(sessions_dir="/sessions", socket_dir="/socket", socket_dirs=())
        with patch("xpra.scripts.server.display_name_check") as display_name_check:
            display_name, display_options = resolve_server_display_name(opts, [":42,DP-1"], "", False, False,
                                                                        False, False, False, False, False)
        assert display_name == ":42"
        assert display_options == "DP-1"
        display_name_check.assert_called_once_with(":42")

    def test_resolve_server_display_name_proxy(self):
        opts = SimpleNamespace(sessions_dir="/sessions", socket_dir="/socket", socket_dirs=())
        dotxpra = SimpleNamespace(sockets=lambda: [("LIVE", ":1000")])
        with patch("xpra.scripts.server.DotXpra", return_value=dotxpra):
            display_name, display_options = resolve_server_display_name(opts, [], "", False, False, False, False,
                                                                        True, False, None)
        assert display_name == ":1001"
        assert display_options == ""

    def test_request_upgrade_display(self):
        with patch("xpra.scripts.server.request_exit", return_value=True) as request_exit, \
                patch("time.sleep") as sleep:
            assert request_upgrade_display(":42", {"socket-path": "/tmp/xpra/42"}) is True
        request_exit.assert_called_once_with("socket:///tmp/xpra/42")
        sleep.assert_called_once_with(1)

    def test_request_upgrade_display_no_session(self):
        with patch("xpra.scripts.server.request_exit") as request_exit:
            assert request_upgrade_display(":42", {}) is False
        request_exit.assert_not_called()

    def test_request_upgrade_display_not_exiting(self):
        with patch("xpra.scripts.server.request_exit", return_value=False) as request_exit, \
                patch("xpra.scripts.server.warn") as warn:
            assert request_upgrade_display(":42", {"socket-path": ""}) is False
        request_exit.assert_called_once_with(":42")
        warn.assert_called_once_with("server for :42 is not exiting")

    def test_setup_xauthority_reuses_session_file(self):
        from xpra.server.subsystem.xvfb import XvfbManager
        session_files = SimpleNamespace(write_session_file=lambda *_args: self.fail("existing xauthority must not be rewritten"))
        xvfb = XvfbManager(SimpleNamespace(subsystems={"session-files": session_files}))
        xvfb.uid = os.getuid()
        xvfb.gid = os.getgid()
        xvfb.username = "test"
        with tempfile.TemporaryDirectory() as session_dir, tempfile.NamedTemporaryFile() as xauth_file:
            with patch.dict(os.environ, {"XPRA_SESSION_DIR": session_dir}, clear=False):
                os.environ.pop("XAUTHORITY", None)
                save_session_file("xauthority", xauth_file.name)
                xauthority = xvfb.setup_xauthority(":42", False)
                assert xauthority == xauth_file.name
                assert os.environ["XAUTHORITY"] == xauth_file.name

    def test_start_server_vfb_noop_for_proxy(self):
        from xpra.server.subsystem.xvfb import XvfbManager
        xvfb = XvfbManager(SimpleNamespace(subsystems={}))
        xvfb.displayfd = "7"
        result = xvfb.start_server_vfb(":100", ":100", None, {}, None, False, True,
                                       False, False, "", lambda *_args: None)
        assert result.xvfb is None
        assert result.xvfb_pid == 0
        assert result.devices == {}
        assert result.display_name == ":100"
        assert result.xvfb_cmd == ()
        assert result.displayfd == 7

    def test_start_server_vfb_invalid_displayfd(self):
        from xpra.server.subsystem.xvfb import XvfbManager
        xvfb = XvfbManager(SimpleNamespace(subsystems={}))
        xvfb.displayfd = "not-an-int"
        stderr = StringIO()
        with patch("sys.stderr", stderr), \
                patch("xpra.server.subsystem.xvfb.POSIX", True):
            result = xvfb.start_server_vfb(":100", ":100", None, {}, None, False, True,
                                           False, False, "", lambda *_args: None)
        assert result.displayfd == 0
        assert "Error: invalid displayfd 'not-an-int':" in stderr.getvalue()

    def test_xvfb_setup_vfb_emits_display_name(self):
        from xpra.server.subsystem.xvfb import XvfbManager
        session_files = SimpleNamespace()
        xvfb = XvfbManager(SimpleNamespace(subsystems={"session-files": session_files}))
        seen = []
        xvfb.connect("display-name", lambda _xvfb, display_name: seen.append(display_name))
        result = xvfb.setup_vfb(":100", False, "", {}, None, False, True, False, False, "",
                                0, None, False, lambda *_args: None)
        assert result.display_name == ":100"
        assert seen == [":100"]

    def test_set_vfb_startup_state(self):
        state_calls = []
        displayfd_calls = []
        state = VFBStartResult(None, 123, {}, ":42", ("Xvfb",), 7)
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
        state = VFBStartResult(None, 123, {}, ":42", ("Xvfb",), 7)
        display = X11DisplayManager.__new__(X11DisplayManager)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XVFB_PID", None)
            X11DisplayManager.set_vfb_startup_state(display, state)
            assert os.environ["XVFB_PID"] == "123"
        assert display.vfb_startup_state is state
        assert display.xvfb is None
        assert display.xvfb_cmd == ("Xvfb",)
        assert display.display_pid == 123

    def test_x11_display_startup_state_checks_vfb(self):
        from xpra.exit_codes import ExitCode
        from xpra.scripts.config import InitExit
        from xpra.x11.subsystem.display import X11DisplayManager
        state = VFBStartResult(object(), 123, {}, ":42", ("Xvfb",), 7)
        display = X11DisplayManager.__new__(X11DisplayManager)
        with patch("xpra.x11.subsystem.display.check_xvfb", return_value=False):
            with self.assertRaises(InitExit) as e:
                X11DisplayManager.set_vfb_startup_state(display, state)
        assert e.exception.status == ExitCode.NO_DISPLAY

    def test_session_files_display_name_changed(self):
        from xpra.server.subsystem.sessionfiles import SessionFilesServer
        daemon_calls = []
        daemon = SimpleNamespace(
            session_dir_changed=lambda session_dir: daemon_calls.append(("session-dir", session_dir)),
            display_name_changed=lambda display_name: daemon_calls.append(("display-name", display_name)),
        )
        session_files = SessionFilesServer(SimpleNamespace(subsystems={"daemon": daemon}))
        session_files.init(SimpleNamespace(uid=os.getuid(), gid=os.getgid()))
        with tempfile.TemporaryDirectory() as sessions_dir:
            session_dir = session_files.setup_session_dir("seamless", sessions_dir, "S123")
            session_files.write_session_file("cmdline", "xpra\n")
            with patch.dict(os.environ, {"XPRA_SESSION_DIR": session_dir}, clear=False):
                session_files.display_name_changed(None, ":42")
                new_session_dir = os.environ["XPRA_SESSION_DIR"]
                assert os.environ["XPRA_SESSION_DIR"] == new_session_dir
            assert new_session_dir == os.path.join(sessions_dir, "42")
            assert session_files.session_dir == new_session_dir
            assert daemon_calls == [("session-dir", new_session_dir), ("display-name", ":42")]
            with open(os.path.join(new_session_dir, "cmdline"), encoding="utf8") as f:
                assert f.read() == "xpra\n"

    def test_make_server_app(self):
        opts = SimpleNamespace(backend="x11")
        attrs = {}
        proxy_module = ModuleType("xpra.platform.proxy_server")
        proxy_module.ProxyServer = lambda: "proxy"
        with patch.dict(sys.modules, {"xpra.platform.proxy_server": proxy_module}):
            app = make_server_app(attrs, opts, 0, "proxy", ":42")
        assert app == "proxy"
        assert attrs["backend"] == "x11"

        attrs = {}
        shadow_calls = []
        shadow_module = ModuleType("xpra.platform.shadow_server")
        shadow_module.ShadowServer = lambda display, attrs: shadow_calls.append((display, attrs)) or "shadow"
        with patch.dict(sys.modules, {"xpra.platform.shadow_server": shadow_module}):
            app = make_server_app(attrs, opts, 0, "shadow", ":42")
        assert app == "shadow"
        assert shadow_calls == [(":42", {"backend": "x11", "multi-window": "True"})]

        attrs = {}
        seamless_calls = []
        seamless_module = ModuleType("xpra.x11.server.seamless")
        seamless_module.SeamlessServer = lambda clobber: seamless_calls.append(clobber) or "seamless"
        with patch.dict(sys.modules, {"xpra.x11.server.seamless": seamless_module}):
            app = make_server_app(attrs, opts, 0, "upgrade", ":42")
        assert app == "seamless"
        assert seamless_calls == [0]

    def test_init_virtual_devices(self):
        calls = []
        pointer = SimpleNamespace(init_virtual_devices=calls.append)
        app = SimpleNamespace(get_subsystem=lambda name: pointer if name == "pointer" else None)
        devices = {"pointer": {"device": "/dev/input/event0"}}
        init_virtual_devices(app, {})
        init_virtual_devices(app, devices)
        assert calls == [devices]

    def test_resolve_x11_display_missing_upgrade(self):
        from xpra.exit_codes import ExitCode
        from xpra.scripts.config import InitExit
        from xpra.server.subsystem.xvfb import XvfbManager
        xvfb = XvfbManager(SimpleNamespace(subsystems={}))
        xvfb.uid = os.getuid()
        xvfb.gid = os.getgid()
        with self.assertRaises(InitExit) as e:
            xvfb.resolve_x11_display(
                "", "/xauth", "", True, None, True, False, False, False, None,
                lambda *_args: None,
            )
        assert e.exception.status == ExitCode.NO_DISPLAY
        assert str(e.exception) == "no displays found to upgrade"

    def test_resolve_x11_display_verified(self):
        from xpra.server.subsystem.xvfb import XvfbManager
        xvfb = XvfbManager(SimpleNamespace(subsystems={}))
        xvfb.uid = os.getuid()
        xvfb.gid = os.getgid()
        progress = []
        with patch("xpra.server.subsystem.xvfb.no_gtk") as no_gtk, \
                patch("xpra.server.subsystem.xvfb.verify_display", return_value=True):
            start_vfb, xauth_data, use_display = xvfb.resolve_x11_display(
                ":42", "/xauth", "abc", True, None, False, False, False, False, None,
                lambda *args: progress.append(args),
            )
        no_gtk.assert_called_once()
        assert start_vfb is False
        assert xauth_data == "abc"
        assert use_display is None
        assert progress == [(40, "connecting to the display"), (40, "connected to the display")]

    def test_resolve_x11_display_readds_xauth(self):
        from xpra.server.subsystem.xvfb import XvfbManager
        xvfb = XvfbManager(SimpleNamespace(subsystems={}))
        xvfb.uid = os.getuid()
        xvfb.gid = os.getgid()
        pam = SimpleNamespace(items=[])
        pam.set_items = pam.items.append
        with patch("xpra.server.subsystem.xvfb.no_gtk"), \
                patch("xpra.server.subsystem.xvfb.verify_display", side_effect=(False, True)), \
                patch("xpra.server.subsystem.xvfb.stat_display_socket", return_value={"uid": os.getuid()}), \
                patch("xpra.server.subsystem.xvfb.get_hex_uuid", return_value="uuid"), \
                patch("xpra.x11.vfb_util.xauth_add") as xauth_add:
            start_vfb, xauth_data, use_display = xvfb.resolve_x11_display(
                ":42", "/xauth", "", True, None, False, False, False, False, pam,
                lambda *_args: None,
            )
        assert start_vfb is False
        assert xauth_data == "uuid"
        assert use_display is None
        assert pam.items == [{"XAUTHDATA": "uuid"}]
        xauth_add.assert_called_once_with("/xauth", ":42", "uuid", os.getuid(), os.getgid())


def main():
    unittest.main()


if __name__ == '__main__':
    main()
