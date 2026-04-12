# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from abc import ABC, abstractmethod

from xpra.codecs.image import ImageWrapper


class CameraDevice(ABC):
    """
    Abstract base class for webcam capture devices.
    Implementations must return frames as ImageWrapper objects.
    """

    @abstractmethod
    def read(self) -> ImageWrapper | None:
        """
        Capture a single frame.
        Returns an ImageWrapper on success, or None on failure.
        """

    @abstractmethod
    def release(self) -> None:
        """Release any underlying resources held by this device."""

    @property
    @abstractmethod
    def pixel_format(self) -> str:
        """The pixel format of frames produced by this device (e.g. 'BGR', 'NV12', 'BGRX')."""

    @property
    @abstractmethod
    def width(self) -> int:
        """Width of captured frames in pixels."""

    @property
    @abstractmethod
    def height(self) -> int:
        """Height of captured frames in pixels."""
