#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from PyQt6.QtCore import Qt, QPoint, QEvent
from PyQt6.QtGui import QImage, QPixmap, QPainter
from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel

from xpra.log import Logger

log = Logger()


def get_pointer_position(event):
    glo_pos = event.globalPosition()
    pos = event.position()
    return glo_pos.x(), glo_pos.y(), pos.x(), pos.y()


class DrawingArea(QLabel):

    def __init__(self, client, wid):
        super().__init__()
        self.client = client
        self.send = client.send
        self.wid = wid
        self.seq = 0

    def mouseMoveEvent(self, event):
        pos = get_pointer_position(event)
        self.send("pointer", -1, self.seq, self.wid, pos, {})
        self.seq += 1

    def send_mouse_button_event(self, event, pressed=True):
        props = {
            # "modifiers": (),
            # "buttons": (),
        }
        button = {
            Qt.MouseButton.LeftButton: 1,
            Qt.MouseButton.RightButton: 2,
            Qt.MouseButton.MiddleButton: 3,
        }.get(event.button(), -1)
        if button < 0:
            return
        pos = get_pointer_position(event)
        self.send("pointer-button", -1, self.seq, self.wid, button, True, pos, props)
        self.seq += 1

    def mousePressEvent(self, event):
        self.send_mouse_button_event(event, True)

    def mouseReleaseEvent(self, event):
        self.send_mouse_button_event(event, False)

    def mouseDoubleClickEvent(self, event):
        self.send_mouse_button_event(event, True)
        self.send_mouse_button_event(event, True)

    def wheelEvent(self, event):
        pos = get_pointer_position(event)
        delta = event.pixelDelta()
        props = {}
        if delta.y() != 0:
            button = 4 if delta.y() > 0 else 5
            self.send("pointer-button", -1, self.seq, self.wid, button, True, pos, props)
            self.send("pointer-button", -1, self.seq, self.wid, button, False, pos, props)
            self.seq += 1
        if delta.x() != 0:
            button = 6 if delta.y() > 0 else 7
            self.send("pointer-button", -1, self.seq, self.wid, button, True, pos, props)
            self.send("pointer-button", -1, self.seq, self.wid, button, False, pos, props)
            self.seq += 1


class ClientWindow(QMainWindow):
    def __init__(self, client, wid: int, x: int, y: int, w: int, h: int, metadata: dict):
        super().__init__()
        self.client = client
        self.send = client.send
        self.wid = wid
        self.setWindowTitle(metadata.get("title", ""))
        self.label = DrawingArea(client, wid)
        self.canvas = QPixmap(w, h)
        self.canvas.fill(Qt.GlobalColor.white)
        self.label.setPixmap(self.canvas)
        self.setCentralWidget(self.label)
        self.resize(w, h)
        self.label.setMouseTracking(True)
        # self.setFixedSize(w, h)
        self.installEventFilter(self)

    def eventFilter(self, object, event):
        if event.type().name == QEvent.Type.WindowDeactivate:
            self.client.update_focus(0)
        if event.type() == QEvent.Type.WindowActivate:
            self.client.update_focus(self.wid)
        log(f"{object}: {event} {event.type().name}")
        return False

    def draw(self, x, y, w, h, coding, data, stride):
        assert coding in ("rgb24", "rgb32")
        canvas = self.label.pixmap()
        painter = QPainter(canvas)
        image = QImage(data, w, h, stride, QImage.Format.Format_BGR888)
        point = QPoint(x, y)
        painter.drawImage(point, image)
        painter.end()
        self.label.setPixmap(canvas)

    def focusInEvent(self, event):
        log.info(f"focus in: {event}")

    def focusOutEvent(self, event):
        log.info(f"focus out: {event}")


def main(args) -> int:
    app = QApplication(args)
    win = ClientWindow({})
    win.show()
    return app.exec()


if __name__ == "__main__":
    main(sys.argv)
