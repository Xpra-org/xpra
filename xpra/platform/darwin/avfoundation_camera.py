# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Webcam capture backend using AVFoundation (macOS).

Builds a minimal AVCaptureSession:
    AVCaptureDeviceInput -> AVCaptureVideoDataOutput

The output's sample buffer delegate is invoked on a dedicated dispatch queue
for every captured frame; the most recent frame is stashed under a Condition
and ``read()`` returns and clears it.
"""

import os
import time
import threading
from typing import Any

from AVFoundation import (
    AVCaptureSession, AVCaptureDevice, AVCaptureDeviceInput,
    AVCaptureVideoDataOutput,
    AVCaptureSessionPreset320x240, AVCaptureSessionPreset640x480,
    AVCaptureSessionPreset1280x720, AVCaptureSessionPreset1920x1080,
)
from Quartz.CoreVideo import (
    kCVPixelFormatType_32BGRA,
    kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
)
from CoreMedia import CMSampleBufferGetImageBuffer

from xpra.codecs.image import ImageWrapper
from xpra.webcam.base import CameraDevice
from xpra.platform.darwin.avfoundation_common import get_dispatch_queue, copy_pixel_buffer, SampleBufferDelegate
from xpra.log import Logger

log = Logger("webcam")

AVFOUNDATION_READ_TIMEOUT = 3
# Block in _setup() until the first frame is delivered (or this many seconds
# elapse). Doing this here - before the GLib main loop starts - means the first
# read() never blocks the UI thread, which on macOS GTK could otherwise starve
# the initial window paint and leave it black.
AVFOUNDATION_FIRST_FRAME_TIMEOUT = 5

# CVPixelBuffer videoSettings keys (string-valued in PyObjC)
kCVPixelBufferPixelFormatTypeKey = "PixelFormatType"
kCVPixelBufferWidthKey = "Width"
kCVPixelBufferHeightKey = "Height"

# Map AVFoundation/CoreVideo OSType to xpra pixel format string
AVF_PIXEL_FORMATS: dict[int, str] = {
    kCVPixelFormatType_32BGRA: "BGRX",
    kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange: "NV12",
}

# Preference order: BGRX first (no CSC needed for the common case), NV12 fallback
PREFERRED_AVF_FORMATS: tuple[int, ...] = (
    kCVPixelFormatType_32BGRA,
    kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
)

# Log a warning when frame delivery (camera -> _on_frame) stalls for longer
# than this many seconds.
STALL_WARN = 0.2

PRESETS: dict[str, str] = {
    "320x240": AVCaptureSessionPreset320x240,
    "640x480": AVCaptureSessionPreset640x480,
    "VGA": AVCaptureSessionPreset640x480,
    "1280x720": AVCaptureSessionPreset1280x720,
    "720p": AVCaptureSessionPreset1280x720,
    "1920x1080": AVCaptureSessionPreset1920x1080,
    "1080p": AVCaptureSessionPreset1920x1080,
}

# Modern / Continuity cameras frequently ignore the session preset and deliver
# their native resolution (e.g. 1920x1080), so we also constrain the output
# size explicitly via the CoreVideo Width/Height keys in videoSettings.
PRESET_SIZES: dict[str, tuple[int, int]] = {
    AVCaptureSessionPreset320x240: (320, 240),
    AVCaptureSessionPreset640x480: (640, 480),
    AVCaptureSessionPreset1280x720: (1280, 720),
    AVCaptureSessionPreset1920x1080: (1920, 1080),
}


class AVFoundationCamera(CameraDevice):
    """
    Webcam capture backend using AVFoundation.

    The constructor takes an AVFoundation ``uniqueID`` string (resolved by
    :func:`xpra.platform.darwin.webcam._find_avfoundation_id`).
    Frames are delivered asynchronously through a sample-buffer delegate
    running on a dedicated dispatch queue; ``read()`` blocks until the
    next frame arrives (drop-oldest: only the most recent frame is kept).
    """

    def __init__(self, device_id: str) -> None:
        self._device_id = device_id
        self._pixel_format = ""
        self._width = 0
        self._height = 0
        self._stride = 0
        self._latest: ImageWrapper | None = None
        self._cond = threading.Condition()
        self._session = None
        self._output = None
        self._delegate = None
        self._queue = None
        self._unknown_format_warned = False
        # diagnostics:
        self._frames = 0            # frames delivered by the OS to _on_frame
        self._delivered = 0         # frames actually returned by read()
        self._overwritten = 0       # frames replaced in _latest before being read
        self._os_dropped = 0        # frames the OS dropped (didDropSampleBuffer)
        self._last_frame_t = 0.0    # monotonic time of the previous delivered frame
        self._last_returned: ImageWrapper | None = None  # last frame handed to read()
        self._setup()

    def _setup(self) -> None:
        log("AVFoundationCamera._setup() device_id=%r", self._device_id)
        device = AVCaptureDevice.deviceWithUniqueID_(self._device_id)
        if device is None:
            raise RuntimeError(f"AVFoundation: device {self._device_id!r} not found")
        try:
            log(" device=%r (%s)", str(device.localizedName()), str(device.modelID()))
        except Exception:
            pass

        session = AVCaptureSession.alloc().init()
        preset_name = os.environ.get("XPRA_AVFOUNDATION_PRESET", "640x480")
        preset = PRESETS.get(preset_name, AVCaptureSessionPreset640x480)
        if session.canSetSessionPreset_(preset):
            session.setSessionPreset_(preset)
            log(" preset=%s", preset)
        else:
            log.warn("Warning: AVFoundation preset %r not supported, using default", preset_name)
        target_size = PRESET_SIZES.get(preset, (640, 480))

        input_, err = AVCaptureDeviceInput.deviceInputWithDevice_error_(device, None)
        if input_ is None:
            raise RuntimeError(f"AVFoundation: cannot open device {self._device_id!r}: {err}")
        if not session.canAddInput_(input_):
            raise RuntimeError(f"AVFoundation: cannot add input for {self._device_id!r}")
        session.addInput_(input_)

        output = AVCaptureVideoDataOutput.alloc().init()
        try:
            available = list(output.availableVideoCVPixelFormatTypes() or ())
        except Exception:
            available = []
        log(" available pixel formats: %s", available)
        chosen = next((p for p in PREFERRED_AVF_FORMATS if p in available), kCVPixelFormatType_32BGRA)
        # constrain the output resolution: many cameras ignore the session preset
        # and would otherwise deliver their full native (e.g. 1080p) frames.
        output.setVideoSettings_({
            kCVPixelBufferPixelFormatTypeKey: chosen,
            kCVPixelBufferWidthKey: target_size[0],
            kCVPixelBufferHeightKey: target_size[1],
        })
        try:
            output.setAlwaysDiscardsLateVideoFrames_(True)
        except AttributeError:
            pass
        log(" requested pixel format: 0x%08X (%s) at %ix%i",
            chosen, AVF_PIXEL_FORMATS.get(chosen, "?"), target_size[0], target_size[1])

        if not session.canAddOutput_(output):
            raise RuntimeError("AVFoundation: cannot add video data output")
        session.addOutput_(output)

        delegate = SampleBufferDelegate.alloc().initWithOwner_(self)
        if delegate is None:
            raise RuntimeError("AVFoundation: failed to create frame delegate")
        queue = get_dispatch_queue(b"xpra.webcam.avfoundation")
        log(" dispatch queue=%s", queue)
        output.setSampleBufferDelegate_queue_(delegate, queue)

        self._session = session
        self._output = output
        self._delegate = delegate
        self._queue = queue

        session.startRunning()
        log("AVFoundationCamera._setup() session running=%s; waiting for first frame", bool(session.isRunning()))
        self._wait_first_frame()
        log("AVFoundationCamera._setup() complete (frames=%i)", self._frames)

    def _wait_first_frame(self, timeout: float = AVFOUNDATION_FIRST_FRAME_TIMEOUT) -> None:
        """
        Block until the first frame has been delivered (or *timeout* elapses).

        Pre-warming here keeps the first read() - which both the GUI test window
        and the webcam forwarder issue from the GLib main loop - from blocking
        the UI thread while the camera starts up.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._latest is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log.warn("Warning: AVFoundation: no frame within %.1fs of starting"
                             " capture for %s", timeout, self._device_id)
                    return
                self._cond.wait(remaining)

    def _on_drop(self) -> None:
        self._os_dropped += 1
        if self._os_dropped <= 5 or self._os_dropped % 50 == 0:
            log("AVFoundation: OS dropped sample buffer (total dropped=%i)", self._os_dropped)

    def _on_frame(self, sample_buffer) -> None:
        # measure delivery cadence first, before any copy work, so a gap here
        # means the OS genuinely stopped delivering frames:
        now = time.monotonic()
        if self._last_frame_t and (now - self._last_frame_t) > STALL_WARN:
            log.warn("Warning: AVFoundation frame delivery stalled for %.2fs"
                     " (between frames #%i and #%i)",
                     now - self._last_frame_t, self._frames, self._frames + 1)
        self._last_frame_t = now

        pb = CMSampleBufferGetImageBuffer(sample_buffer)
        if pb is None:
            log("_on_frame: no image buffer in sample (frame #%i)", self._frames + 1)
            return
        raw, w, h, stride, fmt_int = copy_pixel_buffer(pb)
        if not raw or not w or not h:
            log("_on_frame: empty/invalid buffer raw=%i w=%i h=%i fmt=0x%08X",
                len(raw), w, h, fmt_int)
            return
        pixel_format = AVF_PIXEL_FORMATS.get(fmt_int, "")
        if not pixel_format:
            if not self._unknown_format_warned:
                self._unknown_format_warned = True
                log.warn("Warning: AVFoundation delivered unsupported pixel format 0x%08X", fmt_int)
            return

        self._frames += 1
        image = ImageWrapper(0, 0, w, h, raw, pixel_format, 0, stride, planes=ImageWrapper.PACKED)
        with self._cond:
            if self._latest is not None:
                self._overwritten += 1
            self._pixel_format = pixel_format
            self._width = w
            self._height = h
            self._stride = stride
            self._latest = image
            self._cond.notify_all()

        if self._frames <= 5 or self._frames % 60 == 0:
            log("_on_frame #%i: %ix%i %s stride=%i bytes=%i"
                " (delivered=%i overwritten=%i os_dropped=%i)",
                self._frames, w, h, pixel_format, stride, len(raw),
                self._delivered, self._overwritten, self._os_dropped)

    def read(self) -> ImageWrapper | None:
        # Non-blocking by design: both consumers (the GUI test window and the
        # webcam forwarder) call read() from the GLib main loop, so blocking here
        # would freeze the UI / starve the main loop. Frames are pushed
        # continuously by the capture delegate, so we just hand back the most
        # recent one. If no new frame has arrived since the last call we repeat
        # the previous frame rather than returning None (which the forwarder
        # treats as a fatal capture failure).
        with self._cond:
            if self._latest is not None:
                self._last_returned = self._latest
                self._latest = None
                self._delivered += 1
            return self._last_returned

    def release(self) -> None:
        log("AVFoundationCamera.release() stats: frames=%i delivered=%i overwritten=%i os_dropped=%i",
            self._frames, self._delivered, self._overwritten, self._os_dropped)
        session = self._session
        self._session = None
        self._output = None
        self._delegate = None
        self._queue = None
        if session is not None:
            try:
                session.stopRunning()
            except Exception as e:
                log("AVFoundationCamera.release() stopRunning error: %s", e)
        with self._cond:
            self._latest = None
            self._last_returned = None
            self._cond.notify_all()

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
        return f"AVFoundationCamera({self._device_id!r})"


def _info() -> dict[str, Any]:
    """For debugging / show_webcam-style introspection."""
    from xpra.platform.darwin.webcam import get_avfoundation_devices
    return {"devices": get_avfoundation_devices()}
