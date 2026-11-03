#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""The qt6 client windows: focus, pointer buttons and double-clicks."""

import os
import unittest

from unit.process_test_util import DisplayContext
from unit.client.pyglet_window_test import FakeClient


class Qt6WindowTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PyQt6 is not installed")
        cls.enterClassContext(DisplayContext())
        # (the environment is restored when the display context exits)
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        # destroy the application while the display is still there:
        # its gtk platform theme fails without a display connection
        from PyQt6 import sip
        cls.app.processEvents()
        sip.delete(cls.app)
        cls.app = None

    def setUp(self) -> None:
        from xpra.client.qt6.window import ClientWindow
        self.client = FakeClient()
        self.window = ClientWindow(self.client, 5, 10, 20, 200, 100, {"title": "test"})

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()

    def test_focus(self) -> None:
        # an exception in `eventFilter` aborts the whole process:
        from PyQt6.QtCore import QEvent
        for event_type in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate):
            self.window.eventFilter(self.window, QEvent(event_type))
        self.assertEqual(self.client.focus, [5, 0])

    def test_buttons(self) -> None:
        from PyQt6.QtCore import Qt, QPointF
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QEvent
        label = self.window.label
        buttons = (
            Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton,
            Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton,
        )
        for button in buttons:
            for event_type, handler in (
                (QEvent.Type.MouseButtonPress, label.mousePressEvent),
                (QEvent.Type.MouseButtonRelease, label.mouseReleaseEvent),
            ):
                handler(QMouseEvent(event_type, QPointF(5, 6), QPointF(15, 26), button, button,
                                    Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.client.buttons(), [(b, pressed) for b in (1, 2, 3, 8, 9) for pressed in (True, False)])

    def test_double_click(self) -> None:
        # what Qt sends for a double-click:
        from PyQt6.QtCore import Qt, QPointF, QEvent
        from PyQt6.QtGui import QMouseEvent
        label = self.window.label
        button = Qt.MouseButton.LeftButton
        for event_type, handler in (
            (QEvent.Type.MouseButtonPress, label.mousePressEvent),
            (QEvent.Type.MouseButtonRelease, label.mouseReleaseEvent),
            (QEvent.Type.MouseButtonDblClick, label.mouseDoubleClickEvent),
            (QEvent.Type.MouseButtonRelease, label.mouseReleaseEvent),
        ):
            handler(QMouseEvent(event_type, QPointF(5, 6), QPointF(15, 26), button, button,
                                Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.client.buttons(), [(1, True), (1, False)] * 2)

    def test_wheel(self) -> None:
        # a mouse wheel only sets the `angleDelta`:
        from PyQt6.QtCore import Qt, QPoint, QPointF
        from PyQt6.QtGui import QWheelEvent
        for dx, dy in ((0, 120), (0, -120), (120, 0), (-120, 0)):
            self.window.label.wheelEvent(QWheelEvent(QPointF(5, 6), QPointF(15, 26), QPoint(), QPoint(dx, dy),
                                                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                                     Qt.ScrollPhase.NoScrollPhase, False))
        self.assertEqual(self.client.buttons(), [(b, pressed) for b in (4, 5, 6, 7) for pressed in (True, False)])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
