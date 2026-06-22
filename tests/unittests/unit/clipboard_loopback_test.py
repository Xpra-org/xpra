#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the server clipboard subsystem
(`ClipboardManager`, + `ClipboardConnection` source) to the client
`ClipboardClient` subsystem.

Clipboard status (server -> client): the source sends a clipboard-status packet,
the client decodes it and toggles its clipboard_enabled flag. Only the status
path is exercised - the actual clipboard data transfer needs a GTK clipboard
helper, which is out of scope. `BACKWARDS_COMPATIBLE` is forced off so the modern
`clipboard-status` packet name is used on both sides (the client's status branch
matches on that literal name).
"""

import unittest
from time import monotonic
from unittest.mock import patch

from xpra.util.objects import AdHocStruct

from unit.loopback_util import LoopbackTest


def _client_opts():
    opts = AdHocStruct()
    opts.clipboard = "yes"
    opts.clipboard_direction = "both"
    opts.remote_clipboard = "CLIPBOARD"
    opts.local_clipboard = "CLIPBOARD"
    return opts


def _server_opts():
    opts = AdHocStruct()
    opts.clipboard = "yes"
    opts.clipboard_direction = "both"
    opts.clipboard_filter_file = ""
    return opts


class ClipboardLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem import clipboard as client_clipboard
        from xpra.server.source import clipboard as source_clipboard
        from xpra.client.subsystem.clipboard import ClipboardClient
        from xpra.server.subsystem.clipboard import ClipboardManager
        from xpra.server.source.clipboard import ClipboardConnection
        # force the modern packet name so the client status branch matches; these
        # must stay patched through the test body (the send happens there), so use
        # start()/addCleanup rather than a `with` block scoped to connect():
        for target in (client_clipboard, source_clipboard):
            p = patch.object(target, "BACKWARDS_COMPATIBLE", False)
            p.start()
            self.addCleanup(p.stop)
        # client load() would build a real GTK clipboard helper:
        with patch.object(ClipboardClient, "load", lambda self: None):
            return self.connect(ClipboardClient, ClipboardManager, ClipboardConnection,
                                client_opts=_client_opts(), server_opts=_server_opts(), caps={})

    def test_server_status_toggles_client(self):
        client, _server, source = self._connect()
        # client starts disabled so the incoming status flips it (and emits):
        client.clipboard_enabled = False
        # server source ready to send a status update:
        source.clipboard_enabled = True
        source.hello_sent = monotonic()

        source.send_clipboard_enabled("test reason")

        # a clipboard-status packet crossed the wire:
        self.assertTrue(any(p[0] in ("clipboard-status", "set-clipboard-enabled") for p in self.s2c),
                        "server did not send clipboard status: %s" % (self.s2c,))
        # and the client decoded it and toggled its flag:
        self.assertTrue(client.clipboard_enabled)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
