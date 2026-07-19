#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the server window subsystem (`WindowServer`,
+ `WindowsConnection` source) to the client `WindowBell` subsystem.

Bell (server -> client): the source emits a window-bell packet which the client
decodes and forwards to its `window_bell` UI hook.

The window-bell path is used (rather than map/close/focus) because the server's
window map/close/unmap handlers are stubs - the real window logic lives in the
window models, which are out of scope for a subsystem loopback test.
"""

import unittest
from time import monotonic
from unittest.mock import patch, MagicMock

from xpra.util.objects import AdHocStruct
from xpra.net.packet_type import WINDOW_BELL

from unit.loopback_util import LoopbackTest


def _client_opts():
    opts = AdHocStruct()
    opts.bell = True
    return opts


def _server_opts():
    opts = AdHocStruct()
    opts.min_size = "0x0"
    opts.max_size = "0x0"
    return opts


class WindowBellLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.window.bell import WindowBell
        from xpra.server.subsystem.window import WindowServer
        from xpra.server.source.window import WindowsConnection
        # `WindowBell` is a mixin fused into `WindowClient`, which is what declares
        # its attributes (the mixins keep `__slots__ = ()` so that they can be
        # combined); testing it on its own means declaring them here instead:
        bell_class = type("WindowBellSubsystem", (WindowBell,), {
            "__slots__": ("bell_enabled", "client_supports_bell", "server_bell"),
        })
        # setup() loads existing windows and wires server signal callbacks;
        # the source get_info() touches a packet_queue set up by other bases:
        with patch.object(WindowServer, "setup", lambda self: None), \
             patch.object(WindowsConnection, "get_info", lambda self: {}):
            return self.connect(bell_class, WindowServer, WindowsConnection,
                                client_opts=_client_opts(), server_opts=_server_opts(),
                                caps={"bell": True})

    def test_server_bell_reaches_client(self):
        client, _server, source = self._connect()
        # client-side bell plumbing (provided by the window subsystem in production):
        client.bell_enabled = True
        client.get_window = lambda wid: None
        # the UI hook lives on the owning client (stood-in by the test harness):
        client.client.window_bell = MagicMock()
        # server source ready to send a bell:
        source.window_bell = True
        source.suspended = False
        source.hello_sent = monotonic()

        source.bell(1, 0, 100, 440, 200, 0, 7, "test-bell")

        # the bell packet crossed the wire:
        self.assertTrue(any(p[0] == WINDOW_BELL for p in self.s2c),
                        "server did not send a bell: %s" % (self.s2c,))
        # and the client decoded it and forwarded it to its UI hook:
        client.client.window_bell.assert_called_once()
        args = client.client.window_bell.call_args.args
        # window_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name)
        self.assertEqual(args[2], 100)            # percent
        self.assertEqual(args[3], 440)            # pitch
        self.assertEqual(args[4], 200)            # duration
        self.assertEqual(args[7], "test-bell")    # name


def main():
    unittest.main()


if __name__ == "__main__":
    main()
