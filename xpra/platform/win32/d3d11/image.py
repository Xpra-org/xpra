# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from xpra.codecs.image import ImageWrapper
from xpra.log import Logger

log = Logger("shadow", "win32", "d3d11")


class DXGIImageWrapper(ImageWrapper):
    """
    An area of a DXGI desktop capture, downloaded when CPU pixels are needed.
    Keep the capture alive and let it serialize downloads with capture cleanup.
    The desktop texture changes on refresh, so it cannot be used as a frozen GPU buffer.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 pixel_format: str, depth: int, capture):
        bpp = depth // 8
        super().__init__(x, y, width, height, None, pixel_format, depth, width * bpp,
                         bpp, ImageWrapper.PACKED, thread_safe=False)
        self._capture = capture
        self._src_x = x
        self._src_y = y

    def __repr__(self) -> str:
        return "DXGIImageWrapper(%dx%d %s)" % (self.width, self.height, self.pixel_format)

    def may_download(self) -> None:
        with self._lock:
            if self.pixels is not None or self.freed:
                return
            capture = self._capture
            if capture is None:
                raise RuntimeError("DXGIImageWrapper: the capture is gone")
            start = monotonic()
            self.pixels = capture.download(self._src_x, self._src_y, self.width, self.height)
            elapsed = monotonic() - start
            nbytes = len(self.pixels)
            mbs = nbytes / elapsed / 1024 / 1024 if elapsed > 0 else 9999
            log("may_download() %s size=%i, elapsed=%ims %.0fMB/s",
                self.pixel_format, nbytes, int(1000 * elapsed), mbs)

    def get_pixels(self):
        self.may_download()
        return super().get_pixels()

    def clone_pixel_data(self) -> None:
        self.may_download()
        super().clone_pixel_data()

    def may_restride(self) -> bool:
        self.may_download()
        return super().may_restride()

    def restride(self, rowstride: int) -> bool:
        self.may_download()
        return super().restride(rowstride)

    def get_sub_image(self, x, y, w, h):
        self.may_download()
        return super().get_sub_image(x, y, w, h)

    def freeze(self) -> bool:
        self.may_download()
        return True

    def free(self) -> None:
        lock = getattr(self, "_lock", None)
        if lock is None:
            return
        with lock:
            self._capture = None
            super().free()
