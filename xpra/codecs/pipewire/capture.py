# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import fcntl
import mmap
import os
import threading
from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.codecs.image import ImageWrapper
from xpra.codecs.dmabuf.image import DMABufImageWrapper
from xpra.util.gobject import n_arg_signal
from xpra.log import Logger

GLib = gi_import("GLib")
GObject = gi_import("GObject")
log = Logger("encoder")

PACKED_FORMATS = ("BGRX", "BGRA", "RGBX", "RGBA")
DRM_FORMAT_MOD_LINEAR = 0
DMA_BUF_IOCTL_SYNC = 0x40086200
DMA_BUF_SYNC_READ = 1 << 0
DMA_BUF_SYNC_START = 0 << 2
DMA_BUF_SYNC_END = 1 << 2


def get_native_capture_class():
    try:
        from xpra.codecs.pipewire._native import NativeCapture
    except ImportError as e:
        raise RuntimeError(
            "native PipeWire capture is unavailable; rebuild Xpra with --with-pipewire"
        ) from e
    return NativeCapture


def make_cpu_image(data, offset: int, size: int, width: int, height: int,
                   stride: int, pixel_format: str) -> ImageWrapper:
    if pixel_format not in PACKED_FORMATS:
        raise ValueError(f"unsupported PipeWire pixel format {pixel_format!r}")
    if width <= 0 or height <= 0 or stride < width * 4:
        raise ValueError(f"invalid PipeWire frame layout: {width}x{height}, stride={stride}")
    view = memoryview(data)
    required = stride * height
    if offset < 0 or size < required or offset + required > len(view):
        raise ValueError(f"invalid PipeWire chunk: offset={offset}, size={size}, required={required}")
    pixels = bytes(view[offset:offset + required])
    return ImageWrapper(0, 0, width, height, pixels, pixel_format, 32, stride, 4,
                        ImageWrapper.PACKED, True)


def download_dmabuf(fd: int, offset: int, stride: int, width: int, height: int,
                    pixel_format: str, modifier: int) -> ImageWrapper:
    if modifier != DRM_FORMAT_MOD_LINEAR:
        raise ValueError(f"unsupported DMA-BUF modifier {modifier:#x}")
    if pixel_format not in PACKED_FORMATS or stride < width * 4:
        raise ValueError(f"unsupported DMA-BUF layout: {pixel_format}, stride={stride}")
    length = offset + stride * height
    flags = DMA_BUF_SYNC_READ | DMA_BUF_SYNC_START
    try:
        fcntl.ioctl(fd, DMA_BUF_IOCTL_SYNC, flags.to_bytes(8, "little"))
    except OSError:
        # Some linear exporters (and test files) do not implement synchronization.
        pass
    try:
        with mmap.mmap(fd, length, access=mmap.ACCESS_READ) as mapped:
            pixels = bytes(mapped[offset:length])
    finally:
        flags = DMA_BUF_SYNC_READ | DMA_BUF_SYNC_END
        try:
            fcntl.ioctl(fd, DMA_BUF_IOCTL_SYNC, flags.to_bytes(8, "little"))
        except OSError:
            pass
    return ImageWrapper(0, 0, width, height, pixels, pixel_format, 32, stride, 4,
                        ImageWrapper.PACKED, True)


