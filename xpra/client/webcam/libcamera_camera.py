# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import threading
from typing import Any

from xpra.codecs.image import ImageWrapper
from xpra.client.webcam.base import CameraDevice
from xpra.log import Logger

log = Logger("webcam")

# Timeout (seconds) to wait for a libcamera frame request to complete
LIBCAMERA_READ_TIMEOUT = 1

LIBCAMERA_PIXEL_FORMATS = {
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
    Uses a threading.Event to bridge the asynchronous request-completed
    callback into a synchronous read() call.

    Typical pixel formats delivered are NV12 or YUYV
    """

    def __init__(self, camera_id: str) -> None:
        import libcamera
        self._camera_id = camera_id
        self._cm = libcamera.CameraManager.singleton()
        self._camera = self._cm.find(camera_id)
        if self._camera is None:
            raise RuntimeError(f"libcamera: camera {camera_id!r} not found")
        self._camera.acquire()
        log("libcamera acquired camera_id=%s", camera_id)

        # Choose a configuration for video recording
        self._config = self._camera.generate_configuration([libcamera.StreamRole.VideoRecording])
        log("camera config=%s", self._config)
        stream_config = self._config.at(0)
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

        # Create and queue requests
        self._requests: list[Any] = []
        for buf in self._buffers:
            req = self._camera.create_request()
            req.add_buffer(self._stream, buf)
            self._requests.append(req)
        log("requests=%s", self._requests)

        # Synchronisation primitives: libcamera runs its own thread
        self._event = threading.Event()
        self._completed_request: Any = None
        self._lock = threading.Lock()

        # Wire up the callback and start the camera
        log("starting camera!")
        self._camera.request_completed.connect(self._on_request_completed)
        self._camera.start()

        # Queue the first request
        self._camera.queue_request(self._requests[0])
        self._next_request_index = 1 % len(self._requests)

    def _on_request_completed(self, request) -> None:
        with self._lock:
            self._completed_request = request
        self._event.set()

    def read(self) -> ImageWrapper | None:
        self._event.clear()
        if not self._event.wait(timeout=LIBCAMERA_READ_TIMEOUT):
            log.warn("Warning: libcamera frame timeout for %s", self._camera_id)
            return None

        with self._lock:
            req = self._completed_request
            self._completed_request = None

        if req is None:
            return None

        try:
            buf = req.buffers[self._stream]
            plane = buf.planes[0]
            with plane.fd as mmap_obj:
                raw = bytes(mmap_obj[:plane.length])
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

        # Queue the next pre-allocated request if available
        if len(self._requests) > 1:
            next_req = self._requests[self._next_request_index]
            self._next_request_index = (self._next_request_index + 1) % len(self._requests)
            try:
                self._camera.queue_request(next_req)
            except Exception:
                pass  # already queued

        return image

    def release(self) -> None:
        try:
            self._camera.stop()
            self._camera.request_completed.disconnect(self._on_request_completed)
            self._camera.release()
        except Exception as e:
            log("LibcameraCamera.release() error: %s", e)

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
