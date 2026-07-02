#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the server `CursorManager` subsystem (+
`CursorsConnection` source) to the client `CursorClient` subsystem.

Server -> client: the source builds a cursor-data packet (encoding selection /
compression) which the client decodes and applies. A raw cursor is used so the
payload survives the harness's direct (uncompressed) transport; the network
compression layer is stubbed with identity for the same reason.
"""

import unittest
from unittest.mock import MagicMock

from xpra.util.objects import AdHocStruct
from xpra.net.packet_type import CURSOR_DATA

from unit.loopback_util import LoopbackTest


def _opts():
    opts = AdHocStruct()
    opts.cursors = True
    return opts


class CursorLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.cursor import CursorClient
        from xpra.server.subsystem.cursor import CursorManager
        from xpra.server.source.cursor import CursorsConnection
        return self.connect(CursorClient, CursorManager, CursorsConnection,
                            client_opts=_opts(), server_opts=_opts(),
                            caps={"cursor": True})

    def test_server_cursor_reaches_client(self):
        client, _server, source = self._connect()
        # client-side window plumbing (provided by the window subsystem in production):
        client.enabled = True
        client._id_to_window = {}
        client.set_windows_cursor = MagicMock()
        # server source ready to send a non-legacy cursor-data packet:
        source.send_cursors = True
        source.cursor_backwards_compatible = False
        # no network compression layer in the loopback transport:
        source.compressed_wrapper = lambda _kind, data, **_kw: data

        pixels = b"\x00" * 256  # >=256 so the "raw" encoding path is used
        serial = 0xABCD
        # cursor_data layout: [x, y, w, h, xhot, yhot, serial, pixels, name]
        cursor_data = [0, 0, 16, 16, 1, 2, serial, pixels, "test-cursor"]
        source.do_send_cursor(50, cursor_data, (24, (16, 16)))

        # the cursor-data packet crossed the wire:
        self.assertTrue(any(p[0] == CURSOR_DATA for p in self.s2c),
                        "server did not send cursor data: %s" % (self.s2c,))
        # and the client decoded it and applied it to its windows:
        client.set_windows_cursor.assert_called_once()
        applied = client.set_windows_cursor.call_args.args[1]
        # applied layout: ("raw", 0, 0, w, h, xhot, yhot, serial, pixels, name)
        self.assertEqual(applied[7], serial)
        self.assertEqual(applied[8], pixels)
        self.assertEqual(applied[9], "test-cursor")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
