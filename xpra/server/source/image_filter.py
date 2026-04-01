# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Callable
from time import sleep
from typing import Any

from xpra.server.source.stub import StubClientConnection
from xpra.server.window.compress import WindowSource, free_image_wrapper
from xpra.codecs.loader import load_codec
from xpra.codecs.image import ImageWrapper
from xpra.util.str_fn import csv
from xpra.util.thread import start_thread
from xpra.util.env import envbool, envint
from xpra.util.objects import typedict
from xpra.log import Logger


log = Logger("window", "events", "filter")
# CONTENT_TYPES = set(os.environ.get("XPRA_IMAGEFILTER_CONTENT_TYPES", "text").split(","))
CONTENT_TYPES = set(ct for ct in os.environ.get("XPRA_IMAGEFILTER_CONTENT_TYPES", "").split(",") if ct)
WINDOW_TYPES = set(ct for ct in os.environ.get("XPRA_IMAGEFILTER_WINDOW_TYPES", "").split(",") if ct)
MODULES = os.environ.get("XPRA_IMAGEFILTER_MODULES", "torch,pillow").split(",")
DELAY = envint("XPRA_IMAGE_FILTER_DELAY", 0)
THREADED_FILTERS = tuple(os.environ.get("XPRA_THREADED_FILTERS", "torch").split(","))
TIMEOUT = envint("XPRA_THREADED_FILTER_TIMEOUT", 5)


class ImageFilter:
    def __init__(self, wid: int, imagefilter):
        self.wid = wid
        self.filter = imagefilter
        filter_type = imagefilter.get_info().get("type", "")
        self.threaded = "*" in THREADED_FILTERS or filter_type in THREADED_FILTERS
        self.thread = None
        log("ImageFilter(%#x, %s) filter_type=%s, threaded=%s", wid, imagefilter, filter_type, self.threaded)

    def process_image(self, image: ImageWrapper, callback: Callable[[ImageWrapper], None]) -> None:
        log("%s.process_image(%s, %s)", self, image, callback)
        if not self.threaded:
            self.do_process_image(image, callback)
            return
        if not self.wait_for_thread():
            free_image_wrapper(image)
            return
        self.thread = start_thread(self.do_process_image, "image-filter-process-image-%#x" % self.wid,
                                   daemon=True, args=(image, callback))

    def do_process_image(self, image: ImageWrapper, callback: Callable[[ImageWrapper], None]) -> None:
        if DELAY > 0:
            sleep(DELAY / 1000)
        filtered = self.filter.convert_image(image)
        free_image_wrapper(image)
        callback(filtered)

    def clean(self) -> None:
        self.wait_for_thread()
        filt = self.filter
        if filt:
            self.filter = None
            filt.clean()

    def wait_for_thread(self) -> bool:
        t = self.thread
        if not t:
            return True
        t.join(timeout=TIMEOUT)
        if t.is_alive():
            log.error("Error: image filter thread timeout")
            return False
        self.thread = None
        return True

    def __repr__(self):
        return "ImageFilter(%#x, %s)" % (self.wid, self.filter)


class ImageFilterConnection(StubClientConnection):
    """
    Can modify window pixels before compression
    """
    PREFIX = "imagefilter"

    FAILED_FILTERS: set[str] = set()

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        ifilt = envbool("XPRA_WINDOW_IMAGE_FILTER", bool(CONTENT_TYPES) or bool(WINDOW_TYPES))
        return caps.boolget("imagefilter", ifilt)

    def __init__(self):
        super().__init__()
        for mod in MODULES:
            if mod in ImageFilterConnection.FAILED_FILTERS:
                log("%s in FAILED_FILTERS", mod)
                self.filter_module = None
            else:
                self.filter_module = load_codec(f"filter_{mod}")
            log("filter(%s)=%s", mod, self.filter_module)
            if self.filter_module:
                break
            ImageFilterConnection.FAILED_FILTERS.add(mod)
        if not self.filter_module:
            log.warn("Warning: no imagefilter modules found, tried: %s", csv(MODULES))

    def init_state(self) -> None:
        if not self.filter_module:
            return
        self.connect("new-window-source", self.initialize_imagefilter)
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
        if "*" not in CONTENT_TYPES and not (CONTENT_TYPES & set(ws.content_types)):
            return
        window_types = ws.window.get("window-type")
        log("WINDOW_TYPES=%s, window: %s", csv(WINDOW_TYPES), csv(window_types))
        if "*" not in WINDOW_TYPES and not (WINDOW_TYPES & set(window_types)):
            return
        options = typedict({})
        width, height = ws.window_dimensions
        ifilt = self.filter_module.Filter()
        ifilt.init_context(width, height, "BGRX", width, height, "BGRX", options)
        ws.image_filter = ImageFilter(ws.wid, ifilt)
        log("imagefilter for window %#x %ix%i: %s", ws.wid, width, height, ws.image_filter)

        def resized() -> None:
            self.clean_imagefilter(ss, ws)
            self.initialize_imagefilter(ss, ws)
        ws.window_dimensions_updated = resized

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
