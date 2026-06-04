# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Shared AVFoundation / CoreVideo plumbing used by both the webcam capture
(:mod:`xpra.platform.darwin.avfoundation_camera`) and the screen capture
(:mod:`xpra.platform.darwin.avfoundation_screen`) backends.

Both feed an ``AVCaptureVideoDataOutput`` whose sample-buffer delegate is
invoked on a dedicated dispatch queue for every captured frame; the CVPixelBuffer
behind each sample is only valid for the duration of that callback, so the
helpers here copy the pixels out immediately.
"""

import ctypes

import objc
from Foundation import NSObject
from Quartz.CoreVideo import (
    CVPixelBufferLockBaseAddress, CVPixelBufferUnlockBaseAddress,
    CVPixelBufferGetBaseAddress, CVPixelBufferGetBytesPerRow,
    CVPixelBufferGetWidth, CVPixelBufferGetHeight,
    CVPixelBufferGetPixelFormatType, CVPixelBufferIsPlanar,
    CVPixelBufferGetPlaneCount, CVPixelBufferGetBaseAddressOfPlane,
    CVPixelBufferGetHeightOfPlane, CVPixelBufferGetBytesPerRowOfPlane,
)

from xpra.log import Logger

log = Logger("webcam")

kCVPixelBufferLock_ReadOnly = 1


def get_dispatch_queue(label: bytes):
    """
    Return a serial dispatch queue suitable for sample-buffer delivery.

    AVFoundation needs a real ``dispatch_queue_t``; PyObjC exposes one via
    the ``libdispatch`` framework binding. If unavailable, fall back to a
    global concurrent queue, which still serialises per-delegate calls.
    """
    try:
        from libdispatch import dispatch_queue_create   # type: ignore[import-not-found]
        return dispatch_queue_create(label, None)
    except ImportError:
        pass
    try:
        from libdispatch import dispatch_get_global_queue   # type: ignore[import-not-found]
        return dispatch_get_global_queue(0, 0)
    except ImportError as e:
        raise RuntimeError(
            "AVFoundation backend requires pyobjc-framework-libdispatch"
        ) from e


def addr_to_bytes(addr, length: int) -> bytes:
    """
    Copy *length* bytes out of a base address returned by CoreVideo.

    PyObjC types ``CVPixelBufferGetBaseAddress`` results as an ``objc.varlist``
    (a typed pointer view), which exposes the underlying memory via
    ``as_buffer(length)``. Older bindings may hand back a plain integer pointer.
    """
    as_buffer = getattr(addr, "as_buffer", None)
    if as_buffer is not None:
        return bytes(as_buffer(length))
    return ctypes.string_at(int(addr), length)


def copy_pixel_buffer(pb) -> tuple[bytes, int, int, int, int]:
    """
    Lock *pb*, copy its bytes into a Python ``bytes`` object, and return
    ``(raw, width, height, stride, pixel_format_int)``.

    The copy must happen while the buffer is locked and still owned by the
    caller (i.e. inside the delegate callback): the CVPixelBuffer is recycled
    by AVFoundation once the callback returns.

    For planar buffers (NV12), planes are concatenated in their natural order
    so the result is a single PACKED blob whose first ``stride*height`` bytes
    are the Y plane.
    """
    fmt_int = CVPixelBufferGetPixelFormatType(pb)
    width = CVPixelBufferGetWidth(pb)
    height = CVPixelBufferGetHeight(pb)

    CVPixelBufferLockBaseAddress(pb, kCVPixelBufferLock_ReadOnly)
    try:
        if CVPixelBufferIsPlanar(pb):
            n_planes = CVPixelBufferGetPlaneCount(pb)
            stride = CVPixelBufferGetBytesPerRowOfPlane(pb, 0)
            chunks: list[bytes] = []
            for i in range(n_planes):
                addr = CVPixelBufferGetBaseAddressOfPlane(pb, i)
                plane_h = CVPixelBufferGetHeightOfPlane(pb, i)
                plane_stride = CVPixelBufferGetBytesPerRowOfPlane(pb, i)
                if addr is None or plane_h <= 0 or plane_stride <= 0:
                    return b"", 0, 0, 0, fmt_int
                chunks.append(addr_to_bytes(addr, plane_stride * plane_h))
            raw = b"".join(chunks)
        else:
            stride = CVPixelBufferGetBytesPerRow(pb)
            addr = CVPixelBufferGetBaseAddress(pb)
            if addr is None:
                return b"", 0, 0, 0, fmt_int
            raw = addr_to_bytes(addr, stride * height)
    finally:
        CVPixelBufferUnlockBaseAddress(pb, kCVPixelBufferLock_ReadOnly)
    return raw, width, height, stride, fmt_int


class SampleBufferDelegate(NSObject):
    """
    Generic ``AVCaptureVideoDataOutputSampleBufferDelegate``.

    Receives every delivered sample buffer on the capture queue and forwards
    it to the owning object, which must expose ``_on_frame(sample_buffer)``
    and ``_on_drop()``. The owner reference is held strongly for the lifetime
    of the delegate.
    """

    # noinspection PyTypeHints
    def initWithOwner_(self, owner):
        objc_self = objc.super(SampleBufferDelegate, self).init()
        if objc_self is None:
            return None
        objc_self._owner_ref = owner
        return objc_self

    @objc.typedSelector(b'v@:@@@')
    def captureOutput_didOutputSampleBuffer_fromConnection_(self, output, sample_buffer, conn):
        owner = self._owner_ref
        if owner is None:
            log("captureOutput: no owner ref (delegate orphaned)")
            return
        try:
            owner._on_frame(sample_buffer)
        except Exception:
            log.error("Error: AVFoundation _on_frame failed", exc_info=True)

    @objc.typedSelector(b'v@:@@@')
    def captureOutput_didDropSampleBuffer_fromConnection_(self, output, sample_buffer, conn):
        owner = self._owner_ref
        if owner is not None:
            owner._on_drop()
