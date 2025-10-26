#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from io import BytesIO
from tkinter import Toplevel, Label
from PIL import Image, ImageTk

from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("client", "window")


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
        self.title(self.metadata.strget("title", ""))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.update_metadata(self.metadata)
        self.update_idletasks()

        self.backing = Image.new(mode="RGBA", size=(w, h))
        self.photo_image = ImageTk.PhotoImage(self.backing)
        self.label = Label(self, image=self.photo_image)
        self.label.pack()

        self.bind("<Motion>", self.on_mouse_motion)
        for button in range(1, 3):
            self.bind(f"<Button-{button}>", self.on_mouse_button_press)
            self.bind(f"<ButtonRelease-{button}>", self.on_mouse_button_release)
        # self.bind("<MouseWheel>", self.on_mouse_wheel)
        self.bind("<FocusIn>", self.on_focus_in)
        self.bind("<FocusOut>", self.on_focus_out)
        self.bind("<Key>", self.on_key_press)
        self.bind("<KeyRelease>", self.on_key_release)
        self.bind("<Configure>", self.on_configure)
        self.bind("<Map>", self.on_map)
        self.bind("<Unmap>", self.on_unmap)
        self.bind("<Destroy>", self.on_destroy)
        self.protocol("WM_DELETE_WINDOW", self.on_destroy)

    def update_metadata(self, metadata: typedict):
        self.metadata.update(metadata)
        if "title" in metadata:
            self.title(metadata.strget("title"))
        else:
            log(f"unused window metadata {self.wid:#x}: {metadata}")

    def show(self) -> None:
        self.deiconify()

    def on_focus_in(self, event) -> None:
        log(f"focus-in: {event!r}")
        self.client.update_focus(self.wid)

    @staticmethod
    def on_focus_out(event) -> None:
        log(f"focus_out: {event!r}")
        # no real need to update anything
        # (tracking where the focus is actually going to would add the same complexity as the Gtk client)

    def on_hide(self) -> None:
        self.client.send("unmap-window", self.wid)

    def on_key_press(self, event) -> None:
        log(f"key press: {event!r}")
        self.on_key(True, event)

    def on_key_release(self, event) -> None:
        log(f"key release: {event!r}")
        self.on_key(False, event)

    def on_key(self, pressed: bool, event) -> None:
        mods = modifiers(event.state)
        keyval = 0
        keyname = event.keysym
        string = event.char
        keycode = event.keycode
        group = 0
        self.client.send("key-action", self.wid, keyname, pressed, mods, keyval, string, keycode, group)

    def on_mouse_motion(self, event) -> None:
        log(f"mouse motion: {event!r}")
        device_id = -1
        seq = 0
        pos = (event.x, event.y)
        self.client.send("pointer", device_id, seq, self.wid, pos, {})

    def on_mouse_button_press(self, event) -> None:
        log(f"mouse button press: {event!r}")
        self.on_mouse_button_event(True, event)

    def on_mouse_button_release(self, event) -> None:
        log(f"mouse button release: {event!r}")
        self.on_mouse_button_event(False, event)

    def on_mouse_button_event(self, pressed: bool, event) -> None:
        seq = 0
        button = event.num
        pos = (event.x, event.y)
        self.client.send("pointer-button", -1, seq, self.wid, button, pressed, pos, {})

    def on_map(self, event) -> None:
        log(f"map: {event!r}")
        x = self.winfo_x()
        y = self.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        self.client.send("map-window", self.wid, x, y, w, h, {}, ())

    def on_unmap(self, _event) -> None:
        self.client.send("close-window", self.wid)

    def on_configure(self, event) -> None:
        log(f"configure: {event}")
        counter = 0
        props = {}
        x, y, w, h = event.x, event.y, event.width, event.height
        state = ()
        skip_geometry = False
        self.client.send("configure-window", self.wid, x, y, w, h, props, counter, state, skip_geometry)

    def on_destroy(self, _event=None) -> None:
        self.client.send("close-window", self.wid)

    def on_resize(self, _event) -> None:
        counter = 0
        props = {}
        x = self.winfo_x()
        y = self.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        state = ()
        skip_geometry = False
        self.client.send("configure-window", self.wid, x, y, w, h, props, counter, state, skip_geometry)

    def draw(self, x: int, y: int, _w: int, _h: int, coding: str, data, _stride: int) -> None:
        if coding not in ("png", "jpg", "webp"):
            raise ValueError(f"unsupported format {coding!r}")
        img = Image.open(BytesIO(data))
        self.backing.paste(img, (x, y))
        self.photo_image.paste(self.backing)
