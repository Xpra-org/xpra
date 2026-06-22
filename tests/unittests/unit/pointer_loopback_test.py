#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the client `PointerClient` subsystem to the
server `PointerManager` subsystem (+ `PointerConnection` source).

Pointer position (client -> server): the client reports a mouse position, the
server decodes it and records it on the source. The actual input device and the
mouse-common processing are mocked out (they drive real X11/uinput devices). The
client queues pointer packets for the network thread rather than calling send()
directly, so the harness drains them via have_more() (see loopback_util).
"""

import unittest
from unittest.mock import patch

from xpra.util.objects import AdHocStruct

from unit.loopback_util import LoopbackTest


def _client_opts():
    return AdHocStruct()


def _server_opts():
    opts = AdHocStruct()
    opts.input_devices = "auto"
    return opts


class PointerLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.pointer import PointerClient
        from xpra.server.subsystem.pointer import PointerManager
        from xpra.server.source.pointer import PointerConnection
        # setup() probes the platform pointer device:
        with patch.object(PointerManager, "setup", lambda self: None):
            return self.connect(PointerClient, PointerManager, PointerConnection,
                                client_opts=_client_opts(), server_opts=_server_opts(), caps={})

    def test_mouse_position_reaches_source(self):
        client, server, source = self._connect()
        # the real implementations drive the input device / drag heuristics:
        server.process_mouse_common = lambda *a, **kw: False
        server._maybe_record_drag_scroll = lambda *a, **kw: None
        # the ui_driver gate is checked against the source uuid:
        server.server.ui_driver = None
        source.uuid = "test-client"

        client.send_mouse_position(-1, 1, (100, 200))

        # the pointer packet crossed the wire:
        self.assertTrue(any(p[0] in ("pointer-position", "pointer-motion") for p in self.c2s),
                        "no pointer packet was sent: %s" % (self.c2s,))
        # and the server decoded it and recorded the position on the source:
        self.assertEqual(source.mouse_last_position, (100, 200))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
