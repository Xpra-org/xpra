#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from tkinter import Toplevel, Label
from PIL import Image, ImageTk
from xpra.net.packet_type import (
    POINTER_BUTTON, POINTER_MOTION,
    WINDOW_MAP, WINDOW_UNMAP, WINDOW_CLOSE, WINDOW_CONFIGURE,
)
from xpra.util.objects import typedict
from xpra.client.gui.window_title import window_title_str
from xpra.log import Logger

log = Logger("client", "window")

SHIFT_MASK = 1


def modifiers(value: int) -> list[str]:
    mod_mask = {
        1: "shift",
        2: "Caps_Lock",
        4: "control",
        8: "Alt_L",
        0x10: "Num_Lock",
        0x80: "Alt_R",
    }
    mods = []
    for mask, mod in mod_mask.items():
        if value & mask:
            mods.append(mod)
    return mods


class ClientWindow(Toplevel):
    def __init__(self, client, wid: int, x: int, y: int, w: int, h: int, metadata: dict):
        from xpra.client.tk.client import app
        super().__init__(app)
        self.withdraw()
        self.client = client
        self.send = client.send
        self.wid = wid
        self.metadata = typedict(metadata)
        self.overrideredirect(self.metadata.boolget("override-redirect", False))
        self.title(window_title_str(self.metadata.strget("title", "")))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.update_metadata(self.metadata)
        self.update_idletasks()

        self.backing = Image.new(mode="RGBA", size=(w, h))
        self.photo_image = ImageTk.PhotoImage(self.backing)
        self.label = Label(self, image=self.photo_image)
        self.label.pack()

        self.bind("<Motion>", self.on_mouse_motion)
        # all the buttons, including the wheel with Tk 8.6 on X11 (buttons 4 to 7):
        self.bind("<ButtonPress>", self.on_mouse_button_press)
        self.bind("<ButtonRelease>", self.on_mouse_button_release)
        self.bind("<MouseWheel>", self.on_mouse_wheel)
        self.bind("<FocusIn>", self.on_focus_in)
        self.bind("<FocusOut>", self.on_focus_out)
        self.bind("<Key>", self.on_key_press)
        self.bind("<KeyRelease>", self.on_key_release)
        # (the bindings of a toplevel also receive the events of the widgets it contains,
        # see `is_own_event`)
        self.bind("<Configure>", self.on_configure)
        self.bind("<Map>", self.on_map)
        self.bind("<Unmap>", self.on_unmap)
        # the server decides what to do when the user closes the window:
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def update_metadata(self, metadata: typedict):
        self.metadata.update(metadata)
        if "title" in metadata:
            self.title(window_title_str(metadata.strget("title")))
        else:
            log(f"unused window metadata {self.wid:#x}: {metadata}")

    def show(self) -> None:
        self.deiconify()

    def has_toplevel_focus(self) -> bool:
        focused = self.focus_displayof()
        if focused is None:
            return False
        path = str(self)
        focused_path = str(focused)
        return focused_path == path or focused_path.startswith(path + ".")

    def present(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def restack(self, other_window, above: int = 0) -> None:
        if above:
            self.lift(other_window)
        else:
            self.lower(other_window)

    def on_focus_in(self, event) -> None:
        log(f"focus-in: {event!r}")
        self.client.update_focus(self.wid)

    @staticmethod
    def on_focus_out(event) -> None:
        log(f"focus_out: {event!r}")
        # no real need to update anything
        # (tracking where the focus is actually going to would add the same complexity as the Gtk client)

    def on_key_press(self, event) -> None:
        log(f"key press: {event!r}")
        self.on_key(True, event)

    def on_key_release(self, event) -> None:
        log(f"key release: {event!r}")
        self.on_key(False, event)

    def on_key(self, pressed: bool, event) -> None:
        mods = modifiers(event.state)
        keyname = event.keysym
        string = event.char
        keycode = event.keycode
        self.client.send("keyboard-event", self.wid, keyname, pressed, {
            "modifiers": mods,
            "string": string,
            "keycode": keycode,
            "backend": "tk",
        })

    def get_pointer_position(self, event) -> tuple[int, int, int, int]:
        """ the position on the screen, and relative to the window """
        # (`event.x` and `event.y` are relative to the widget under the pointer, not the window)
        x, y = event.x_root, event.y_root
        return x, y, x - self.winfo_rootx(), y - self.winfo_rooty()

    def on_mouse_motion(self, event) -> None:
        log(f"mouse motion: {event!r}")
        device_id = -1
        seq = 0
        pos = self.get_pointer_position(event)
        self.client.send(POINTER_MOTION, device_id, seq, self.wid, pos, {})

    def on_mouse_button_press(self, event) -> None:
        log(f"mouse button press: {event!r}")
        self.on_mouse_button_event(True, event)

    def on_mouse_button_release(self, event) -> None:
        log(f"mouse button release: {event!r}")
        self.on_mouse_button_event(False, event)

    def on_mouse_button_event(self, pressed: bool, event) -> None:
        seq = 0
        button = event.num
        pos = self.get_pointer_position(event)
        self.client.send(POINTER_BUTTON, -1, seq, self.wid, button, pressed, pos, {})

    def on_mouse_wheel(self, event) -> None:
        # Tk 8.7 and later, and Tk on MS Windows and macOS: the delta is a multiple of 120 with most mice,
        # and the horizontal wheel (X11 buttons 6 and 7) is sent with the shift modifier
        log(f"mouse wheel: {event!r}")
        if not event.delta:
            return
        button = 6 if event.state & SHIFT_MASK else 4
        if event.delta < 0:
            button += 1
        # sent as clicks of the wheel buttons:
        pos = self.get_pointer_position(event)
        for _ in range(max(1, abs(event.delta) // 120)):
            for pressed in (True, False):
                self.client.send(POINTER_BUTTON, -1, 0, self.wid, button, pressed, pos, {})

    def is_own_event(self, event) -> bool:
        return event.widget is self

    def on_map(self, event) -> None:
        log(f"map: {event!r}")
        if not self.is_own_event(event):
            return
        x = self.winfo_x()
        y = self.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        self.client.send(WINDOW_MAP, self.wid, x, y, w, h, {}, {})

    def on_unmap(self, event) -> None:
        log(f"unmap: {event!r}")
        if not self.is_own_event(event):
            return
        iconified = self.state() == "iconic"
        self.client.send(WINDOW_UNMAP, self.wid, iconified)

    def on_configure(self, event) -> None:
        log(f"configure: {event}")
        if not self.is_own_event(event):
            return
        self.client.send(WINDOW_CONFIGURE, self.wid, {
            "geometry": (event.x, event.y, event.width, event.height),
        })

    def on_close(self) -> None:
        self.client.send(WINDOW_CLOSE, self.wid)

    def on_resize(self, _event) -> None:
        x = self.winfo_x()
        y = self.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        self.client.send(WINDOW_CONFIGURE, self.wid, {
            "geometry": (x, y, w, h),
        })

    def draw(self, x: int, y: int, _w: int, _h: int, coding: str, data, _stride: int) -> None:
        if coding not in ("png", "jpeg", "webp"):
            raise ValueError(f"unsupported format {coding!r}")
        from xpra.codecs.pillow.decoder import open_only
        img = open_only(data, (coding, ))
        self.backing.paste(img, (x, y))
        self.photo_image.paste(self.backing)
