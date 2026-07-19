#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the client `PowerEventClient` subsystem to the
server `SuspendServer` subsystem.

Power events (client -> server): the client forwards suspend/resume events, the
server decodes them and re-emits them as signals on the per-client source.
There is no dedicated power/suspend source, so the harness uses the generic
StubClientConnection.
"""

import unittest

from xpra.util.objects import AdHocStruct
from xpra.server.source.stub import StubClientConnection

from unit.loopback_util import LoopbackTest


def _client_opts():
    return AdHocStruct()


def _server_opts():
    return AdHocStruct()


class PowerLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.power import PowerEventClient
        from xpra.server.subsystem.suspend import SuspendServer
        return self.connect(PowerEventClient, SuspendServer, StubClientConnection,
                            client_opts=_client_opts(), server_opts=_server_opts(), caps={})

    def test_suspend_and_resume_reach_server(self):
        client, _server, source = self._connect()
        # the BACKWARDS_COMPATIBLE branch of suspend()/resume() reads `_id_to_window`
        # from the `window` subsystem, which is not registered here, so it sends no wids
        events = []
        source.connect("suspend", lambda *a: events.append("suspend"))
        source.connect("resume", lambda *a: events.append("resume"))

        client.suspend()
        client.resume()

        # both events crossed the wire:
        self.assertTrue(any(p[0] == "suspend" for p in self.c2s),
                        "no suspend packet was sent: %s" % (self.c2s,))
        self.assertTrue(any(p[0] == "resume" for p in self.c2s),
                        "no resume packet was sent: %s" % (self.c2s,))
        # and the server decoded them and re-emitted them on the source:
        self.assertEqual(events, ["suspend", "resume"])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
