#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from PyQt6.QtCore import Qt, QPoint, QEvent
from PyQt6.QtGui import QImage, QPixmap, QPainter, QKeyEvent
from PyQt6.QtWidgets import QMainWindow, QLabel, QSizePolicy

from xpra.client.qt6.keys import key_names
from xpra.log import Logger

log = Logger()


def get_pointer_position(event) -> tuple[int, int, int, int]:
    glo_pos = event.globalPosition()
    pos = event.position()
    return round(glo_pos.x()), round(glo_pos.y()), round(pos.x()), round(pos.y())


def get_event_pos(event) -> tuple[int, int]:
    pos = event.pos()
    return round(pos.x()), round(pos.y())


def get_modifiers(event: QKeyEvent) -> list[str]:
    modifiers = []
    mods = event.modifiers()
    for value, name in {
        Qt.KeyboardModifier.ShiftModifier: "shift",
        Qt.KeyboardModifier.ControlModifier: "control",
        Qt.KeyboardModifier.AltModifier: "alt",
        Qt.KeyboardModifier.MetaModifier: "meta",
        # Qt.KeyboardModifier.KeypadModifier: "numlock",
        # Qt.KeyboardModifier.KeypadModifier: "group",
    }.items():
        if mods & value:
            modifiers.append(name)
    return modifiers


class DrawingArea(QLabel):

    def __init__(self, client, wid):
        super().__init__()
        self.client = client
        self.send = client.send
        self.wid = wid
        self.seq = 0

    def mouseMoveEvent(self, event) -> None:
        pos = get_pointer_position(event)
        self.send("pointer", -1, self.seq, self.wid, pos, {})
        self.seq += 1

    def send_mouse_button_event(self, event, pressed=True) -> None:
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
        self.send("pointer-button", -1, self.seq, self.wid, button, pressed, pos, props)
        self.seq += 1

    def mousePressEvent(self, event) -> None:
        self.send_mouse_button_event(event, True)

    def mouseReleaseEvent(self, event) -> None:
        self.send_mouse_button_event(event, False)

    def mouseDoubleClickEvent(self, event) -> None:
        self.send_mouse_button_event(event, True)
        self.send_mouse_button_event(event, True)

    def wheelEvent(self, event) -> None:
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
        self.metadata = metadata
        if metadata.get("override-redirect"):
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window | Qt.WindowType.X11BypassWindowManagerHint)
        self.setWindowTitle(metadata.get("title", ""))
        self.label = DrawingArea(client, wid)
        self.label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))
        self.label.setMinimumSize(1, 1)
        self.canvas = QPixmap(w, h)
        self.canvas.fill(Qt.GlobalColor.white)
        self.label.setPixmap(self.canvas)
        self.setCentralWidget(self.label)
        self.move(x, y)
        self.resize(w, h)
        self.label.setMouseTracking(True)
        # self.setFixedSize(w, h)
        self.installEventFilter(self)

    def get_canvas_size(self) -> tuple[int, int]:
        size = self.label.size()
        return size.width(), size.height()

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if etype == QEvent.Type.WindowDeactivate:
            self.client.update_focus(0)
        elif etype == QEvent.Type.WindowActivate:
            self.client.update_focus(self.wid)
        elif etype == QEvent.Type.Show:
            x = self.pos().x() + self.label.pos().x()
            y = self.pos().y() + self.label.pos().y()
            w, h = self.get_canvas_size()
            if not self.metadata.get("override-redirect"):
                self.send("map-window", self.wid, x, y, w, h)
        elif etype == QEvent.Type.Hide:
            log("hidden - iconified?")
        elif etype == QEvent.Type.Move:
            x, y = get_event_pos(event)
            x += self.label.pos().x()
            y += self.label.pos().y()
            w, h = self.get_canvas_size()
            state = {}
            props = {}
            self.send("configure-window", self.wid, x, y, w, h, props, 0, state, False)
        elif etype == QEvent.Type.WindowStateChange:
            new_state = self.windowState()
            old_state = event.oldState()
            changes = {}
            for mask, name in {
                Qt.WindowState.WindowMinimized: "iconified",
                Qt.WindowState.WindowMaximized: "maximized",
                Qt.WindowState.WindowFullScreen: "fullscreen",
                Qt.WindowState.WindowActive: "focused",
            }.items():
                if new_state & mask != old_state & mask:
                    changes[name] = bool(new_state & mask)
            log(f"state changes: {changes}")
            if changes:
                props = {}
                self.send("configure-window", self.wid, 0, 0, 0, 0, props, 0, changes, True)
        elif etype == QEvent.Type.Resize:
            size = event.size()
            x = self.pos().x() + self.label.pos().x()
            y = self.pos().y() + self.label.pos().y()
            w = size.width()
            h = size.height()
            state = {}
            props = {}
            self.send("configure-window", self.wid, x, y, w, h, props, 0, state, False)
            old_pixmap = self.canvas
            self.canvas = QPixmap(w, h)
            self.canvas.fill(Qt.GlobalColor.white)
            painter = QPainter(self.canvas)
            painter.drawPixmap(0, 0, old_pixmap)
            painter.end()
            self.label.setPixmap(self.canvas)
        log(f"{obj}: {event} {event.type().name}")
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self.send_key_event(event, True)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        self.send_key_event(event, False)

    def closeEvent(self, event) -> None:
        log(f"close: {event}")
        self.send("close-window", self.wid)
        event.ignore()

    def send_key_event(self, event, pressed=True) -> None:
        keyval = event.key()
        name = key_names.get(keyval, event.text())
        keycode = event.nativeScanCode()
        string = event.text()
        group = 0
        modifiers = get_modifiers(event)
        native_modifiers = event.nativeModifiers()
        vk = event.nativeVirtualKey()
        log(f"key: {name!r}, {keyval=}, {keycode=}, {modifiers=} {native_modifiers=}, {vk=}")
        self.send("key-action", self.wid, name, pressed, modifiers, keyval, string, keycode, group)

    def draw(self, x, y, w, h, coding, data, stride) -> None:
        if coding in ("png", "jpg", "webp"):
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(data))
            if img.mode == "RGBA":
                coding = "rgb32"
                stride = w * 4
            else:
                assert img.mode == "RGB"
                coding = "rgb24"
                stride = w * 3
            data = img.tobytes("raw", img.mode)
        assert coding in ("rgb24", "rgb32")
        fmt = QImage.Format.Format_RGB888 if coding == "rgb24" else QImage.Format.Format_ARGB32_Premultiplied
        image = QImage(data, w, h, stride, fmt)
        canvas = self.label.pixmap()
        painter = QPainter(canvas)
        point = QPoint(x, y)
        painter.drawImage(point, image)
        painter.end()
        self.label.setPixmap(canvas)
