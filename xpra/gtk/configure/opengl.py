# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import struct
from typing import Any

from xpra.common import noop, PaintCallbacks
from xpra.os_util import gi_import, WIN32
from xpra.codecs.loader import load_codec
from xpra.util.objects import typedict
from xpra.platform.paths import get_image, get_image_dir
from xpra.util.io import load_binary_file
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.configure.common import sync, run_gui
from xpra.util.config import get_user_config_file, parse_user_config_file, save_user_config_file
from xpra.log import Logger

Gtk = gi_import("Gtk")

log = Logger("opengl", "util")

WW = 640
WH = 480


def BGRA(b: int, g: int, r: int, a: int):
    return struct.pack("@BBBB", b, g, r, a)


def BGR(b: int, g: int, r: int):
    return struct.pack("@BBB", b, g, r)


def draw_data(x: int, y: int, w: int, h: int, pixel_data: bytes):
    coding = "rgb32" if len(pixel_data) == 4 else "rgb24"
    rgb_format = "BGRX" if len(pixel_data) == 4 else "BGR"
    return (
        x, y, w, h,
        coding, pixel_data*w*h, len(pixel_data)*w, {"rgb_format": rgb_format}
    )


CLEAR = (
    "white background",
    (
        draw_data(0, 0, WW, WH, BGRA(0xff, 0xff, 0xff, 0xff)),
    ),
)

