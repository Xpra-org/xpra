#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.notifications.notifier_base import NotifierBase


class NotifierBaseTest(unittest.TestCase):

    def test_icon_string(self):
        notifier = NotifierBase()
        for app_icon in ("mail-unread", "org.gnome.Evolution"):
            self.assertEqual(notifier.get_icon_string(1, app_icon, None), app_icon)
        for app_icon in (
            "/etc/passwd", "file:///home/user/Downloads/x.png", "../x.png", "~/x.png",
            "resource:///x.png", "a b", "x" * 200,
        ):
            with self.subTest(app_icon=app_icon):
                self.assertEqual(notifier.get_icon_string(1, app_icon, None), "")


if __name__ == '__main__':
    unittest.main()
