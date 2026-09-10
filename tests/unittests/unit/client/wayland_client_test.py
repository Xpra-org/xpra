#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import OSX, POSIX
from xpra.os_util import get_hex_uuid
from unit.wayland.test_util import WestonTestUtil


@unittest.skipUnless(POSIX and not OSX, "native Wayland clients require Linux")
class WaylandClientTest(WestonTestUtil):

    def test_client_attaches_to_x11_server(self):
        display = self.find_free_display()
        server = self.check_fast_start_server(display, "--windows=yes",
                                              "--start=xterm")
        client = None
        try:
            client = self.run_wayland_client(display)
            self.assert_running(client, "Wayland client")
            self.check_stop_server(server, "stop", display)
            self.wait_for_exit(client,
                               "Wayland client after X11 server shutdown")
        finally:
            if client and client.poll() is None:
                client.terminate()
            if server.poll() is None:
                server.terminate()

    def test_client_and_wayland_server(self):
        server = self.start_wayland_server()
        client = None
        try:
            info = self.wait_for_server_info(server.display, "windows.count",
                                             "1")
            self.assertEqual(info.get("windows.1.app-id"),
                             "org.freedesktop.weston.wayland-terminal")
            self.assertEqual(info.get("windows.1.title"), "Wayland Terminal")
            client = self.run_wayland_client(server.display)
            self.assert_running(client, "Wayland client")
            self.stop_wayland_server(server)
            self.wait_for_exit(client,
                               "Wayland client after Wayland server shutdown")
        finally:
            if client and client.poll() is None:
                client.terminate()
            if server.poll() is None:
                self.stop_wayland_server(server)

    def test_wayland_clipboard(self):
        server = self.start_wayland_server()
        client = None
        try:
            client = self.run_wayland_client(server.display)
            self.assert_running(client, "Wayland client")
            server_env = self.wayland_server_env(server)
            client_value = get_hex_uuid()
            self.set_wayland_clipboard(self.wayland_client_env(), client_value)
            self.wait_for_wayland_clipboard(server_env, client_value)
            server_value = get_hex_uuid()
            self.set_wayland_clipboard(server_env, server_value)
            self.wait_for_wayland_clipboard(self.wayland_client_env(),
                                            server_value)
        finally:
            if client and client.poll() is None:
                client.terminate()
            if server.poll() is None:
                self.stop_wayland_server(server)

    def test_wayland_clipboard_mime_type(self):
        server = self.start_wayland_server()
        client = None
        try:
            client = self.run_wayland_client(server.display)
            self.assert_running(client, "Wayland client")
            server_env = self.wayland_server_env(server)
            mime_type = "text/plain;charset=utf-8"
            client_value = ("Xpra clipboard:\n"
                            "\u20ac \u0e20\u0e32\u0e29\u0e32"
                            "\u0e44\u0e17\u0e22 "
                            "\u65e5\u672c\u8a9e")
            self.set_wayland_clipboard(self.wayland_client_env(), client_value)
            self.wait_for_wayland_clipboard(server_env, client_value)
            self.wait_for_wayland_clipboard_type(server_env, mime_type)
            server_value = ("Wayland server:\n"
                            "\u043a\u0438\u0440\u0438\u043b\u043b"
                            "\u0438\u0446\u0430 \U0001f30d")
            self.set_wayland_clipboard(server_env, server_value)
            self.wait_for_wayland_clipboard(self.wayland_client_env(),
                                            server_value)
            self.wait_for_wayland_clipboard_type(self.wayland_client_env(),
                                                 mime_type)
        finally:
            if client and client.poll() is None:
                client.terminate()
            if server.poll() is None:
                self.stop_wayland_server(server)

    def check_wayland_clipboard_direction(self, direction: str) -> None:
        server = self.start_wayland_server()
        try:
            server_env = self.wayland_server_env(server)
            client = self.run_wayland_client(
                server.display, f"--clipboard-direction={direction}")
            try:
                self.assert_running(client, f"Wayland {direction} client")
                client_value = get_hex_uuid()
                self.set_wayland_clipboard(self.wayland_client_env(),
                                           client_value)
                if direction == "to-server":
                    self.wait_for_wayland_clipboard(server_env, client_value)
                else:
                    self.assert_wayland_clipboard_not_value(server_env,
                                                            client_value)
                server_value = get_hex_uuid()
                self.set_wayland_clipboard(server_env, server_value)
                if direction == "to-client":
                    self.wait_for_wayland_clipboard(self.wayland_client_env(),
                                                    server_value)
                else:
                    self.assert_wayland_clipboard_not_value(
                        self.wayland_client_env(), server_value)
            finally:
                self.terminate_process(client)
        finally:
            if server.poll() is None:
                self.stop_wayland_server(server)

    def test_wayland_clipboard_to_server(self):
        self.check_wayland_clipboard_direction("to-server")

    def test_wayland_clipboard_to_client(self):
        self.check_wayland_clipboard_direction("to-client")

    def test_wayland_clipboard_disabled(self):
        self.check_wayland_clipboard_direction("disabled")

    def test_client_exits_when_weston_stops(self):
        display = self.find_free_display()
        server = self.check_fast_start_server(display, "--windows=yes",
                                              "--start=xterm")
        client = None
        try:
            client = self.run_wayland_client(display)
            self.assert_running(client, "Wayland client")
            self.stop_weston()
            self.wait_for_exit(client, "Wayland client after Weston shutdown")
        finally:
            if client and client.poll() is None:
                client.terminate()
            if server.poll() is None:
                self.check_stop_server(server, "stop", display)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
