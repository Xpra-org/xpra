#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.net.common import Packet
from xpra.client.subsystem.notification import NotificationClient
from unit.client.subsystem.notification_icons_test import FakeClient, FakeEncodings


class RecordingNotifier:
    def __init__(self):
        self.shown: list[dict] = []

    def show_notify(self, dbus_id, tray, nid, app_name, replaces_nid, app_icon,
                    summary, body, actions, hints, expire_timeout, icon):
        self.shown.append({
            "nid": nid, "app_name": app_name, "replaces_nid": replaces_nid, "app_icon": app_icon,
            "summary": summary, "body": body, "actions": actions, "hints": hints,
            "expire_timeout": expire_timeout,
        })

    def close_notify(self, nid):
        """ not tested here """

    def cleanup(self):
        """ nothing to clean up """


class NotificationSanitizeTest(unittest.TestCase):
    """
    the strings the server sends us are handed to the notification daemon:
    they must not be able to spoof the application they come from
    """

    def setUp(self):
        self.client = FakeClient()
        self.notifications = NotificationClient(client=self.client)
        self.notifications.enabled = True
        self.notifier = RecordingNotifier()
        self.notifications.notifier = self.notifier
        self.client.subsystems = {
            "encoding": FakeEncodings(),
            "notification": self.notifications,
        }

    def show(self, nid=1, app_name="app", summary="summary", body="body",
             actions=("0", "Hello"), hints=None, expire_timeout=10 * 1000, replaces_nid=0) -> dict:
        count = len(self.notifier.shown)
        self.notifications._process_show(
            Packet("notification-show", "", nid, app_name, replaces_nid, "", summary, body, expire_timeout,
                   (), actions, hints or {})
        )
        if len(self.notifier.shown) == count:
            return {}
        return self.notifier.shown[-1]

    def test_app_name_and_summary_are_single_line(self):
        shown = self.show(app_name="Mail‮\n(local)", summary="line1\nline2\x00⁦")
        self.assertEqual(shown["app_name"], "Mail (local)")
        self.assertEqual(shown["summary"], "line1 line2")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
