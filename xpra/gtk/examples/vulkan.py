#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# A small demo that opens a GTK window and paints test BGRX pixels into it
# using the GTK-independent Vulkan renderer (xpra.vulkan.renderer).

from xpra.os_util import gi_import
from xpra.log import Logger, consume_verbose_argv

log = Logger("vulkan")

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

WIDTH = 640
HEIGHT = 480


def make_test_bgrx(width: int, height: int) -> bytes:
    # vertical colour bars + a horizontal brightness gradient, as BGRX (B, G, R, X):
    bars = (
        (0x00, 0x00, 0x00),  # black
        (0x00, 0x00, 0xFF),  # red
        (0x00, 0xFF, 0x00),  # green
        (0xFF, 0x00, 0x00),  # blue
        (0x00, 0xFF, 0xFF),  # yellow
        (0xFF, 0xFF, 0x00),  # cyan
        (0xFF, 0x00, 0xFF),  # magenta
        (0xFF, 0xFF, 0xFF),  # white
    )
    buf = bytearray(width * height * 4)
    nbars = len(bars)
    for y in range(height):
        shade = y / max(1, height - 1)
        row = y * width * 4
        for x in range(width):
            r, g, b = bars[x * nbars // width]
            o = row + x * 4
            buf[o] = int(r * shade)      # B byte position holds the bar's "r" tuple value
            buf[o + 1] = int(g * shade)
            buf[o + 2] = int(b * shade)
            buf[o + 3] = 0xFF            # X (unused)
    return bytes(buf)


class VulkanDemo:
    def __init__(self):
        self.renderer = None
        self.width = WIDTH
        self.height = HEIGHT
        self._pixels_cache: tuple[int, int, bytes] | None = None
        self.window = Gtk.Window(title="Vulkan BGRX Demo")
        self.window.set_default_size(WIDTH, HEIGHT)
        self.window.connect("delete-event", self.on_close)
        self.area = Gtk.DrawingArea()
        self.area.set_app_paintable(True)
        # we paint the native window directly via Vulkan,
        # so stop GTK from blitting its own (empty) buffer over it:
        self.area.set_double_buffered(False)
        self.area.set_size_request(WIDTH, HEIGHT)
        self.area.connect("realize", self.on_realize)
        self.area.connect("configure-event", self.on_configure)
        self.window.add(self.area)
        self.window.show_all()

    def on_realize(self, widget) -> None:
        from xpra.vulkan.x11 import create_vulkan_window
        gdk_window = widget.get_window()
        xid = gdk_window.get_xid()
        log.info("creating Vulkan renderer for window %#x", xid)
        self.renderer = create_vulkan_window(xid, self.width, self.height)
        # repaint periodically so the content survives GTK / compositor exposes:
        GLib.timeout_add(200, self.repaint)

    def on_configure(self, _widget, event) -> bool:
        if self.renderer and (event.width != self.width or event.height != self.height):
            self.width = event.width
            self.height = event.height
            self.renderer.resize(self.width, self.height)
            self.repaint()
        return False

    def get_pixels(self) -> bytes:
        if not self._pixels_cache or self._pixels_cache[0] != self.width or self._pixels_cache[1] != self.height:
            self._pixels_cache = (self.width, self.height, make_test_bgrx(self.width, self.height))
        return self._pixels_cache[2]

    def repaint(self) -> bool:
        if not self.renderer:
            return False
        self.renderer.paint_bgrx(self.get_pixels(), self.width, self.height, self.width * 4)
        return True

    def on_close(self, *_args) -> bool:
        if self.renderer:
            self.renderer.close()
            self.renderer = None
        Gtk.main_quit()
        return False


def main(argv) -> int:
    from xpra.platform import program_context
    with program_context("Vulkan", "Vulkan"):
        consume_verbose_argv(argv, "vulkan")
        from xpra.util.system import is_X11
        if is_X11():
            from xpra.gtk.util import init_display_source
            init_display_source(False)
        VulkanDemo()
        log.info("starting main loop")
        Gtk.main()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
