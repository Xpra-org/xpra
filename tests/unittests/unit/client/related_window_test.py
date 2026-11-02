#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Test resolving "transient-for" / "parent" window references through the `window` subsystem."""

import unittest

from xpra.util.objects import typedict
from xpra.client.gui.window_base import ClientWindowBase
from xpra.client.gui.fake_client import FakeWindowSubsystem


class Window:
    find_related_window = ClientWindowBase.find_related_window

    def __init__(self, metadata: dict, window_subsystem=None):
        self._metadata = typedict(metadata)
        self.window_subsystem = window_subsystem

    def get_subsystem(self, name: str):
        return self.window_subsystem if name == "window" else None


class RelatedWindowTest(unittest.TestCase):

    def test_found(self) -> None:
        ws = FakeWindowSubsystem()
        parent = object()
        ws._id_to_window[5] = parent
        w = Window({"transient-for": 5, "parent": 6}, ws)
        self.assertIs(w.find_related_window("transient-for"), parent)
        self.assertIsNone(w.find_related_window("parent"))

    def test_missing(self) -> None:
        ws = FakeWindowSubsystem()
        ws._id_to_window[0] = object()
        self.assertIsNone(Window({}, ws).find_related_window("parent"))
        self.assertIsNone(Window({"parent": 0}, ws).find_related_window("parent"))
        self.assertIsNone(Window({"parent": 5}).find_related_window("parent"))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
