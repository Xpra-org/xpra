# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import numpy
import cv2

from xpra.codecs.image import ImageWrapper
from xpra.client.webcam.base import CameraDevice
from xpra.log import Logger

log = Logger("webcam")


class CV2Camera(CameraDevice):
    """
    Webcam capture backend using OpenCV (cv2.VideoCapture).
    Delivers BGR frames wrapped as ImageWrapper.
    """

    def __init__(self, device_no: int) -> None:
        self._device_no = device_no
        self._capture = cv2.VideoCapture(device_no)
        self._width: int = 0
        self._height: int = 0

    def read(self) -> ImageWrapper | None:
        ret, frame = self._capture.read()
        if not ret or frame is None:
            return None
        if frame.ndim != 3:
            log.warn("Warning: unexpected frame dimensions: %s", frame.ndim)
            return None
        h, w, bpp = frame.shape
        if bpp != 3:
            log.warn("Warning: unexpected bytes per pixel: %s", bpp)
            return None
        self._width = w
        self._height = h
        # Ensure the array is contiguous in memory before wrapping
        if not frame.flags["C_CONTIGUOUS"]:
            frame = numpy.ascontiguousarray(frame)
        rowstride = w * bpp
        return ImageWrapper(0, 0, w, h, frame.tobytes(), "BGR", 24, rowstride, planes=ImageWrapper.PACKED)

    def release(self) -> None:
        try:
            self._capture.release()
        except Exception as e:
            log("CV2Camera.release() error: %s", e)

    @property
    def pixel_format(self) -> str:
        return "BGR"

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def __repr__(self) -> str:
        return f"CV2Camera({self._device_no})"
