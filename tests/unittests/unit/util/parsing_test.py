#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.parsing import SYNC_SUBSYSTEMS, parse_sharing_sync, is_sharing_sync, parse_sharing


class TestSharing(unittest.TestCase):

    def test_sync_all(self):
        for value in ("sync", "SYNC", " sync "):
            with self.subTest(value=value):
                self.assertEqual(parse_sharing_sync(value), SYNC_SUBSYSTEMS)
                for subsystem in SYNC_SUBSYSTEMS:
                    self.assertTrue(is_sharing_sync(value, subsystem))

    def test_individual_subsystems(self):
        self.assertEqual(parse_sharing_sync("sync-focus"), ("focus", ))
        self.assertEqual(parse_sharing_sync("sync-position,sync-pointer"), ("position", "pointer"))
        # aliases and duplicates:
        self.assertEqual(parse_sharing_sync("SYNC-Position, sync_position"), ("position", ))
        self.assertTrue(is_sharing_sync("sync-focus", "focus"))
        self.assertFalse(is_sharing_sync("sync-focus", "position"))
        self.assertFalse(is_sharing_sync("sync-focus", "pointer"))

    def test_no_sync(self):
        for value in ("yes", "no", "auto", "", "sync-bogus", None, True, False):
            with self.subTest(value=value):
                self.assertFalse(is_sharing_sync(value))
                for subsystem in SYNC_SUBSYSTEMS:
                    self.assertFalse(is_sharing_sync(value, subsystem))

    def test_parse_sharing(self):
        for value in ("yes", "sync", "sync-focus", "sync-position,sync-pointer", True):
            with self.subTest(value=value):
                self.assertTrue(parse_sharing(value))
        for value in ("no", False):
            with self.subTest(value=value):
                self.assertFalse(parse_sharing(value))
        self.assertIsNone(parse_sharing("auto"))
        self.assertIsNone(parse_sharing(None))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
