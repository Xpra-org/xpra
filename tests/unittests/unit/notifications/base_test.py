#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.notification import common
from xpra.notification.base import NotifierBase


class TestNotifier(NotifierBase):

    def show_notify(self, *args) -> None:
        """ we only care about `dbus_check` here """


class NotifierBaseTest(unittest.TestCase):

    @staticmethod
    def make_notifier(service_name: str) -> TestNotifier:
        notifier = TestNotifier()
        notifier.dbus_id = "unix:path=/tmp/dbus-test"
        with patch.object(common, "get_notification_service_name", return_value=service_name):
            notifier.is_proxy_service()
        return notifier

    def test_same_dbus_id(self):
        notifier = self.make_notifier("some-notification-daemon")
        self.assertTrue(notifier.dbus_check(""))
        self.assertTrue(notifier.dbus_check("unix:path=/tmp/dbus-other"))
        # the notification comes from the bus we would show it on:
        self.assertFalse(notifier.dbus_check("unix:path=/tmp/dbus-test"))

    def test_proxy_service(self):
        # the notification service is one of our forwarders:
        # showing anything would send it straight back to us
        notifier = self.make_notifier(common.PROXY_NAME)
        self.assertFalse(notifier.dbus_check(""))
        self.assertFalse(notifier.dbus_check("unix:path=/tmp/dbus-other"))

    def test_unknown_service(self):
        # we could not find out: don't get in the way
        notifier = self.make_notifier("")
        self.assertTrue(notifier.dbus_check("unix:path=/tmp/dbus-other"))

    def test_icon_string(self):
        notifier = TestNotifier()
        self.assertEqual(notifier.get_icon_string(1, "mail-unread", None, {}), "mail-unread")
        self.assertEqual(notifier.get_icon_string(1, "org.gnome.Evolution", None, {}), "org.gnome.Evolution")
        # anything the daemon would load as a file instead of looking it up in the theme:
        for app_icon in (
            "/etc/passwd", "file:///home/user/Downloads/x.png", "../x.png", "~/x.png",
            "resource:///x.png", "a b", "x" * 200,
        ):
            self.assertEqual(notifier.get_icon_string(1, app_icon, None, {}), "", f"{app_icon!r} should be rejected")


def main():
    unittest.main()


if __name__ == "__main__":
    main()
