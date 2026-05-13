# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.client.gui.window.backing import fire_paint_callbacks
from xpra.util.env import envint
from xpra.log import Logger

log = Logger("window", "fake")

FAKE_BACKING_DELAY = envint("XPRA_FAKE_BACKING_DELAY", 5)


class FakeBacking:
    HAS_ALPHA = True

    def __init__(self, wid: int, *_args):
        self.wid = wid
        self.size = 0, 0
        self.render_size = 0, 0
        self.offsets = 0, 0, 0, 0
        self._backing = None
        self.border = None
        self.content_type = ""
        self.default_cursor_data = ()
        self.gravity = 0
        self.fake_delay = FAKE_BACKING_DELAY
        self._video_encoder = None
        self._video_encoder_lock = None
        self._video_encoder_speed = []
        self._video_encoder_quality = []

    def init(self, ww: int, wh: int, bw: int, bh: int) -> None:
        self.size = bw, bh
        self.render_size = ww, wh

    def close(self) -> None:
        self.wid = 0

    def draw_region(self, _x, _y, _width, _height, _coding, _img_data, _rowstride, _options, callbacks):
        log("draw_region(..) faking it after %sms", self.fake_delay)
        from xpra.os_util import gi_import
        GLib = gi_import("GLib")
        GLib.timeout_add(self.fake_delay, fire_paint_callbacks, callbacks, True)

    def cairo_draw(self, context, x, y):
        log("cairo_draw%s", (context, x, y))

    def get_encoding_properties(self) -> dict[str, Any]:
        return {
            "encodings.rgb_formats": ["RGBA", "RGB"],
        }
