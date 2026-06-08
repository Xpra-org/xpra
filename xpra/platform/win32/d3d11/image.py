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
    Wraps a D3D11 staging texture that has already been GPU-copied from the
    desktop duplication surface.  CPU pixel data is obtained lazily via
    may_download() so GPU-capable encoders can bypass the readback entirely.

    Lifecycle:
      - Constructed by DXGICapture.get_image() holding a pointer to the
        staging texture and a MapPixels callable.
      - may_download() maps the texture, copies to bytes, unmaps.
      - free() calls the unmap callable if download was never done.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 pixel_format: str, depth: int, rowstride: int,
                 map_pixels,        # callable() -> memoryview | bytes, or raises
                 unmap,             # callable() — always called after map_pixels
                 staging_ptr: int = 0):
        super().__init__(x, y, width, height, None, pixel_format, depth, rowstride,
                         depth // 8, ImageWrapper.PACKED, thread_safe=False)
        self._map_pixels = map_pixels
        self._unmap = unmap
        self._staging_ptr = staging_ptr

    def __repr__(self) -> str:
        return "DXGIImageWrapper(%dx%d %s)" % (self.width, self.height, self.pixel_format)

    def may_download(self) -> None:
        if self.pixels is not None or self.freed:
            return
        if not self._map_pixels:
            raise RuntimeError("DXGIImageWrapper: no map function available")
        start = monotonic()
        try:
            data = self._map_pixels()
            self.pixels = bytes(data)
        finally:
            if self._unmap:
                self._unmap()
                self._unmap = None
            self._map_pixels = None
        elapsed = monotonic() - start
        nbytes = len(self.pixels)
        if elapsed > 0:
            mbs = nbytes / elapsed / 1024 / 1024
        else:
            mbs = 9999
        log("may_download() %s size=%i, elapsed=%ims %.0fMB/s",
            self.pixel_format, nbytes, int(1000 * elapsed), mbs)

    def get_gpu_buffer(self):
        return self._staging_ptr or None

    def has_pixels(self) -> bool:
        return self.pixels is not None

    def get_pixels(self):
        self.may_download()
        return super().get_pixels()

    def clone_pixel_data(self) -> None:
        self.may_download()
        super().clone_pixel_data()

    def get_sub_image(self, x, y, w, h):
        self.may_download()
        return super().get_sub_image(x, y, w, h)

    def freeze(self) -> bool:
        self.may_download()
        return True

    def free(self) -> None:
        if self._unmap:
            try:
                self._unmap()
            except Exception:
                log("DXGIImageWrapper.free() unmap error", exc_info=True)
            self._unmap = None
        self._map_pixels = None
        self._staging_ptr = 0
        super().free()
