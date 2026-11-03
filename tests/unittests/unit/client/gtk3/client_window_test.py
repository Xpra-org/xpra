#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Real gtk3 client windows, created without a client:
a window is only given a subsystem lookup, the read-only flag and the xpra menu.
The events are emitted on the window's widgets, so they go through the same handlers as real ones.
"""

import os
import unittest
from types import SimpleNamespace

# no OpenGL or real backing needed:
os.environ["XPRA_USE_FAKE_BACKING"] = "1"

from xpra.os_util import gi_import  # noqa: E402
from xpra.util.objects import typedict  # noqa: E402

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")


def has_display() -> bool:
    return Gdk.Display.get_default() is not None


class Recorder:
    """ records the calls made to the methods named """

    def __init__(self, *names, **attrs):
        self.calls: list[tuple] = []
        for name in names:
            setattr(self, name, self.recorder(name))
        for k, v in attrs.items():
            setattr(self, k, v)

    def recorder(self, name: str):
        def record(*args):
            self.calls.append((name, *args))
        return record


@unittest.skipUnless(has_display(), "requires a display")
class ClientWindowTest(unittest.TestCase):

    def setUp(self) -> None:
        from xpra.client.gui.fake_client import FakeWindowHost, FakePointerSubsystem
        self.host = FakeWindowHost()
        pointer = FakePointerSubsystem()
        self.pointer_calls = []
        pointer.send_button = lambda *args: self.pointer_calls.append(("button", *args))
        pointer.wheel_event = lambda *args: self.pointer_calls.append(("wheel", *args))
        pointer.send_mouse_position = lambda *args: self.pointer_calls.append(("motion", *args))
        self.host.subsystems["pointer"] = pointer
        self.windows = []

    def tearDown(self) -> None:
        for window in self.windows:
            window.destroy()

    def make_window(self, wid=3, geometry=(10, 20, 200, 100), metadata=None, **kwargs):
        from xpra.client.gtk3.window.window import ClientWindow
        window = self.host.make_window(ClientWindow, wid, geometry, metadata or {"title": "test"}, **kwargs)
        self.windows.append(window)
        return window

    @staticmethod
    def button_event(event_type, button=1, x=5, y=6, x_root=15, y_root=26):
        event = Gdk.Event.new(event_type)
        event.button.button = button
        event.button.x, event.button.y = float(x), float(y)
        event.button.x_root, event.button.y_root = float(x_root), float(y_root)
        return event

    def click(self, window) -> None:
        window.drawing_area.emit("button-press-event", self.button_event(Gdk.EventType.BUTTON_PRESS))
        window.drawing_area.emit("button-release-event", self.button_event(Gdk.EventType.BUTTON_RELEASE))

    @staticmethod
    def smooth_scroll(window, delta_y=1.0) -> None:
        event = Gdk.Event.new(Gdk.EventType.SCROLL)
        event.scroll.direction = Gdk.ScrollDirection.SMOOTH
        event.scroll.delta_y = delta_y
        window.drawing_area.emit("scroll-event", event)

    @staticmethod
    def key_event(window, pressed=True, keyval=Gdk.KEY_a) -> None:
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS if pressed else Gdk.EventType.KEY_RELEASE)
        event.key.keyval = keyval
        event.key.hardware_keycode = 38
        window.emit("key-press-event" if pressed else "key-release-event", event)

    def test_no_client(self) -> None:
        window = self.make_window()
        self.assertFalse(hasattr(window, "_client"))
        self.assertEqual(window.get_subsystem, self.host.get_subsystem)
        # the window schedules its callbacks via the window subsystem's main loop:
        window_sub = self.host.get_subsystem("window")
        self.assertEqual(window.idle_add, window_sub.idle_add)
        self.assertEqual(window.timeout_add, window_sub.timeout_add)
        self.assertEqual(window.source_remove, window_sub.source_remove)
        self.assertIs(window_sub.get_window(3), window)

    def test_buttons(self) -> None:
        window = self.make_window()
        self.click(window)
        self.assertEqual([call[:5] for call in self.pointer_calls], [
            ("button", 0, 3, 1, True),
            ("button", 0, 3, 1, False),
        ])
        # the pointer position, relative to the root and to the window:
        self.assertEqual(self.pointer_calls[0][5], (15, 26, 5, 6))

    def test_button_transform(self) -> None:
        window = self.make_window()
        self.host.get_subsystem("pointer").button_transform = {("shift", 1): 3}
        self.host.subsystems["keyboard"] = SimpleNamespace(mask_to_names=lambda _state: ["shift"])
        self.click(window)
        self.assertEqual([call[3] for call in self.pointer_calls], [3, 3])

    def test_no_server_pointer(self) -> None:
        window = self.make_window()
        self.host.get_subsystem("pointer").server_pointer = False
        self.click(window)
        self.assertEqual(self.pointer_calls, [])
        # the wheel events are dropped by the pointer subsystem itself (`wheel_event`),
        # since some clients send them there without going through a window:
        self.smooth_scroll(window)
        self.assertEqual([call[0] for call in self.pointer_calls], ["wheel"])

    def test_smooth_scroll(self) -> None:
        window = self.make_window()
        self.smooth_scroll(window, 1.0)
        self.assertEqual(len(self.pointer_calls), 1)
        name, device_id, wid, deltax, deltay = self.pointer_calls[0][:5]
        self.assertEqual((name, device_id, wid, deltax), ("wheel", -1, 3, 0))
        self.assertLess(deltay, 0)

    def test_readonly(self) -> None:
        window = self.make_window()
        self.host.readonly = True
        self.click(window)
        self.smooth_scroll(window)
        self.assertEqual(self.pointer_calls, [])
        # the size can no longer be changed:
        window.update_metadata(typedict())
        constraints = window._metadata.get("size-constraints")
        self.assertTrue(constraints)
        self.assertEqual(tuple(constraints["minimum-size"]), tuple(constraints["maximum-size"]))
        # the read-only flag can change at any time:
        self.host.readonly = False
        self.click(window)
        self.assertEqual(len(self.pointer_calls), 2)

    def test_readonly_from_the_start(self) -> None:
        self.host.readonly = True
        window = self.make_window()
        constraints = window._metadata.get("size-constraints")
        self.assertEqual(tuple(constraints["minimum-size"]), (200, 100))
        self.assertEqual(tuple(constraints["maximum-size"]), (200, 100))

    def test_keys(self) -> None:
        window = self.make_window()
        # without a keyboard subsystem, the key events go nowhere:
        self.key_event(window)
        keyboard = Recorder("handle_key_action", mask_to_names=lambda _state: [])
        self.host.subsystems["keyboard"] = keyboard
        self.key_event(window, True)
        self.key_event(window, False)
        self.assertEqual([(name, target) for name, target, _event in keyboard.calls],
                         [("handle_key_action", window)] * 2)
        events = [call[2] for call in keyboard.calls]
        self.assertEqual([(e.keyname, e.pressed, e.string) for e in events], [("a", True, "a"), ("a", False, "a")])

    def test_focus(self) -> None:
        window = self.make_window()
        window_sub = self.host.get_subsystem("window")
        changes = []

        def update_focus(wid: int, focused: bool) -> bool:
            changes.append((wid, focused))
            return True
        window_sub.update_focus = update_focus
        window._focus_latest = True
        window.send_latest_focus()
        window._focus_latest = False
        window.send_latest_focus()
        self.assertEqual(changes, [(3, True), (3, False)])

    @staticmethod
    def accepts_uris(window) -> bool:
        targets = window.drag_dest_get_target_list()
        return bool(targets and targets.find(Gdk.Atom.intern("text/uri-list", False))[0])

    def test_dragndrop(self) -> None:
        # files can only be dropped when there is a `file` subsystem to send them:
        window = self.make_window()
        self.assertFalse(self.accepts_uris(window))
        file_handler = SimpleNamespace()
        self.host.subsystems["file"] = file_handler
        window = self.make_window(wid=4)
        self.assertTrue(self.accepts_uris(window))
        self.assertIs(window._file_handler, file_handler)

    def xpra_menu_button(self, window):
        headerbar = window.get_titlebar()
        self.assertIsInstance(headerbar, Gtk.HeaderBar)
        for child in headerbar.get_children():
            if headerbar.child_get_property(child, "pack-type") == Gtk.PackType.END and isinstance(child, Gtk.Button):
                return child
        return None

    def test_headerbar_without_xpra_menu(self) -> None:
        window = self.make_window(headerbar="force")
        self.assertIsNone(self.xpra_menu_button(window))
        # nothing to show:
        window.show_xpra_menu()

    def test_headerbar_xpra_menu(self) -> None:
        menu = Recorder("build", "popup")
        window = self.make_window(headerbar="force", get_xpra_menu=lambda: menu)
        button = self.xpra_menu_button(window)
        self.assertIsNotNone(button)
        button.clicked()
        self.assertEqual(menu.calls, [("build", ), ("popup", 0, 0)])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
