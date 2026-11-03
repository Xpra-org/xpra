# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Buffer, Callable, Sequence

from xpra.codecs.image import ImageWrapper


class CUDADecodedImageWrapper(ImageWrapper):
    """Decoded pixels kept on the device until CPU plane access is requested."""

    def __init__(self, *args, gpu_buffer, downloader: Callable[[object], Sequence[Buffer]], cuda_context, **kwargs):
        super().__init__(*args, **kwargs)
        self.cuda_device_buffer = gpu_buffer
        self.downloader = downloader
        self.cuda_context = cuda_context
        self.pbos: tuple[int, ...] = ()

    def get_gpu_buffer(self):
        return self.cuda_device_buffer

    def free_cuda(self) -> None:
        with self._lock:
            buffer = self.cuda_device_buffer
            if buffer is None:
                return
            self.cuda_device_buffer = None
            self.cuda_context.push()
            try:
                buffer.free()
            finally:
                self.cuda_context.pop()

    def may_download(self) -> None:
        with self._lock:
            if self.pixels or self.freed:
                return
            buffer = self.cuda_device_buffer
            if buffer is None:
                raise RuntimeError("CUDA image has no device buffer")
            self.cuda_context.push()
            try:
                self.set_pixels(self.downloader(buffer))
                self.free_cuda()
            finally:
                self.cuda_context.pop()

    def get_plane(self, i: int) -> Buffer:
        self.may_download()
        return super().get_plane(i)

    def clone_pixel_data(self) -> None:
        self.may_download()
        super().clone_pixel_data()

    def get_sub_image(self, x: int, y: int, w: int, h: int):
        self.may_download()
        return super().get_sub_image(x, y, w, h)

    def free(self) -> None:
        lock = getattr(self, "_lock", None)
        if lock is None:
            return
        with lock:
            if getattr(self, "cuda_device_buffer", None) is not None:
                self.free_cuda()
            super().free()
