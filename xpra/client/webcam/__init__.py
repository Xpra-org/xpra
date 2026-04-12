# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Webcam capture abstraction.

Provides a unified factory (open_camera) that selects between libcamera
(preferred on Linux when available) and cv2 (OpenCV) backends.

Usage::

    from xpra.client.webcam import open_camera, make_csc_to_bgrx

    device = open_camera(device_str, virt_devices, non_virtual)
    csc = make_csc_to_bgrx(device.pixel_format, device.width, device.height)

    ok, image = device.read()
    if ok and csc is not None:
        image = csc.convert_image(image)

    device.release()
    if csc is not None:
        csc.clean()
"""

from typing import Any

from xpra.client.webcam.base import CameraDevice
from xpra.log import Logger

log = Logger("webcam")

# Device string values that mean "pick the first available device"
AUTO_OPTIONS = frozenset(("auto", "on", "yes", "true"))


def _get_libcamera_devices() -> dict[str, dict[str, Any]]:
    """
    Return a dict of {camera_id: info_dict} for libcamera devices,
    or an empty dict if libcamera is not available.
    """
    try:
        from xpra.platform.posix.webcam import get_libcamera_devices
        return get_libcamera_devices()
    except (ImportError, Exception) as e:
        log("libcamera devices not available: %s", e)
        return {}


def _parse_device_no(device_str: str, non_virtual: dict[int, Any]) -> int:
    """
    Convert a device string such as "auto", "0", or "/dev/video2"
    to an integer device number for cv2.VideoCapture.
    """
    if device_str in AUTO_OPTIONS:
        if non_virtual:
            return next(iter(non_virtual))
        return 0
    try:
        return int(device_str)
    except ValueError:
        pass
    # Try to extract the number from paths like "/dev/video2"
    p = device_str.find("video")
    if p >= 0:
        try:
            return int(device_str[p + len("video"):])
        except ValueError:
            pass
    return 0


def open_camera(
    device_str: str,
    virt_devices: dict[int, Any],
    non_virtual: dict[int, Any],
) -> CameraDevice:
    """
    Open a camera device appropriate for *device_str*.

    Selection priority:
    1. If libcamera is available and *device_str* matches a known camera ID
       (or is an AUTO_OPTIONS value), use LibcameraCamera.
    2. Otherwise fall back to CV2Camera.

    Parameters
    ----------
    device_str:
        The webcam option string from xpra configuration.
    virt_devices:
        Dict of virtual v4l2 device numbers (used to warn / skip).
    non_virtual:
        Dict of non-virtual v4l2 device numbers (used for "auto" selection).
    """
    lc_devices = _get_libcamera_devices()
    if lc_devices:
        camera_id: str | None = None
        if device_str in lc_devices:
            camera_id = device_str
        elif device_str in AUTO_OPTIONS:
            camera_id = next(iter(lc_devices))
        if camera_id is not None:
            log("using libcamera backend for %r (camera_id=%r)", device_str, camera_id)
            from xpra.client.webcam.libcamera_camera import LibcameraCamera
            return LibcameraCamera(camera_id)

    device_no = _parse_device_no(device_str, non_virtual)
    log("using cv2 backend for %r (device_no=%i)", device_str, device_no)
    from xpra.client.webcam.cv2_camera import CV2Camera
    return CV2Camera(device_no)


def make_csc_to_bgrx(src_format: str, w: int, h: int):
    """
    Create and initialise a CSC converter that converts *src_format* → BGRX,
    or return None if *src_format* is already BGRX.

    Tries libyuv first (supports NV12, YUYV), then csc_cython as a fallback.
    Returns None if no suitable converter is found.

    Note: libcamera support requires xpra-codecs compiled with libyuv.
    """
    if src_format == "BGRX":
        return None
    for mod_name in ("libyuv.converter", "csc_cython.converter"):
        try:
            from importlib import import_module
            mod = import_module(f"xpra.codecs.{mod_name}")
        except ImportError:
            continue
        try:
            specs = mod.get_specs(src_format, "BGRX")
        except Exception:
            continue
        for spec in specs:
            try:
                conv = spec.codec_class()
                conv.init_context(w, h, src_format, w, h, "BGRX", {})
                log("make_csc_to_bgrx: using %s for %s->BGRX", mod_name, src_format)
                return conv
            except Exception as e:
                log("make_csc_to_bgrx: %s spec failed: %s", mod_name, e)
    log.warn("Warning: no CSC converter found for %s→BGRX", src_format)
    log.warn(" libcamera webcam frames will not be forwarded correctly")
    log.warn(" ensure xpra-codecs is built with libyuv support")
    return None
