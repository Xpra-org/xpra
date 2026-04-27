# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
import time
import colorsys
import threading

from xpra.os_util import gi_import
from xpra.exit_codes import ExitCode
from xpra.log import Logger
from xpra.util.env import envint

log = Logger("util")

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GdkPixbuf = gi_import("GdkPixbuf")
GLib = gi_import("GLib")


INTERVAL = envint("XPRA_PAINT_INTERVAL", 100)


def get_pixbuf(encoding: str, data: bytes):
    try:
        assert encoding in ("jpeg", "png", "webp")
        mime = f"image/{encoding}"
        loader = GdkPixbuf.PixbufLoader.new_with_mime_type(mime)
        loader.write(data)
        loader.close()
        return loader.get_pixbuf()
    except Exception as e:
        log("get_pixbuf(%s, %i bytes) error: %s", encoding, len(data), e)
        return get_pillow_pixbuf(encoding, data)


def get_pillow_pixbuf(encoding: str, data: bytes):
    try:
        from xpra.codecs.pillow.decoder import open_only
        img = open_only(data, encoding)
        img = img.convert("RGBA")
        w, h = img.size
        raw = GLib.Bytes.new(img.tobytes())
        return GdkPixbuf.Pixbuf.new_from_bytes(raw, GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
    except Exception as e:
        log.error("Error loading %s frame: %s", encoding, e)
        return None


def make_solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (width, height), rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestWindow:

    def __init__(self) -> None:
        self._pixbuf = None
        self._stop = threading.Event()
        self._window = Gtk.Window(title="Test Window")
        self._window.set_default_size(640, 480)
        self._window.connect("delete-event", self._on_close)
        self._area = Gtk.DrawingArea()
        self._area.connect("draw", self._on_draw)
        self._area.set_app_paintable(True)
        self._window.add(self._area)
        self._window.show_all()
        self._feed_thread = threading.Thread(target=self._feed_loop, name="solid-color-feed", daemon=True)
        self._feed_thread.start()

    # ------------------------------------------------------------------
    # GTK window

    def _on_close(self, _window, _event) -> bool:
        self.quit(ExitCode.OK)
        return False

    def quit(self, _code: int = 0) -> None:
        self._stop.set()
        Gtk.main_quit()

    def _feed_loop(self) -> None:
        width, height = 640, 480
        start = time.monotonic()
        while not self._stop.is_set():
            hue = (time.monotonic() - start) * 0.2 % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            rgb = (int(r * 255), int(g * 255), int(b * 255))
            data = make_solid_png(width, height, rgb)
            GLib.idle_add(self._update_frame, "png", data)
            self._stop.wait(INTERVAL / 1000)

    def _update_frame(self, encoding: str, data: bytes) -> None:
        self._pixbuf = get_pixbuf(encoding, data)
        if self._pixbuf:
            w, h = self._pixbuf.get_width(), self._pixbuf.get_height()
            self._window.resize(w, h)
            self._area.queue_draw()

    def _on_draw(self, _widget, ctx) -> None:
        if pixbuf := self._pixbuf:
            Gdk.cairo_set_source_pixbuf(ctx, pixbuf, 0, 0)
            ctx.paint()


def main() -> int:
    TestWindow()
    Gtk.main()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
