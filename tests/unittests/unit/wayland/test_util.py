#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Helpers for tests which need a native Wayland client display."""

import importlib.util
import os
import shutil
import tempfile
import time
import unittest

from xpra.exit_codes import exit_str
from xpra.util.io import pollwait
from unit.server_test_util import ServerTestUtil


WESTON_TIMEOUT = 10
CLIENT_TIMEOUT = 20


class WestonTestUtil(ServerTestUtil):
    """Run Xpra clients against a private Weston headless compositor."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("weston"):
            raise unittest.SkipTest("Weston is not installed")
        if not shutil.which("weston-terminal"):
            raise unittest.SkipTest("weston-terminal is not installed")
        if importlib.util.find_spec("xpra.wayland.server.compositor") is None:
            raise unittest.SkipTest("the Wayland server backend is not built")
        ServerTestUtil.setUpClass()

    def setUp(self):
        ServerTestUtil.setUp(self)
        self.weston = None
        self.weston_runtime = tempfile.TemporaryDirectory(
            prefix="xpra-weston-")
        os.chmod(self.weston_runtime.name, 0o700)
        self.weston_socket = "wayland-xpra-test"
        env = self.get_run_env()
        env.update({
            "XDG_RUNTIME_DIR": self.weston_runtime.name,
            "WAYLAND_DISPLAY": self.weston_socket,
        })
        env.pop("DISPLAY", None)
        self.weston = self.run_command([
            "weston", "--backend=headless-backend.so",
            f"--socket={self.weston_socket}", "--idle-time=0",
        ], env=env)
        self.wait_for_weston()

    def tearDown(self):
        self.stop_weston()
        if self.weston_runtime:
            self.weston_runtime.cleanup()
            self.weston_runtime = None
        ServerTestUtil.tearDown(self)

    def wait_for_weston(self) -> None:
        socket_path = os.path.join(self.weston_runtime.name,
                                   self.weston_socket)
        deadline = time.monotonic() + WESTON_TIMEOUT
        while time.monotonic() < deadline:
            if os.path.exists(socket_path):
                return
            if self.weston.poll() is not None:
                self.show_proc_error(self.weston, "Weston failed to start")
            time.sleep(0.1)
        self.show_proc_error(self.weston,
                             f"Weston did not create {socket_path}")

    def stop_weston(self) -> None:
        weston = self.weston
        self.weston = None
        self.terminate_process(weston)

    @staticmethod
    def terminate_process(proc) -> None:
        if proc and proc.poll() is None:
            proc.terminate()
            if pollwait(proc, CLIENT_TIMEOUT) is None:
                proc.kill()
                pollwait(proc, CLIENT_TIMEOUT)

    def wayland_client_env(self) -> dict[str, str]:
        env = self.get_run_env()
        env.update({
            "GDK_BACKEND": "wayland",
            "XDG_RUNTIME_DIR": self.weston_runtime.name,
            "WAYLAND_DISPLAY": self.weston_socket,
        })
        env.pop("DISPLAY", None)
        return env

    def run_wayland_client(self, display: str):
        return self.run_xpra([
            "attach", display,
            "--clipboard=no", "--notification=no", "--opengl=no",
        ], env=self.wayland_client_env())

    def assert_running(self, proc, description: str) -> None:
        r = pollwait(proc, 1)
        if r is not None:
            self.show_proc_error(proc,
                                 f"{description} exited with {exit_str(r)}")

    def wait_for_exit(self, proc, description: str) -> None:
        if pollwait(proc, CLIENT_TIMEOUT) is None:
            self.show_proc_error(proc, f"{description} did not exit")

    def start_wayland_server(self):
        before = set(self.displays())
        runtime = tempfile.TemporaryDirectory(prefix="xpra-wayland-server-")
        os.chmod(runtime.name, 0o700)
        env = self.get_run_env()
        env["XDG_RUNTIME_DIR"] = runtime.name
        env.pop("DISPLAY", None)
        server = self.run_xpra([
            "seamless", "--backend=wayland", "--no-daemon",
            "--start=weston-terminal",
            "--mdns=no", "--printing=no", "--webcam=no", "--audio=no",
            "--start-new-commands=no",
        ], env=env)
        server.runtime = runtime
        deadline = time.monotonic() + CLIENT_TIMEOUT
        display = ""
        while time.monotonic() < deadline:
            if server.poll() is not None:
                runtime.cleanup()
                self.show_proc_error(server, "Wayland server failed to start")
            new_displays = set(self.displays()) - before
            candidates = sorted(x for x in new_displays
                                if x.startswith("wayland-"))
            if candidates:
                display = candidates[0]
                break
            time.sleep(0.25)
        if not display:
            self.terminate_process(server)
            runtime.cleanup()
            self.show_proc_error(server,
                                 "Wayland server did not create a session "
                                 "socket")
        server.display = display
        version = self.run_xpra(["version", display])
        if pollwait(version, CLIENT_TIMEOUT) != 0:
            self.show_proc_error(version,
                                 f"version check failed for {display}")
        return server

    def stop_wayland_server(self, server) -> None:
        try:
            if server.poll() is None:
                self.stop_server(server, "stop", server.display)
                self.wait_for_exit(server, "Wayland server")
        finally:
            self.terminate_process(server)
            runtime = getattr(server, "runtime", None)
            if runtime:
                runtime.cleanup()
                server.runtime = None

    def wait_for_server_info(self, display: str, key: str,
                             value: str) -> dict[str, str]:
        deadline = time.monotonic() + CLIENT_TIMEOUT
        info: dict[str, str] = {}
        while time.monotonic() < deadline:
            info = self.get_server_info(display)
            if info.get(key) == value:
                return info
            time.sleep(0.25)
        raise AssertionError(f"server {display} never reported "
                             f"{key}={value!r}: "
                             f"{info}")
