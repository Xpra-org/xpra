#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import struct
from io import BytesIO
from typing import TypeAlias

from PIL import Image

from xpra.log import Logger
from xpra.os_util import gi_import
from xpra.util.io import load_binary_file
from xpra.util.objects import typedict
from xpra.gtk.window import add_close_accel
from xpra.util.glib import install_signal_handlers
from xpra.opengl.window import get_gl_client_window_module
from xpra.common import force_size_constraint
from xpra.client.gui.fake_client import FakeClient
from xpra.client.gui.window_border import WindowBorder

Gtk = gi_import("Gtk")
Pango = gi_import("Pango")

log = Logger()


ScreenUpdate: TypeAlias = tuple[int, int, int, int, str, bytes | tuple, int, typedict]


class TestGLRender:

    def __init__(self):
        from xpra.codecs.loader import load_codec
        load_codec("dec_pillow")

        self.ww = 800
        self.wh = 600

        self.index = 0
        self.updates = self.gen_updates()

        self.opengl_props, gl_client_window_module = get_gl_client_window_module("force")
        self.GLClientWindowClass = gl_client_window_module.GLClientWindow

        self.gl_window = self.init_gl_window()
        self.control_window = self.init_control_window()

    def gen_updates(self) -> list[ScreenUpdate]:
        # fake some draw packets
        w = self.ww
        h = self.wh

        def fullrgb(data: bytes) -> ScreenUpdate:
            return 0, 0, w, h, "rgb32", data, w * 4, typedict()

        def b(v: int) -> bytes:
            return struct.pack("@B", v)

        packets = [
            # clear it
            fullrgb(b"\0"*4*w*h),
            # white:
            fullrgb(b"\xff" * 4 * w * h),
            # gradient grey:
            fullrgb(b"".join(b(round(y * 255 / h)) * 4 * w for y in range(h))),
            # gradient grey:
            fullrgb(b"".join((b(round(y * 255 / h)) + b"\x80\x40\xff") * w for y in range(h)))
        ]

        def add_scroll(dy: int, fill: bytes):
            # scroll data: (x, y, w, h, xdelta, ydelta)
            scroll_h = abs(dy)
            scrolls = [
                (0, max(0, -dy), w, h-scroll_h, 0, dy)
            ]
            packets.append((0, 0, w, h, "scroll", scrolls, 0, typedict({"flush": 1})))
            stride = w * 4
            data = fill * stride * scroll_h
            if dy > 0:
                # scrolling down, fill the top:
                filly = 0
            else:
                filly = h + dy
            packets.append((0, filly, w, scroll_h, "rgb32", data, stride, typedict()))
        # scroll up:
        add_scroll(-10, b"\xff")
        # scroll down:
        add_scroll(-20, b"\x80")

        from xpra.platform.paths import get_icon_filename
        filename = get_icon_filename("xpra")
        ext = filename.split(".")[-1]
        icon = load_binary_file(filename)
        img = Image.open(BytesIO(icon))
        iw, ih = img.size
        assert icon

        def add_icon(x: int, y: int, options: typedict) -> None:
            packets.append((x, y, iw, ih, ext, icon, iw*4, options))
        count = h // ih + 1
        for y in range(count):
            add_icon(w // 2, y * ih, typedict({"flush": count-1-y}))
        return packets

    def init_control_window(self) -> None:
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_transient_for(self.gl_window)
        window.set_size_request(1920, 720)

        vbox = Gtk.VBox(homogeneous=False, spacing=0)

        hbox = Gtk.HBox(homogeneous=True, spacing=10)
        vbox.pack_start(hbox, False, False, 10)

        pu = Gtk.Button(label="Previous Update")
        pu.connect("clicked", self.previous_update)
        hbox.add(pu)
        nu = Gtk.Button(label="Next Update")
        nu.connect("clicked", self.next_update)
        hbox.add(nu)

        self.label = Gtk.Label()
        fontdesc = Pango.FontDescription("monospace 9")
        self.label.modify_font(fontdesc)
        self.label.set_margin_start(10)
        self.label.set_xalign(0)
        self.label.set_line_wrap(True)
        vbox.pack_start(self.label, True, True, 0)

        window.add(vbox)

        window.connect("delete-event", self.close)
        add_close_accel(window, self.close)
        return window

    def init_gl_window(self) -> None:
        noclient = FakeClient()
        x = 2000
        y = 1000
        metadata = typedict({"has-alpha": True})
        metadata.update(force_size_constraint(self.ww, self.wh))
        border = WindowBorder()
        max_window_size = (4096, 4096)
        default_cursor_data = None
        pixel_depth = 32

        window = self.GLClientWindowClass(noclient, None, 0, 2 ** 32 - 1, x, y, self.ww, self.wh, self.ww, self.wh,
                                          metadata, False, typedict({}),
                                          border, max_window_size, default_cursor_data, pixel_depth)
        window_backing = window._backing
        window.realize()
        window_backing.paint_screen = True
        window.connect("delete-event", self.close)
        add_close_accel(window, self.close)
        return window

    def previous_update(self, *_args) -> None:
        if self.index > 0:
            self.index -= 1
            self.show_update()

    def next_update(self, *_args) -> None:
        if self.index < len(self.updates) - 1:
            self.index += 1
            self.show_update()

    def show_update(self) -> None:
        update = self.updates[self.index]

        def show_result(*args):
            log.info(f"show_result%s for {update[4]}", args)

        self.gl_window.draw_region(*update, callbacks=[show_result])
        encoding = update[4]
        x = update[0]
        y = update[1]
        self.label.set_text(f"{encoding} at {x}x{y}")

    def run(self) -> None:
        install_signal_handlers("test-gl-scroll", self.close)
        self.gl_window.show_all()
        self.control_window.show_all()
        self.show_update()
        Gtk.main()
        self.control_window.close()
        self.gl_window.close()

    def close(self, *_args) -> None:
        Gtk.main_quit()


def main() -> int:
    from xpra.platform import program_context
    from xpra.platform.gui import init as gui_init
    from xpra.log import enable_color, consume_verbose_argv
    from xpra.util.system import is_X11
    with program_context("OpenGL Native Context Check"):
        if is_X11():
            from xpra.x11.gtk.display_source import init_gdk_display_source
            init_gdk_display_source()
        gui_init()
        enable_color()
        consume_verbose_argv(sys.argv, "opengl")
        TestGLRender().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
