#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

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


def main():
    unittest.main()


if __name__ == "__main__":
    main()
