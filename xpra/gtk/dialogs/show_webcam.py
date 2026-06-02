#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


import sys

from xpra.os_util import gi_import
from xpra.util.str_fn import memoryview_to_bytes
from xpra.codecs.image import ImageWrapper
from xpra.log import Logger

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GdkPixbuf = gi_import("GdkPixbuf")
GLib = gi_import("GLib")

log = Logger("webcam")

DISPLAY_FORMATS = ("RGB", "RGBX")
PACKED_BGR_FORMATS = ("BGR", "BGRX")
CSC_FORMATS = DISPLAY_FORMATS + ("BGRX",)
FRAME_DELAY = 30


def pixels_to_bytes(pixels) -> bytes:
    if isinstance(pixels, bytes):
        return pixels
    if isinstance(pixels, bytearray):
        return bytes(pixels)
    try:
        return memoryview(pixels).tobytes()
    except TypeError:
        return memoryview_to_bytes(pixels)


def to_rgb(image: ImageWrapper) -> ImageWrapper:
    pixel_format = image.get_pixel_format()
    w, h = image.get_width(), image.get_height()
    src = pixels_to_bytes(image.get_pixels())
    if pixel_format == "BGR":
        from xpra.codecs.argb.argb import bgr_to_rgb
        rgb = bgr_to_rgb(src)
    elif pixel_format in ("BGRX", "BGRA"):
        # BGRX / BGRA: drop the X/A byte and swap B↔R
        from xpra.codecs.argb.argb import bgra_to_rgb
        rgb = bgra_to_rgb(src)
    else:
        raise RuntimeError("unsupported pixel format %r" % pixel_format)
    return ImageWrapper(0, 0, w, h, rgb, "RGB", 24, w * 3, 3,
                        planes=ImageWrapper.PACKED)


class WebcamWindow(Gtk.Window):

    def __init__(self, camera, device_str: str):
        super().__init__(title=f"Webcam ({device_str})")
        self.camera = camera
        self.csc = None
        self.csc_key = None
        self.pixbuf = None
        self.timer = 0

        self.set_default_size(640, 480)
        self.connect("delete-event", self.close)
        self.area = Gtk.DrawingArea()
        self.area.set_app_paintable(True)
        self.area.connect("draw", self.draw)
        self.add(self.area)

    def start(self) -> None:
        self.timer = GLib.timeout_add(FRAME_DELAY, self.update_frame)

    def close(self, *_args) -> bool:
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.csc:
            self.csc.clean()
            self.csc = None
        self.camera.release()
        Gtk.main_quit()
        return False

    def stop(self) -> None:
        self.timer = 0
        if self.csc:
            self.csc.clean()
            self.csc = None
        self.camera.release()
        Gtk.main_quit()

    def get_display_image(self, image: ImageWrapper):
        pixel_format = image.get_pixel_format()
        if pixel_format in DISPLAY_FORMATS:
            return image
        if pixel_format in PACKED_BGR_FORMATS:
            return to_rgb(image)
        w, h = image.get_width(), image.get_height()
        key = pixel_format, w, h
        if key != self.csc_key:
            if self.csc:
                self.csc.clean()
            from xpra.webcam import make_csc
            self.csc = make_csc(pixel_format, w, h, CSC_FORMATS)
            self.csc_key = key
        if self.csc:
            csc_image = self.csc.convert_image(image)
            if csc_image.get_pixel_format() in PACKED_BGR_FORMATS:
                return to_rgb(csc_image)
            return csc_image
        return None

    def update_frame(self) -> bool:
        try:
            image = self.camera.read()
            if image is None:
                return True
            image = self.get_display_image(image)
            if image is None:
                return True

            pixel_format = image.get_pixel_format()
            w, h = image.get_width(), image.get_height()
            rowstride = image.get_rowstride()
            pixels = pixels_to_bytes(image.get_pixels())
            has_alpha = pixel_format == "RGBX"
            raw = GLib.Bytes.new(pixels)
            self.pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(raw, GdkPixbuf.Colorspace.RGB,
                                                          has_alpha, 8, w, h, rowstride)
            self.resize(w, h)
            self.area.queue_draw()
            return True
        except Exception as e:
            log.error("Error updating webcam frame: %s", e, exc_info=True)
            self.stop()
            return False

    def draw(self, _widget, ctx) -> None:
        if self.pixbuf:
            Gdk.cairo_set_source_pixbuf(ctx, self.pixbuf, 0, 0)
            ctx.paint()


def main(argv: list[str]) -> int:
    from xpra.platform import program_context, command_error
    from xpra.platform.gui import init, ready, set_default_icon
    with program_context("Webcam", "Webcam"):
        from xpra.log import consume_verbose_argv
        consume_verbose_argv(argv, "webcam")
        set_default_icon("webcam.png")
        init()

        device_str = "auto"
        if len(argv) == 2:
            device_str = argv[1]
        elif len(argv) > 2:
            command_error("Error: too many arguments")
            return 1

        log("opening webcam device %r", device_str)
        from xpra.webcam import open_camera
        try:
            camera = open_camera(device_str)
        except Exception as e:
            command_error(f"Error: failed to open webcam device {device_str!r}:\n{e}")
            return 1
        if camera is None:
            command_error(f"Error: failed to open webcam device {device_str!r}")
            return 1

        window = WebcamWindow(camera, device_str)
        window.show_all()
        window.start()
        ready()
        Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
