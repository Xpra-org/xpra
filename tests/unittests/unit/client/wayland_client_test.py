#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import OSX, POSIX
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
