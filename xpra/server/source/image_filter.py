# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.server.source.stub import StubClientConnection
from xpra.server.window.compress import WindowSource
from xpra.codecs.loader import load_codec
from xpra.codecs.image import ImageWrapper
from xpra.util.str_fn import csv
from xpra.util.env import envbool
from xpra.util.objects import typedict
from xpra.log import Logger


log = Logger("window", "events")
# CONTENT_TYPES = set(os.environ.get("XPRA_IMAGEFILTER_CONTENT_TYPES", "text").split(","))
CONTENT_TYPES = set(ct for ct in os.environ.get("XPRA_IMAGEFILTER_CONTENT_TYPES", "").split(",") if ct)
MODULES = os.environ.get("XPRA_IMAGEFILTER_MODULES", "torch,pillow").split(",")


class ImageFilter:
    def __init__(self, wid: int, filter):
        self.wid = wid
        self.filter = filter

    def process_image(self, image: ImageWrapper) -> ImageWrapper:
        return self.filter.convert_image(image)

    def clean(self) -> None:
        filt = self.filter
        if filt:
            self.filter = None
            filt.clean()

    def __repr__(self):
        return "ImageFilter(%#x, %s)" % (self.wid, self.filter)


class ImageFilterConnection(StubClientConnection):
    """
    Can modify window pixels before compression
    """
    PREFIX = "imagefilter"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        ifilt = envbool("XPRA_WINDOW_IMAGE_FILTER", bool(CONTENT_TYPES))
        return caps.boolget("imagefilter", ifilt)

    def __init__(self):
        super().__init__()
        for mod in MODULES:
            self.filter_module = load_codec(f"filter_{mod}")
            log("filter(%s)=%s", mod, self.filter_module)
            if self.filter_module:
                break
        if not self.filter_module:
            log.warn("Warning: no imagefilter modules found")

    def init_state(self) -> None:
        if not self.filter_module:
            return
        self.connect("new-window-source", self.initialize_imagefilter)
        self.connect("resize-window-source", self.resize_imagefilter)
        self.connect("remove-window-source", self.clean_imagefilter)

    def get_caps(self) -> dict[str, Any]:
        return {}

    def get_info(self) -> dict[str, Any]:
        info = {}
        if self.filter_module:
            info["filter-module"] = self.filter_module.get_info()
        return {ImageFilterConnection.PREFIX: info}

    def initialize_imagefilter(self, ss, ws: WindowSource) -> None:
        log("initialize_imagefilter(%s, %s) depth=%i", ss, ws, ws.image_depth)
        if ws.image_depth not in (24, 32):
            return
        log("CONTENT_TYPES=%s, window: %s", csv(CONTENT_TYPES), csv(ws.content_types))
        if "*" in CONTENT_TYPES or CONTENT_TYPES & set(ws.content_types):
            options = typedict({})
            width, height = ws.window_dimensions
            ifilt = self.filter_module.Filter()
            ifilt.init_context(width, height, "BGRX", width, height, "BGRX", options)
            ws.image_filter = ImageFilter(ws.wid, ifilt)
            log("imagefilter for window %i %ix%i: %s", ws.wid, width, height, ws.image_filter)

    def resize_imagefilter(self, ss, ws: WindowSource) -> None:
        log.warn("imagefilter: resize!")
        self.clean_imagefilter(ss, ws)
        self.initialize_imagefilter(ss, ws)

    def clean_imagefilter(self, ss, ws: WindowSource) -> None:
        ifilt = ws.image_filter
        log("clean_imagefilter(%s, %s) image_filter=%s", ss, ws, ifilt)
        if ifilt:
            ws.image_filter = None
            ifilt.clean()
