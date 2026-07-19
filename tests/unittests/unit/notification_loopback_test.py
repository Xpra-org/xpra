#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the client `NotificationClient` subsystem to
the server `NotificationForwarder` subsystem (+ `NotificationConnection` source).

Exercises both directions:
 - client -> server: notification-action / notification-close
 - server -> client: notification-show (via the source's notify())
"""

import unittest
from time import monotonic
from unittest.mock import MagicMock

from xpra.util.objects import AdHocStruct
from xpra.net.packet_type import NOTIFICATION_SHOW

from unit.loopback_util import LoopbackTest


def _client_opts():
    opts = AdHocStruct()
    # keep client notifications disabled so load() does not build a real notifier:
    opts.notifications = False
    return opts


def _server_opts():
    opts = AdHocStruct()
    opts.notifications = True
    return opts


class NotificationLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.notification import NotificationClient
        from xpra.server.subsystem.notification import NotificationForwarder
        from xpra.server.source.notification import NotificationConnection
        return self.connect(NotificationClient, NotificationForwarder, NotificationConnection,
                            client_opts=_client_opts(), server_opts=_server_opts(),
                            caps={"notification": True, "notifications": {"enabled": True}})

    def test_client_action_reaches_server(self):
        client, _server, source = self._connect()
        self.assertTrue(client.server)
        events = []
        source.connect("user-event", lambda *a: events.append(a))

        client.notification_action(7, "default-action")

        self.assertIn(("notification-action", 7, "default-action"),
                      [tuple(p) for p in self.c2s])
        # the server raised a user-event for the action:
        self.assertTrue(events, "server did not emit user-event")

    def test_client_close_reaches_server(self):
        client, _server, _source = self._connect()
        client.notification_closed(9, 2, "dismissed")
        self.assertIn(("notification-close", 9, 2, "dismissed"),
                      [tuple(p) for p in self.c2s])

    def test_server_show_reaches_client(self):
        client, _server, source = self._connect()
        # stand in for the client-side notifier / UI:
        client.enabled = True
        client.notifier = MagicMock()
        # `_ui_event` is called on the owning client, which the harness provides
        # the source needs to consider the client ready:
        source.send_notifications = True
        source.hello_sent = monotonic()

        source.notify("", 11, "App", 0, "", "Summary", "Body", (), {}, 10 * 1000, None)

        self.assertTrue(any(p[0] == NOTIFICATION_SHOW for p in self.s2c),
                        "server did not send a notification: %s" % (self.s2c,))
        client.notifier.show_notify.assert_called()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