class Capture(GObject.GObject):
    __gsignals__ = {
        "new-image": n_arg_signal(3),
        "state-changed": n_arg_signal(1),
        "error": n_arg_signal(1),
    }

    def __init__(self, fd: int, node_id: int, width: int = 0, height: int = 0,
                 backend_factory: Callable | None = None):
        super().__init__()
        self.node_id = node_id
        self.width = width
        self.height = height
        self.pixel_format = ""
        self.frames = 0
        self.state = "stopped"
        self._image: ImageWrapper | None = None
        self._lock = threading.Lock()
        self._refresh_pending = False
        self._cleaned = False
        if backend_factory is None:
            try:
                backend_factory = get_native_capture_class()
            except RuntimeError:
                os.close(fd)
                raise
        try:
            self._backend = backend_factory(fd, node_id, self)
        except Exception:
            os.close(fd)
            raise

    def __repr__(self) -> str:
        return f"pipewire.Capture({self.node_id}, {self.pixel_format or 'unnegotiated'})"

    def start(self) -> None:
        if self._cleaned or self.state != "stopped":
            return
        self.state = "starting"
        self._backend.start()

    def stop(self) -> None:
        self.clean()

    def clean(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        with self._lock:
            image, self._image = self._image, None
        if image:
            image.free()
        backend, self._backend = self._backend, None
        if backend:
            backend.clean()
        self.state = "stopped"

    def get_image(self, _x=0, _y=0, _width=0, _height=0) -> ImageWrapper | None:
        with self._lock:
            image, self._image = self._image, None
        return image

    def refresh(self) -> bool:
        with self._lock:
            return self._image is not None

    def get_info(self) -> dict:
        info = {
            "type": "pipewire", "node-id": self.node_id, "state": self.state,
            "frames": self.frames, "width": self.width, "height": self.height,
            "pixel-format": self.pixel_format,
        }
        if self._backend:
            info.update(self._backend.get_info())
        return info

    # These methods are invoked by the PipeWire thread.
    def native_state_changed(self, state: str) -> None:
        GLib.idle_add(self._emit_state, state)

    def native_error(self, message: str) -> None:
        GLib.idle_add(self._emit_error, message)

    def native_frame(self, frame: dict) -> None:
        try:
            image = self._make_image(frame)
        except Exception as e:
            release = frame.get("release")
            if release:
                release()
            log.warn("Warning: dropping PipeWire frame: %s", e)
            return
        with self._lock:
            previous, self._image = self._image, image
            schedule = not self._refresh_pending
            self._refresh_pending = True
        if previous:
            previous.free()
        if schedule:
            GLib.idle_add(self._emit_frame)

    def _make_image(self, frame: dict) -> ImageWrapper:
        width = int(frame["width"])
        height = int(frame["height"])
        stride = int(frame["stride"])
        pixel_format = str(frame["format"])
        self.width, self.height, self.pixel_format = width, height, pixel_format
        if frame["type"] != "dmabuf":
            return make_cpu_image(frame["data"], int(frame.get("offset", 0)),
                                  int(frame["size"]), width, height, stride, pixel_format)
        fds = tuple(frame["fds"])
        strides = tuple(frame["strides"])
        offsets = tuple(frame["offsets"])
        modifier = int(frame.get("modifier", 0))
        if modifier != DRM_FORMAT_MOD_LINEAR:
            raise ValueError(f"unsupported DMA-BUF modifier {modifier:#x}")
        if len(fds) != 1 or len(strides) != 1 or len(offsets) != 1:
            raise ValueError("only single-plane packed DMA-BUF frames are supported")
        release = frame.get("release")
        return DMABufImageWrapper(
            0, 0, width, height, int(frame["drm-format"]), modifier,
            fds, strides, offsets,
            lambda: download_dmabuf(fds[0], offsets[0], strides[0], width, height,
                                    pixel_format, modifier),
            release=release, pixel_format=pixel_format, depth=32, bytesperpixel=4,
        )

    def _emit_frame(self) -> bool:
        with self._lock:
            self._refresh_pending = False
            has_image = self._image is not None
        if self._cleaned or not has_image:
            return False
        self.frames += 1
        self.emit("new-image", self.pixel_format, self._image, {"frame": self.frames})
        return False

    def _emit_state(self, state: str) -> bool:
        if not self._cleaned:
            self.state = state
            self.emit("state-changed", state)
        return False

    def _emit_error(self, message: str) -> bool:
        if not self._cleaned:
            self.emit("error", message)
        return False


GObject.type_register(Capture)
