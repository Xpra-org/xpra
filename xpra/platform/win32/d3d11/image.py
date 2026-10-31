# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from dataclasses import dataclass

from xpra.codecs.image import ImageWrapper
from xpra.log import Logger

log = Logger("shadow", "win32", "d3d11")


@dataclass(frozen=True, slots=True)
class D3D11Texture:
    """
    An area of a D3D11 texture, which GPU encoders can read from without going through system memory.
    The texture uses `DXGI_FORMAT_B8G8R8A8_UNORM`.
    """
    texture: int    # `ID3D11Texture2D*`
    device: int     # the `ID3D11Device*` it belongs to
    x: int
    y: int
    width: int
    height: int


class DXGIImageWrapper(ImageWrapper):
    """
    Wraps an area of the texture that `DXGICapture` copies each desktop frame to.
    The pixels stay on the GPU until something asks for them:

    - `freeze_on_gpu()` copies the area to a texture of its own (GPU to GPU),
      which `get_gpu_buffer()` then hands to the GPU encoders.
    - `freeze()`, `get_pixels()` and friends download the area to system memory,
      from that texture if there is one, or from the desktop texture otherwise.

    Before overwriting the desktop texture, the capture freezes images that still
    depend on it. Images downloaded or freed before then need no extra copy.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 pixel_format: str, depth: int, capture):
        bpp = depth // 8
        super().__init__(x, y, width, height, None, pixel_format, depth, width * bpp,
                         bpp, ImageWrapper.PACKED, thread_safe=False)
        self._capture = capture
        # position of this image in the capture's desktop texture:
        self._src_x = x
        self._src_y = y
        self._snapshot: D3D11Texture | None = None

    def __repr__(self) -> str:
        return "DXGIImageWrapper(%dx%d %s)" % (self.width, self.height, self.pixel_format)

    def _download(self, x: int, y: int, width: int, height: int):
        """ download an area of this image, relative to its top-left corner """
        capture = self._capture
        if not capture:
            raise RuntimeError("DXGIImageWrapper: the capture is gone")
        snapshot = self._snapshot
        if snapshot:
            return capture.download(snapshot.texture, snapshot.x + x, snapshot.y + y, width, height)
        return capture.download(0, self._src_x + x, self._src_y + y, width, height)

    def may_download(self) -> None:
        with self._lock:
            if self.pixels is not None or self.freed:
                return
            start = monotonic()
            self.pixels = self._download(0, 0, self.width, self.height)
            elapsed = monotonic() - start
            nbytes = len(self.pixels)
            mbs = nbytes / elapsed / 1024 / 1024 if elapsed > 0 else 9999
            log("may_download() %s size=%i, from %s, elapsed=%ims %.0fMB/s",
                self.pixel_format, nbytes, "snapshot" if self._snapshot else "desktop texture",
                int(1000 * elapsed), mbs)

    def get_gpu_buffer(self) -> D3D11Texture | None:
        """ only available once frozen on the GPU, the desktop texture keeps changing """
        return self._snapshot

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

    def get_sub_image(self, x: int, y: int, w: int, h: int):
        with self._lock:
            if self.pixels is None and not self.freed and (x, y, w, h) != (0, 0, self.width, self.height):
                # only download the area we need:
                if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > self.width or y + h > self.height:
                    raise ValueError(f"invalid sub-image geometry {x},{y},{w},{h} for {self.width}x{self.height}")
                bpp = self.bytesperpixel
                image = ImageWrapper(self.x + x, self.y + y, w, h, self._download(x, y, w, h),
                                     self.pixel_format, self.depth, w * bpp, bpp,
                                     planes=self.planes, thread_safe=True, full_range=self.full_range)
                image.set_target_x(self.target_x + x)
                image.set_target_y(self.target_y + y)
                return image
        self.may_download()
        return super().get_sub_image(x, y, w, h)

    def freeze(self) -> bool:
        self.may_download()
        return True

    def freeze_on_gpu(self) -> bool:
        with self._lock:
            if self.pixels is not None or self._snapshot or self.freed:
                return True
            capture = self._capture
            if capture:
                self._snapshot = capture.snapshot(self._src_x, self._src_y, self.width, self.height)
                if self._snapshot:
                    return True
        # out of snapshot textures, or the capture is gone:
        log("freeze_on_gpu() no snapshot available for %s, downloading it instead", self)
        return self.freeze()

    def preserve_before_overwrite(self) -> None:
        """ Called by the capture thread before it overwrites the desktop texture. """
        with self._lock:
            if self.freed or self._capture is None or self.pixels is not None or self._snapshot is not None:
                return
            # Keep the image locked through the fallback download if the snapshot pool is full.
            self.freeze_on_gpu()

    def free(self) -> None:
        lock = getattr(self, "_lock", None)
        if lock is None:
            return
        with lock:
            # `free()` is called more than once, and not always from the same thread:
            snapshot = getattr(self, "_snapshot", None)
            self._snapshot = None
            capture = getattr(self, "_capture", None)
            self._capture = None
            if snapshot and capture:
                capture.release_snapshot(snapshot)
        super().free()