TEST_STEPS = [
    CLEAR,
    (
        "a grey square in the top left corner",
        (
            draw_data(0, 0, 128, 128, BGR(0x80, 0x80, 0x80)),
        ),
    ),
    (
        "four squares dividing the screen, red, green, blue and grey",
        (
            draw_data(0, 0, WW//2, WH//2, BGR(0, 0, 0xFF)),
            draw_data(WW//2, 0, WW//2, WH//2, BGR(0, 0xFF, 0)),
            draw_data(WW//2, WH//2, WW//2, WH//2, BGR(0xFF, 0, 0)),
            draw_data(0, WH//2, WW//2, WH//2, BGR(0x40, 0x40, 0x40)),
        ),
    ),
]


def load_image(name: str) -> tuple[int, int, bytes]:
    filename = os.path.join(get_image_dir(), name)
    image_data = load_binary_file(filename)
    w = h = 0
    if image_data:
        try:
            from PIL import Image
            img = Image.open(filename)
            w = int(img.width)
            h = int(img.height)
            img.close()
        except ImportError:
            img = get_image(filename)
            if img:
                w = int(img.get_width())
                h = int(img.get_height())
    return w, h, image_data


def add_test_images():
    encodings = []
    for decoder_name in ("pillow", "jpeg", "webp", "spng", "avif"):
        decoder = load_codec(f"dec_{decoder_name}")
        if decoder:
            encodings += decoder.get_encodings()

    for name, description in {
        "smpte-rp-219.png": "smpte-rp-219 test bars (png)",
        "pinwheel.jpg": "pinwheel pattern (jpeg)",
        "gradient.webp": "gradient pattern (webp)",
    }.items():
        encoding = name.split(".")[-1]
        if encoding not in encodings:
            continue
        width, height, image_data = load_image(name)
        options: dict[str, str] = {}
        if width and height and image_data:
            paint_data = (
                0, 0, width, height,
                encoding, bytes(image_data), 0, options,
            )
            TEST_STEPS.append((description, (paint_data, )))


add_test_images()


def create_twin_test_windows(parent: Gtk.Window) -> tuple[dict[str, Any], list[Gtk.Window]]:
    from xpra.gtk.window import add_close_accel
    from xpra.client.gui.fake_client import FakeClient
    from xpra.client.gui.window_border import WindowBorder
    from xpra.opengl.window import get_gl_client_window_module
    from xpra.client.gtk3.window import ClientWindow
    opengl_props, gl_client_window_module = get_gl_client_window_module("force")
    if not gl_client_window_module:
        return opengl_props, []
    gl_window_class = gl_client_window_module.GLClientWindow
    pixel_depth = 0  # int(opts.pixel_depth)
    wid = 10000
    noclient = FakeClient()
    noclient._id_to_window[wid] = parent
    ww, wh = WW, WH
    metadata = typedict({
        # prevent resizing:
        "maximum-size": (WW, WH),
        "minimum-size": (WW, WH),
        "modal": True,
        "has-alpha": not WIN32,
        "transient-for": wid,
    })
    border = WindowBorder(False)
    max_window_size = None  # (1024, 1024)
    default_cursor_data = None
    windows: list[Gtk.Window] = []
    for i, window_class, title in (
        (0, gl_window_class, "OpenGL Window"),
        (1, ClientWindow, "Non-OpenGL Window"),
    ):
        x, y = 100+ww*i, 100
        window = window_class(noclient, None, 0, 2 ** 32 - 1, x, y, ww, wh, ww, wh,
                              metadata, False, typedict({}),
                              border, max_window_size, default_cursor_data, pixel_depth,
                              )
        window.set_title(title)
        windows.append(window)

        # make sure these windows stay open:
        add_close_accel(window, noop)
    return opengl_props, windows


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        self.opengl_props = {}
        self.windows = []
        self.test_steps = TEST_STEPS
        self.step = 0
        super().__init__(
            "Configure Xpra's OpenGL Renderer",
            "opengl.png",
            wm_class=("xpra-configure-opengl-gui", "Xpra Configure OpenGL GUI"),
            header_bar=(False, False),
            parent=parent,
        )

    def dismiss(self, *args):
        self.close_test_windows()
        super().dismiss()

    def populate(self):
        self.populate_form(
            (
                "This tool can cause your system to crash if your GPU drivers are buggy.",
                "Use with caution.",
                "",
                "Enabling the OpenGL renderer can improve the framerate and general performance of the client.",
                "Your xpra client will also be able to skip its OpenGL self-tests and start faster.",
            ),
            ("Proceed", self.start_test),
            ("Exit", self.dismiss),
        )

    def start_test(self, *_args):
        sync()
        self.opengl_props, self.windows = create_twin_test_windows(self)
        if not self.windows:
            log.warn(f"{self.opengl_props=}")
            self.populate_form(
                (
                    "Xpra was unable to intialize the test windows",
                ),
                ("Exit", self.dismiss),
            )
            return
        glp = typedict(self.opengl_props)
        version = ".".join(str(x) for x in glp.inttupleget("opengl", ()))
        renderer = glp.get("renderer", "unknown").split(";")[0]
        backend = glp.get("backend", "unknown")
        vendor = glp.get("vendor", "unknown vendor")
        glinfo = f"OpenGL {version} has been initialized using the {backend!r} backend" + \
            f"and {renderer!r} driver from {vendor}"
        self.populate_form(
            (
                glinfo,
                "",
                "This tool will now present two windows which will be painted using various picture encodings.",
                "You will be asked to confirm that the rendering was correct and identical in both windows.",
                "",
                "Try to arrange them side by side to make it easier to compare.",
            ),
            ("Understood", self.paint_step),
            ("Exit", self.dismiss),
        )

    def paint_step(self, *_args):
        for window in self.windows:
            window.show()
            window.present()
        step_data = self.test_steps[self.step]
        description = step_data[0]
        self.paint_twin_windows(*CLEAR)
        self.paint_twin_windows(*step_data)
        self.populate_form(
            (
                "Please compare the two windows.",
                "They should be indistinguishable from each other.",
                "The colors and content should look 100% identical.",
                "",
                "The windows should be both showing:",
                description,
            ),
            ("Restart", self.restart),
            ("Identical", self.test_passed),
            ("Not identical", self.test_failed),
        )

    def paint_twin_windows(self, description: str, paint_data: tuple):
        log("paint_twin_windows() %r", description)
        callbacks: PaintCallbacks = []
        for x, y, w, h, encoding, img_data, rowstride, options in paint_data:
            for window in self.windows:
                window.draw_region(x, y, w, h, encoding, img_data, rowstride, typedict(options), callbacks)

    def restart(self, *_args):
        self.close_test_windows()
        self.start_test()

    def close_test_windows(self):
        for window in self.windows:
            try:
                window.destroy()
            except Exception:
                log.warn(f"Warning: error closing window {window}", exc_info=True)
        self.windows = []

    def test_passed(self, *_args):
        log("test_passed()")
        self.step += 1
        if self.step < len(self.test_steps):
            self.paint_step()
            return
        # reached the last step!
        self.close_test_windows()
        self.populate_form(
            (
                "OpenGL can be enabled safely using this GPU.",
                "",
                "You can revert this change by running this tool again, or by resetting your user configuration."
            ),
            ("Enable OpenGL", self.enable_opengl),
            ("Exit", self.dismiss),
        )

    def enable_opengl(self, *_args):
        config = parse_user_config_file()
        config["opengl"] = "noprobe"
        save_user_config_file(config)
        self.populate_form(
            (
                "OpenGL is now enabled in your user's xpra configuration file:",
                "'%s'" % get_user_config_file(),
                "If you experience issues later, you may want to reset your configuration.",
            ),
            ("Exit", self.dismiss),
        )

    def test_failed(self, *_args):
        description = self.test_steps[self.step][0]
        self.populate_form(
            (
                "Please report this issue at https://github.com/Xpra-org/xpra/issues/new/choose",
                "",
                f"The test failed on step: {description!r}",
                "Please try to include a screenshot covering both windows",
            ),
            ("Exit", self.dismiss),
        )


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
