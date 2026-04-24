# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import mmap
import time
import selectors
from typing import Any

from xpra.codecs.image import ImageWrapper
from xpra.webcam.base import CameraDevice
from xpra.log import Logger

log = Logger("webcam")

# Timeout (seconds) to wait for a libcamera frame request to complete
LIBCAMERA_READ_TIMEOUT = 3

LIBCAMERA_PIXEL_FORMATS: dict[str, str] = {
    "NV12": "NV12",
    "YUYV": "YUYV",
    "BGR888": "BGR",
    "RGB888": "RGB",
    "BGRA8888": "BGRX",
    "RGBA8888": "RGBX",
}


def _get_pixel_format(stream_config) -> str:
    """Map a libcamera PixelFormat to an Xpra pixel format string."""
    fmt = str(stream_config.pixel_format)
    return LIBCAMERA_PIXEL_FORMATS.get(fmt, fmt)


class LibcameraCamera(CameraDevice):
    """
    Webcam capture backend using libcamera Python bindings.

    The bindings deliver completed requests through ``CameraManager.event_fd``
    (an eventfd) and ``CameraManager.get_ready_requests()``; ``read()`` polls
    that fd with a timeout and drains any ready requests.

    Typical pixel formats delivered are NV12 or YUYV
    """

    def __init__(self, camera_id: str) -> None:
        import libcamera
        self._camera_id = camera_id
        self._cm = libcamera.CameraManager.singleton()
        self._camera = next((c for c in self._cm.cameras if c.id == camera_id), None)
        if self._camera is None:
            raise RuntimeError(f"libcamera: camera {camera_id!r} not found")
        self._camera.acquire()
        log("libcamera acquired camera_id=%s", camera_id)

        self._config = self._camera.generate_configuration([libcamera.StreamRole.Viewfinder])
        log("camera config=%s", self._config)
        stream_config = self._config.at(0)

        # libcamera often picks MJPEG on UVC cameras, which this backend does not
        # decode and which is unreliable through the uvcvideo pipeline. Try to
        # force an uncompressed format we know how to handle.
        preferred = ("YUYV", "NV12", "RGB888", "BGR888", "BGRA8888", "RGBA8888")
        try:
            available = [str(f) for f in stream_config.formats.pixel_formats]
            log(" available pixel formats: %s", available)
            chosen = next((p for p in preferred if p in available), "")
            if chosen and str(stream_config.pixel_format) != chosen:
                match = next(f for f in stream_config.formats.pixel_formats if str(f) == chosen)
                stream_config.pixel_format = match
                log(" forcing pixel format to %s", chosen)
        except Exception as e:
            log(" could not override pixel format: %s", e)

        from xpra.util.parsing import parse_resolution
        parsed = parse_resolution(os.environ.get("XPRA_LIBCAMERA_SIZE", "320x240"))
        if parsed:
            w, h = parsed[:2]
            try:
                stream_config.size = libcamera.Size(w, h)
                log(" requested size %ix%i from XPRA_LIBCAMERA_SIZE", w, h)
            except Exception as e:
                log.warn("Warning: could not set libcamera size to %ix%i: %s", w, h, e)

        status = self._config.validate()
        log("camera config validate=%s", status)
        self._pixel_format: str = _get_pixel_format(stream_config)
        self._width: int = stream_config.size.width
        self._height: int = stream_config.size.height
        # NV12 stride may differ from width
        self._stride: int = stream_config.stride
        log(" using %ix%i %s with stride=%i", self._width, self._height, self._pixel_format, self._stride)

        self._camera.configure(self._config)

        # Allocate frame buffers
        alloc = libcamera.FrameBufferAllocator(self._camera)
        self._stream = stream_config.stream
        alloc.allocate(self._stream)
        self._buffers = alloc.buffers(self._stream)
        log("allocated buffers=%s", self._buffers)

        # Map each FrameBuffer once; reuse across frames.
        # plane.fd is a raw dmabuf fd in this binding version, so we mmap it ourselves.
        self._buffer_maps: dict[int, tuple[mmap.mmap, int, int]] = {}
        for buf in self._buffers:
            plane = buf.planes[0]
            fd = int(plane.fd)
            offset = int(getattr(plane, "offset", 0))
            length = int(plane.length)
            try:
                mm = mmap.mmap(fd, offset + length, mmap.MAP_SHARED, mmap.PROT_READ)
            except Exception as e:
                log.error("Error: mmap(fd=%s, len=%s) failed: %s", fd, offset + length, e)
                raise
            self._buffer_maps[id(buf)] = (mm, offset, length)
        log("mmapped %i buffers", len(self._buffer_maps))

        # Create and queue requests
        self._requests: list[Any] = []
        for buf in self._buffers:
            req = self._camera.create_request()
            req.add_buffer(self._stream, buf)
            self._requests.append(req)
        log("requests=%s", self._requests)

        # Set up selector on the CameraManager's event fd (delivered when
        # completed requests are available via get_ready_requests()).
        self._selector = selectors.DefaultSelector()
        event_fd = getattr(self._cm, "event_fd", None)
        log("camera manager event_fd=%s", event_fd)
        if event_fd is None:
            raise RuntimeError("libcamera: CameraManager has no event_fd")
        self._selector.register(event_fd, selectors.EVENT_READ)

        log("starting camera!")
        ret = self._camera.start()
        log("camera.start() returned %r", ret)
        if ret:
            raise RuntimeError(f"libcamera: camera.start() failed with {ret}")

        # Queue every pre-allocated request so the camera can fill them.
        for i, req in enumerate(self._requests):
            ret = self._camera.queue_request(req)
            log("queue_request[%i] returned %r", i, ret)
            if ret:
                log.warn("Warning: queue_request[%i] failed with %r", i, ret)

    def _wait_ready_request(self) -> Any:
        """Block until one completed request is available, or return None on timeout."""
        deadline = time.monotonic() + LIBCAMERA_READ_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log("libcamera read deadline reached")
                return None
            events = self._selector.select(timeout=remaining)
            log("selector.select() -> %s (remaining=%.2fs)", events, remaining)
            if not events:
                return None
            # get_ready_requests() internally drains the eventfd and pops
            # completed requests from the camera manager's queue.
            reqs = self._cm.get_ready_requests()
            log("get_ready_requests() -> %i requests", len(reqs) if reqs else 0)
            if not reqs:
                # drain anyway so we don't spin on a stuck-readable fd
                try:
                    os.read(self._cm.event_fd, 8)
                except OSError:
                    pass
                continue
            # Prefer the most recent frame; reuse+requeue the rest immediately.
            latest = reqs[-1]
            for req in reqs[:-1]:
                req.reuse()
                self._camera.queue_request(req)
            return latest

    def read(self) -> ImageWrapper | None:
        req = self._wait_ready_request()
        if req is None:
            log.warn("Warning: libcamera frame timeout for %s", self._camera_id)
            return None

        try:
            buf = req.buffers[self._stream]
            mm, offset, length = self._buffer_maps[id(buf)]
            raw = bytes(mm[offset:offset + length])
        except Exception as e:
            log.warn("Warning: failed to read libcamera buffer: %s", e)
            # Re-queue the request for reuse
            req.reuse()
            self._camera.queue_request(req)
            return None

        w, h = self._width, self._height
        image = ImageWrapper(0, 0, w, h, raw, self._pixel_format, 0, self._stride, planes=ImageWrapper.PACKED)
        log("%r.read()=%s", self, image)

        # Re-queue the request so the camera keeps filling buffers
        req.reuse()
        self._camera.queue_request(req)

        return image

    def release(self) -> None:
        try:
            self._camera.stop()
            self._camera.release()
        except Exception as e:
            log("LibcameraCamera.release() error: %s", e)
        for mm, _, _ in self._buffer_maps.values():
            try:
                mm.close()
            except Exception:
                pass
        self._buffer_maps.clear()
        try:
            self._selector.close()
        except Exception:
            pass

    @property
    def pixel_format(self) -> str:
        return self._pixel_format

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def __repr__(self) -> str:
        return f"LibcameraCamera({self._camera_id!r})"
