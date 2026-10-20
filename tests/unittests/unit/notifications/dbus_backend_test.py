#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from dbus.exceptions import DBusException

from xpra.notification.dbus_backend import DBUSNotifier


class DBUSBackendTest(unittest.TestCase):

    def test_replaces_notification_id(self):
        notifier = object.__new__(DBUSNotifier)
        notifier.app_name_format = "%s"
        notifier.actual_notification_id = {7: 42}
        notifier.dbusnotify = Mock()
        notifier.get_icon_string = Mock(return_value="")
        notifier.to_dbus_hints = Mock(return_value={})

        def notify(replaces_nid: int) -> int:
            notifier.dbus_notify("", None, 8, "app", replaces_nid, "",
                                 "summary", "body", (), {}, 1000, None)
            return notifier.dbusnotify.Notify.call_args.args[1]

        self.assertEqual(notify(7), 42)
        self.assertEqual(notify(8), 0)
        self.assertEqual(notify(0), 0)

    @staticmethod
    def make_notifier() -> tuple[DBUSNotifier, list]:
        closed = []
        notifier = object.__new__(DBUSNotifier)
        notifier.temp_files = {}
        notifier.closed_cb = lambda *args: closed.append(args)
        notifier.dbus_check = lambda dbus_id: True
        notifier.dbusnotify = Mock()
        notifier.last_notification = ()
        return notifier, closed

    def show(self, notifier: DBUSNotifier, nid=1) -> None:
        notifier.show_notify("", None, nid, "app", 0, "", "summary", "body", (), {}, 1000, None)

    def test_notify_exception_closes(self):
        notifier, closed = self.make_notifier()
        notifier.dbus_notify = Mock(side_effect=TypeError("invalid argument"))
        self.show(notifier)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0][:2], (1, 4))

    def test_notify_error_closes(self):
        notifier, closed = self.make_notifier()
        notifier.dbus_notify = Mock()
        self.show(notifier)
        notifier.NotifyError(1, DBusException("no", name="org.freedesktop.DBus.Error.InvalidArgs"))
        self.assertEqual([c[:2] for c in closed], [(1, 4)])

    def test_notify_error_retries_once(self):
        notifier, closed = self.make_notifier()
        notifier.dbus_notify = Mock()
        notifier.setup_dbusnotify = Mock()
        self.show(notifier)
        unknown = DBusException("gone", name="org.freedesktop.DBus.Error.ServiceUnknown")
        notifier.NotifyError(1, unknown)
        # we retried, and the retry may still succeed:
        self.assertEqual(notifier.dbus_notify.call_count, 2)
        self.assertEqual(closed, [])
        # the retry failed too:
        notifier.NotifyError(1, unknown)
        self.assertEqual(notifier.dbus_notify.call_count, 2)
        self.assertEqual([c[:2] for c in closed], [(1, 4)])

    def test_notify_error_other_notification(self):
        # we can only retry the last notification:
        notifier, closed = self.make_notifier()
        notifier.dbus_notify = Mock()
        notifier.setup_dbusnotify = Mock()
        self.show(notifier, nid=1)
        self.show(notifier, nid=2)
        notifier.NotifyError(1, DBusException("gone", name="org.freedesktop.DBus.Error.ServiceUnknown"))
        self.assertEqual([c[:2] for c in closed], [(1, 4)])


def main():
    unittest.main()


if __name__ == "__main__":
    main()
