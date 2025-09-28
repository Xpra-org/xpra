#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic_ns

from xpra.util.system import is_Wayland
from xpra.x11.error import xlog, xsync
from xpra.log import Logger

log = Logger("x11", "shadow")


class XImageCapture:
    __slots__ = ("xshm", "xwindow", "XImage")

    def __init__(self, xwindow: int):
        log("XImageCapture(%#x)", xwindow)
        self.xshm = None
        self.xwindow = xwindow
        from xpra.x11.bindings.shm import XShmBindings  # pylint: disable=import-outside-toplevel
        shm = XShmBindings()
        if not shm or not shm.has_XShm():
            raise RuntimeError("no XShm support")
        if is_Wayland():
            log.warn("Warning: shadow servers do not support Wayland")
            log.warn(" please switch to X11 for shadow support")

    def __repr__(self):
        return f"XImageCapture({self.xwindow:x})"

    def get_type(self) -> str:
        return "XImageCapture"

    def clean(self) -> None:
        self.close_xshm()

    def close_xshm(self) -> None:
        xshm = self.xshm
        if self.xshm:
            self.xshm = None
            with xlog:
                xshm.cleanup()

    def _err(self, e, op="capture pixels") -> None:
        if getattr(e, "msg", None) == "BadMatch":
            log("BadMatch - temporary error in %s of window #%x", op, self.xwindow, exc_info=True)
        else:
            log.warn("Warning: failed to %s of window %#x:", op, self.xwindow)
            log.warn(" %s", e)
        self.close_xshm()

    def refresh(self) -> bool:
        if self.xshm:
            # discard to ensure we will call XShmGetImage next time around
            self.xshm.discard()
            return True
        try:
            with xsync:
                log("%s.refresh() xshm=%s", self, self.xshm)
                from xpra.x11.bindings.shm import XShmBindings  # pylint: disable=import-outside-toplevel
                self.xshm = XShmBindings().get_XShmWrapper(self.xwindow)
                self.xshm.setup()
        except Exception as e:
            self.xshm = None
            self._err(e, "xshm setup")
        return True

    def get_image(self, x: int, y: int, width: int, height: int):
        log("XImageCapture.get_image%s for %#x", (x, y, width, height), self.xwindow)
        if self.xshm is None:
            log("no xshm, cannot get image")
            return None
        start = monotonic_ns()
        try:
            with xsync:
                log("X11 shadow get_image, xshm=%s", self.xshm)
                image = self.xshm.get_image(self.xwindow, x, y, width, height)
                return image
        except Exception as e:
            self._err(e)
            return None
        finally:
            end = monotonic_ns()
            log("X11 shadow captured %s pixels at %i MPixels/s using %s",
                width * height, (width * height / (end - start)), ["GTK", "XSHM"][bool(self.xshm)])
