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
    Wraps a captured DXGI frame.  Two zero-copy paths are supported:

    GPU path (no CPU involvement):
      get_gpu_buffer() returns the D3D11_USAGE_DEFAULT texture pointer
      (_gpu_ptr).  GPU encoders (e.g. MF VideoProcessor) read from it
      directly without any CPU readback.

    CPU path (lazy):
      get_pixels() / may_download() triggers a GPU->staging copy followed
      by Map/memcpy/Unmap.  The staging texture is only touched when this
      path is taken.

    Lifecycle:
      - Constructed by DXGICapture.get_image().
      - may_download() maps the staging texture, copies pixels to bytes,
        unmaps.  Sets _mapped=True while the staging is live, False after.
      - free() calls _unmap only if the staging is currently mapped
        (_mapped=True), avoiding Unmap calls on a never-mapped texture.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 pixel_format: str, depth: int, rowstride: int,
                 map_pixels,        # callable() -> bytes, or raises
                 unmap,             # callable() — called after map_pixels
                 gpu_ptr: int = 0):
        super().__init__(x, y, width, height, None, pixel_format, depth, rowstride,
                         depth // 8, ImageWrapper.PACKED, thread_safe=False)
        self._map_pixels = map_pixels
        self._unmap = unmap
        self._gpu_ptr = gpu_ptr
        self._mapped = False   # True only while staging texture is mapped

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
            self._mapped = True     # staging is now mapped (Map succeeded)
            self.pixels = bytes(data)
        finally:
            # Unmap only if Map actually succeeded; if _map_pixels raised,
            # _mapped is still False and the staging was never mapped.
            if self._unmap and self._mapped:
                self._unmap()
                self._mapped = False
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
        """Return the D3D11_USAGE_DEFAULT texture pointer, or None.
        This texture is GPU-accessible and can be fed directly to GPU
        encoders (e.g. ID3D11VideoProcessor, MF VideoProcessorMFT).
        It is NOT CPU-mapped and does not require any staging copy."""
        return self._gpu_ptr or None

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
        # Only unmap if the staging texture is currently mapped.
        # If may_download() was never called, _mapped is False and the
        # staging was never mapped — calling Unmap would be incorrect.
        if self._unmap and self._mapped:
            try:
                self._unmap()
            except Exception:
                log("DXGIImageWrapper.free() unmap error", exc_info=True)
        self._unmap = None
        self._map_pixels = None
        self._mapped = False
        self._gpu_ptr = 0
        super().free()
