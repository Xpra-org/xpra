#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.client.mixins.notifications import NotificationClient


class NotificationSanitizationTest(unittest.TestCase):

    def make_client(self):
        client = NotificationClient()
        client.notifications_enabled = True
        client.client_supports_notifications = True
        client.notifier = Mock()
        client._ui_event = Mock()
        client.idle_add = lambda callback: callback()
        return client

    def test_remote_notification(self):
        for app_icon in ("mail-unread", b"mail-unread"):
            with self.subTest(app_icon=app_icon):
                client = self.make_client()
                body = b'<b>bold</b> <a href="file:///tmp/x">link</a><img src="/tmp/x">'
                client._process_notify_show([
                    "notify_show", "", 1, "test", 0, app_icon, b"title", body, 1000,
                ])
                args = client.notifier.show_notify.call_args[0]
                self.assertEqual(args[5], "mail-unread")
                self.assertEqual(args[6], "title")
                self.assertEqual(args[7], "<b>bold</b> link")

    def test_local_notification(self):
        client = self.make_client()
        with patch("xpra.client.mixins.notifications.get_icon_filename", return_value=""):
            client.do_notify(1, "Disconnected", '<b>reason</b><img src="/tmp/x"><a href="file:///tmp/x">text</a>')
        args = client.notifier.show_notify.call_args[0]
        self.assertEqual(args[6], "Disconnected")
        self.assertEqual(args[7], "<b>reason</b>text")


if __name__ == '__main__':
    unittest.main()
