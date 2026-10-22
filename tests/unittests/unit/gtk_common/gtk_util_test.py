#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.gtk_common import gtk_util


class TestGtkVersionInfo(unittest.TestCase):

    def test_major_minor_micro_order(self):
        gtk = SimpleNamespace(MAJOR_VERSION=3, MINOR_VERSION=24, MICRO_VERSION=42)
        glib = SimpleNamespace(MAJOR_VERSION=2, MINOR_VERSION=80, MICRO_VERSION=3)
        with patch.object(gtk_util, "Gtk", gtk), patch.object(gtk_util, "GLib", glib), \
                patch.object(gtk_util, "GTK_VERSION_INFO", {}):
            versions = gtk_util.get_gtk_version_info()
        self.assertEqual(versions["gtk"]["version"], (3, 24, 42))
        self.assertEqual(versions["glib"]["version"], (2, 80, 3))


if __name__ == '__main__':
    unittest.main()
