# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Screen capture backend using AVFoundation (macOS).

Builds one minimal AVCaptureSession per display:
    AVCaptureScreenInput -> AVCaptureVideoDataOutput

The output's sample-buffer delegate is invoked on a dedicated dispatch queue
for every captured frame; the CVPixelBuffer is copied out immediately (it is
only valid for the duration of the callback) and stashed under a lock, then a
notification callback is fired so the shadow server can schedule a refresh.

Unlike ``CGRegisterScreenRefreshCallback``, AVCaptureScreenInput delivers whole
frames with no dirty-rectangle information, so this backend is meant for
full-frame streaming (``--encoding=stream`` / multi-window shadow mode).

High-DPI:
    By default the output is pinned to the display's logical (point) size so the
    delivered frames match the logical window-model geometry. Set
    ``XPRA_AVFOUNDATION_HIGHDPI=1`` to capture at the display's native pixel
    resolution instead (the shadow server then scales the window-model geometry
    by the same factor so sizes stay consistent).
"""

import sys
import time
import threading
from typing import Any
from collections.abc import Callable, Sequence

import Quartz.CoreGraphics as CG
from AVFoundation import (
    AVCaptureSession, AVCaptureScreenInput, AVCaptureVideoDataOutput,
)
from Quartz.CoreVideo import kCVPixelFormatType_32BGRA
from CoreMedia import CMSampleBufferGetImageBuffer, CMTimeMake

from xpra.codecs.image import ImageWrapper
from xpra.util.env import envbool
from xpra.platform.darwin.avfoundation_common import (
    get_dispatch_queue, copy_pixel_buffer, SampleBufferDelegate,
)
from xpra.log import Logger

log = Logger("shadow", "osx")

HIGHDPI = envbool("XPRA_AVFOUNDATION_HIGHDPI", False)

# Block in start() until the first frame is delivered (or this many seconds
# elapse), so the initial window paint isn't black while the session warms up.
FIRST_FRAME_TIMEOUT = 3

# CVPixelBuffer videoSettings keys (string-valued in PyObjC):
kCVPixelBufferPixelFormatTypeKey = "PixelFormatType"
kCVPixelBufferWidthKey = "Width"
kCVPixelBufferHeightKey = "Height"


def get_display_scale(display_id: int) -> float:
    """Return the backing scale (native pixels / logical points) for *display_id*."""
    try:
        mode = CG.CGDisplayCopyDisplayMode(display_id)
        pixel_w = CG.CGDisplayModeGetPixelWidth(mode)
        point_w = CG.CGDisplayModeGetWidth(mode)
        if point_w > 0:
            return pixel_w / point_w
    except Exception:
        log("get_display_scale(%#x)", display_id, exc_info=True)
    return 1.0


def get_active_displays() -> Sequence[int]:
    err, active, count = CG.CGGetActiveDisplayList(16, None, None)
    if err or not count:
        log("CGGetActiveDisplayList failed (err=%s, count=%s), using main display", err, count)
        return (CG.CGMainDisplayID(), )
    return tuple(active)


class ScreenCaptureDevice:
    """
    One AVCaptureSession + AVCaptureScreenInput capturing a single display.

    ``bounds`` is the display's rectangle ``(x, y, w, h)`` in the *same*
    coordinate space as the captured frames and the window models: logical
    points by default, or native pixels when ``pin_size`` is False (high-DPI).
    """

    def __init__(self, display_id: int, bounds: tuple[int, int, int, int],
                 notify: Callable[[], None], get_fps: Callable[[], int], pin_size: bool = True):
        self._display_id = display_id
        self._bounds = bounds
        self._notify = notify
        self._get_fps = get_fps
        self._pin_size = pin_size
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._raw: bytes = b""
        self._width = 0
        self._height = 0
        self._stride = 0
        self._frames = 0
        self._os_dropped = 0
        self._session = None
        self._input = None
        self._output = None
        self._delegate = None
        self._queue = None
        self._setup()

    def _setup(self) -> None:
        log("ScreenCaptureDevice._setup() display=%#x bounds=%s pin_size=%s",
            self._display_id, self._bounds, self._pin_size)
        session = AVCaptureSession.alloc().init()
        sinput = AVCaptureScreenInput.alloc().initWithDisplayID_(self._display_id)
        if sinput is None:
            raise RuntimeError(f"cannot capture display {self._display_id:#x}")
        fps = max(1, int(self._get_fps()))
        try:
            sinput.setMinFrameDuration_(CMTimeMake(1, fps))
        except Exception:
            log("setMinFrameDuration_ failed", exc_info=True)
        # xpra draws its own cursor via the cursor subsystem:
        for setter in ("setCapturesCursor_", "setCapturesMouseClicks_"):
            try:
                getattr(sinput, setter)(False)
            except Exception:
                log("%s failed", setter, exc_info=True)
        if not session.canAddInput_(sinput):
            raise RuntimeError(f"cannot add screen input for display {self._display_id:#x}")
        session.addInput_(sinput)

        output = AVCaptureVideoDataOutput.alloc().init()
        video_settings: dict[str, Any] = {kCVPixelBufferPixelFormatTypeKey: kCVPixelFormatType_32BGRA}
        if self._pin_size:
            # pin to the logical size: many displays would otherwise deliver
            # native (Retina 2x) frames that wouldn't match the model geometry.
            _, _, w, h = self._bounds
            video_settings[kCVPixelBufferWidthKey] = w
            video_settings[kCVPixelBufferHeightKey] = h
        output.setVideoSettings_(video_settings)
        try:
            output.setAlwaysDiscardsLateVideoFrames_(True)
        except AttributeError:
            pass
        if not session.canAddOutput_(output):
            raise RuntimeError("cannot add video data output for screen capture")
        session.addOutput_(output)

        delegate = SampleBufferDelegate.alloc().initWithOwner_(self)
        if delegate is None:
            raise RuntimeError("failed to create screen capture frame delegate")
        queue = get_dispatch_queue(b"xpra.shadow.avfoundation")
        output.setSampleBufferDelegate_queue_(delegate, queue)

        self._session = session
        self._input = sinput
        self._output = output
        self._delegate = delegate
        self._queue = queue

    def _on_drop(self) -> None:
        self._os_dropped += 1

    def _on_frame(self, sample_buffer) -> None:
        pb = CMSampleBufferGetImageBuffer(sample_buffer)
        if pb is None:
            return
        raw, w, h, stride, _fmt = copy_pixel_buffer(pb)
        if not raw or not w or not h:
            return
        with self._cond:
            self._raw = raw
            self._width = w
            self._height = h
            self._stride = stride
            self._frames += 1
            self._cond.notify_all()
        if self._frames <= 3:
            log("ScreenCaptureDevice display=%#x frame #%i: %ix%i stride=%i",
                self._display_id, self._frames, w, h, stride)
        self._notify()

    def start(self, wait: float = FIRST_FRAME_TIMEOUT) -> None:
        session = self._session
        if session is None:
            return
        if not session.isRunning():
            session.startRunning()
        # pre-warm so the first get_image doesn't return a black frame:
        deadline = time.monotonic() + wait
        with self._cond:
            while self._frames == 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log.warn("Warning: no screen frame within %.1fs for display %#x",
                             wait, self._display_id)
                    return
                self._cond.wait(remaining)

    def stop(self) -> None:
        session = self._session
        if session is not None and session.isRunning():
            session.stopRunning()

    def clean(self) -> None:
        self.stop()
        self._session = None
        self._input = None
        self._output = None
        self._delegate = None
        self._queue = None
        with self._cond:
            self._raw = b""

    def set_fps(self, fps: int) -> None:
        sinput = self._input
        if sinput is not None:
            try:
                sinput.setMinFrameDuration_(CMTimeMake(1, max(1, int(fps))))
            except Exception:
                log("set_fps(%s) failed", fps, exc_info=True)

    def get_image(self, x: int, y: int, width: int, height: int) -> ImageWrapper | None:
        with self._lock:
            raw = self._raw
            fw = self._width
            fh = self._height
            stride = self._stride
        if not raw:
            return None
        x = max(0, x)
        y = max(0, y)
        if x >= fw or y >= fh:
            return None
        width = min(width, fw - x)
        height = min(height, fh - y)
        if width <= 0 or height <= 0:
            return None
        if x == 0 and width == fw:
            # rows are contiguous, no per-row copy needed:
            data = raw[y * stride:(y + height) * stride]
            return ImageWrapper(x, y, fw, height, data, "BGRX", 24, stride)
        row_bytes = width * 4
        out = bytearray(row_bytes * height)
        for i in range(height):
            src = (y + i) * stride + x * 4
            out[i * row_bytes:(i + 1) * row_bytes] = raw[src:src + row_bytes]
        return ImageWrapper(x, y, width, height, bytes(out), "BGRX", 24, row_bytes)

    def get_info(self) -> dict[str, Any]:
        return {
            "display": self._display_id,
            "bounds": self._bounds,
            "size": (self._width, self._height),
            "frames": self._frames,
            "os-dropped": self._os_dropped,
        }


class AVFShadowCapture:
    """
    Multi-display screen capture used by the macOS shadow server.

    Creates one :class:`ScreenCaptureDevice` per active display so multi-monitor
    keeps working (the old CoreGraphics grab captured the whole virtual desktop).
    ``get_image`` routes each request to the device whose bounds contain it.
    """

    def __init__(self, on_frame: Callable[[], None], get_fps: Callable[[], int], highdpi: bool = HIGHDPI):
        self._notify = on_frame
        self._get_fps = get_fps
        self._highdpi = highdpi
        self._devices: list[tuple[tuple[int, int, int, int], ScreenCaptureDevice]] = []
        self._setup()

    def _setup(self) -> None:
        for display_id in get_active_displays():
            b = CG.CGDisplayBounds(display_id)
            lx, ly = int(b.origin.x), int(b.origin.y)
            lw, lh = int(b.size.width), int(b.size.height)
            sf = get_display_scale(display_id) if self._highdpi else 1.0
            bounds = (round(lx * sf), round(ly * sf), round(lw * sf), round(lh * sf))
            device = ScreenCaptureDevice(display_id, bounds, self._notify, self._get_fps,
                                         pin_size=not self._highdpi)
            self._devices.append((bounds, device))
        log("AVFShadowCapture._setup() highdpi=%s devices=%s", self._highdpi,
            [b for b, _ in self._devices])

    @staticmethod
    def get_type() -> str:
        return "AVFoundation"

    @staticmethod
    def refresh() -> bool:
        return True

    def start(self) -> None:
        for _, device in self._devices:
            device.start()

    def stop(self) -> None:
        for _, device in self._devices:
            device.stop()

    def clean(self) -> None:
        for _, device in self._devices:
            device.clean()
        self._devices = []

    def _find_device(self, x: int, y: int):
        for bounds, device in self._devices:
            bx, by, bw, bh = bounds
            if bx <= x < bx + bw and by <= y < by + bh:
                return bounds, device
        if self._devices:
            return self._devices[0]
        return None, None

    def get_image(self, x: int, y: int, width: int, height: int) -> ImageWrapper | None:
        bounds, device = self._find_device(x, y)
        if device is None:
            return None
        bx, by = bounds[:2]
        return device.get_image(x - bx, y - by, width, height)

    def set_fps(self, fps: int) -> None:
        for _, device in self._devices:
            device.set_fps(fps)

    @staticmethod
    def take_screenshot() -> tuple[int, int, str, int, bytes]:
        from xpra.platform.darwin.gui import take_screenshot
        return take_screenshot()

    def get_info(self) -> dict[str, Any]:
        return {
            "type": self.get_type(),
            "highdpi": self._highdpi,
            "displays": [device.get_info() for _, device in self._devices],
        }


def main() -> None:
    from xpra.platform import program_context
    from xpra.codecs.image import to_pil_encoding
    with program_context("MacOS AVFoundation Screen Capture"):
        log.enable_debug()
        x, y, w, h = (int(sys.argv[i]) for i in range(1, 5))
        capture = AVFShadowCapture(on_frame=lambda: None, get_fps=lambda: 10)
        capture.start()
        image = capture.get_image(x, y, w, h)
        if image is None:
            print("no image captured")
            capture.clean()
            return
        data = to_pil_encoding(image, "png")
        capture.clean()
        tstr = time.strftime("%H-%M-%S", time.localtime(time.time()))
        filename = "./Capture-{}-{}.png".format((x, y, w, h), tstr)
        with open(filename, "wb") as f:
            f.write(data)
        print(f"saved {image.get_width()}x{image.get_height()} to {filename!r}")


if __name__ == "__main__":
    main()
