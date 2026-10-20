#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.net.common import Packet
from xpra.client.subsystem import notification
from xpra.client.subsystem.notification import NotificationClient
from xpra.notification.common import MAX_SUMMARY, MAX_BODY, MAX_ACTIONS, MAX_ACTION_KEY, MAX_ACTION_LABEL
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
        self.closed: list = []
        self.client.send = lambda *args: self.closed.append(args)
        self.notifications.server = True
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

    def test_lengths_are_limited(self):
        shown = self.show(summary="s" * 10000, body="b" * 100000)
        self.assertEqual(len(shown["summary"]), MAX_SUMMARY)
        self.assertEqual(len(shown["body"]), MAX_BODY)
        self.assertEqual(shown["body"][-1], "\u2026")

    def test_actions_are_limited(self):
        actions = []
        for i in range(100):
            actions += [str(i), f"label{i}"]
        shown = self.show(actions=actions)
        self.assertEqual(shown["actions"], actions[:MAX_ACTIONS * 2])
        # keys cannot be truncated: skip those which are too long
        shown = self.show(nid=2, actions=("k" * (MAX_ACTION_KEY + 1), "too long", "ok", "l" * 1000, "odd"))
        self.assertEqual(shown["actions"][0], "ok")
        self.assertEqual(len(shown["actions"][1]), MAX_ACTION_LABEL)
        self.assertEqual(len(shown["actions"]), 2)

    def test_urgency(self):
        self.assertEqual(self.show(nid=1, hints={"urgency": 2})["hints"]["urgency"], 2)
        self.assertEqual(self.show(nid=2, hints={"urgency": 99})["hints"]["urgency"], 2)
        self.assertEqual(self.show(nid=3, hints={"urgency": -5})["hints"]["urgency"], 0)
        self.assertNotIn("urgency", self.show(nid=4, hints={"urgency": "high"})["hints"])
        with patch.object(notification, "MAX_URGENCY", 1):
            self.assertEqual(self.show(nid=5, hints={"urgency": 2})["hints"]["urgency"], 1)

    def test_rate_limit(self):
        with patch.object(notification, "RATE_LIMIT", 3):
            for nid in range(1, 4):
                self.assertTrue(self.show(nid=nid))
            # replacing a notification already shown does not count:
            self.assertTrue(self.show(nid=2, replaces_nid=2))
            # but a new one is dropped, and the server is told it is closed:
            self.assertFalse(self.show(nid=4))
            self.assertEqual(self.closed, [("notification-close", 4, 4, "too many notifications")])
            # make room by closing one:
            self.notifications.notification_closed(1, 2)
            self.assertFalse(self.show(nid=5), "closing a notification does not reset the rate")
            self.notifications.show_times.clear()
            self.assertTrue(self.show(nid=5))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
