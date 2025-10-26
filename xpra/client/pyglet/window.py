#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from pyglet.window import Window, event
from pyglet.image import ImageData, SolidColorImagePattern
from pyglet.sprite import Sprite

from xpra.client.pyglet.keys import keynames
from xpra.log import Logger

log = Logger()


def get_modifiers(_modifiers: int) -> Sequence[str]:
    return ()


class ClientWindow(Window):
    def __init__(self, client, wid: int, x: int, y: int, w: int, h: int, metadata: dict):
        super().__init__(visible=False)
        self.client = client
        self.send = client.send
        self.wid = wid
        self.metadata = metadata
        self.image = SolidColorImagePattern((128, 0, 0, 128)).create_image(w, h)
        self.sprite = Sprite(img=self.image, x=0, y=0)
        #self.image_data = self.image.get_image_data()
        #self.texture = self.image.get_texture()
        # window.config.alpha_size = 8
        # if metadata.get("override-redirect"):
        #    how?
        self.set_caption(metadata.get("title", ""))
        self.set_location(x, y)
        self.set_size(w, h)

        # A logger class, which prints events to stdout or to a file:
        win_event_logger = event.WindowEventLogger()
        self.push_handlers(win_event_logger)

    def show(self) -> None:
        self.set_visible(True)

    def on_close(self) -> None:
        self.client.send("close-window", self.wid)

    def on_activate(self) -> None:
        self.client.update_focus(self.wid)

    def on_show(self) -> None:
        x, y = self.get_location()
        w, h = self.get_size()
        self.client.send("map-window", self.wid, x, y, w, h, {}, ())

    def on_hide(self) -> None:
        self.client.send("unmap-window", self.wid)

    def on_key_press(self, keysym: int, modifiers: int) -> None:
        self.on_key_event(True, keysym, modifiers)

    def on_key_release(self, keysym: int, modifiers: int) -> None:
        self.on_key_event(False, keysym, modifiers)

    def on_key_event(self, pressed: bool, keysym: int, modifiers: int) -> None:
        keyname = keynames.get(keysym)
        if not keyname:
            log.info(f"unknown key {keysym}")
            return
        mods = get_modifiers(modifiers)
        keyval = 0
        string = ""
        keycode = 0
        group = 0
        self.client.send("key-action", self.wid, keyname, pressed, mods, keyval, string, keycode, group)

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        device_id = -1
        seq = 0
        pos = (x, y, dx, dy)
        self.client.send("pointer", device_id, seq, self.wid, pos, {})

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        self.on_mouse_button_event(True, x, y, button, modifiers)

    def on_mouse_release(self, x: int, y: int, button: int, modifiers: int) -> None:
        self.on_mouse_button_event(False, x, y, button, modifiers)

    def on_mouse_button_event(self, pressed: bool, x: int, y: int, button: int, modifiers: int) -> None:
        seq = 0
        pos = (x, y)
        self.client.send("pointer-button", -1, seq, self.wid, button, pressed, pos, {})

    def on_mouse_scroll(self, x: int, y: int, scroll_x: float, scroll_y: float) -> None:
        button = 4
        pointer = (x, y)
        modifiers = ()
        buttons = ()
        for state in True, False:
            self.send_button(-1, self.wid, button, state, pointer, modifiers, buttons, {})

    def on_move(self, x: int, y: int) -> None:
        counter = 0
        props = {}
        w, h = self.get_size()
        state = ()
        skip_geometry = False
        self.client.send("configure-window", self.wid, x, y, w, h, props, counter, state, skip_geometry)

    def on_resize(self, w: int, h: int) -> None:
        counter = 0
        props = {}
        x, y = self.get_location()
        state = ()
        skip_geometry = False
        self.client.send("configure-window", self.wid, x, y, w, h, props, counter, state, skip_geometry)

    def draw(self, x: int, y: int, w: int, h: int, coding: str, data, stride: int) -> None:
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
            flipped = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            data = flipped.tobytes("raw", img.mode)
        if coding == "rgb24":
            image = ImageData(w, h, "RGB", data, pitch=stride or w*3)
        elif coding == "rgb32":
            image = ImageData(w, h, "RGBA", data, pitch=stride or w*4)
        else:
            raise ValueError(f"invalid encoding {coding!r}")
        bh = self.get_size()[1]
        self.sprite = Sprite(image, x=x, y=bh - y - h)
        self.sprite.draw()
        self.flip()
