# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import monotonic
from collections.abc import Callable, Sequence

from xpra.util.io import osclose
from xpra.codecs.image import ImageWrapper
from xpra.util.thread import check_main_thread
from xpra.log import Logger

log = Logger("dmabuf")


class DMABufImageWrapper(ImageWrapper):
    """
    Image wrapper for Linux dmabuf-backed frames.

    Like CUDAImageWrapper, CPU pixel access triggers may_download().  For now
    the Wayland capture path calls may_download() immediately after
    construction, but keeping the lazy path here preserves the future contract.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 drm_format: int, modifier: int,
                 fds: Sequence[int], strides: Sequence[int], offsets: Sequence[int],
                 downloader: Callable[[], ImageWrapper | None] | None = None,
                 pixel_format: str = "DMABUF", depth: int = 0,
                 bytesperpixel: int = 0, full_range=True):
        rowstride = tuple(strides)
        super().__init__(x, y, width, height, None, pixel_format, depth, rowstride,
                         bytesperpixel, ImageWrapper.PACKED, True, None, full_range)
        self.drm_format = drm_format
        self.modifier = modifier
        self.fds = tuple(os.dup(fd) for fd in fds)
        self.strides = tuple(strides)
        self.offsets = tuple(offsets)
        self.downloader = downloader

    def __repr__(self) -> str:
        return "%s(%#x:%s:%s:%s)" % (
            self._cn(), self.drm_format, self.get_geometry(), self.strides, len(self.fds),
        )

    def get_gpu_buffer(self):
        return self

    def has_pixels(self) -> bool:
        return self.pixels is not None

    def get_dmabuf_info(self) -> dict:
        return {
            "format": self.drm_format,
            "modifier": self.modifier,
            "fds": self.fds,
            "strides": self.strides,
            "offsets": self.offsets,
            "planes": len(self.fds),
        }

    def close_fds(self) -> None:
        if fds := self.fds:
            self.fds = ()
            osclose(*fds)

    def may_download(self) -> None:
        if self.pixels is not None or self.freed:
            return
        check_main_thread()
        if not self.downloader:
            raise RuntimeError("no dmabuf downloader is available")
        start = monotonic()
        image = self.downloader()
        if image is None:
            raise RuntimeError("dmabuf download failed")
        self.pixels = image.get_pixels()
        self.pixel_format = image.get_pixel_format()
        self.depth = image.get_depth()
        self.rowstride = image.get_rowstride()
        self.bytesperpixel = image.get_bytesperpixel()
        self.planes = image.get_planes()
        self.palette = image.get_palette()
        self.full_range = image.get_full_range()
        self.close_fds()
        self.downloader = None
        elapsed = monotonic() - start
        log("may_download() format=%#x, modifier=%#x, size=%ix%i, elapsed=%ims",
            self.drm_format, self.modifier, self.width, self.height, int(1000 * elapsed))

    def get_pixels(self):
        self.may_download()
        return super().get_pixels()

    def clone_pixel_data(self) -> None:
        self.may_download()
        super().clone_pixel_data()

    def get_sub_image(self, x, y, w, h):
        self.may_download()
        return super().get_sub_image(x, y, w, h)

    def free(self) -> None:
        self.close_fds()
        self.downloader = None
        super().free()
