# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Webcam capture abstraction.

Provides a unified factory (open_camera) that selects a platform capture
backend (DirectShow on Windows, AVFoundation on macOS, libcamera on Linux),
plus CSC helpers.

Usage::

    from xpra.webcam import open_camera, make_csc

    device = open_camera(device_str)
    csc = make_csc(device.pixel_format, device.width, device.height, ("BGRX", ))

    image = device.read()
    if image is not None and csc is not None:
        image = csc.convert_image(image)

    device.release()
    if csc is not None:
        csc.clean()
"""

import sys
from collections.abc import Sequence
from typing import Any

from xpra.webcam.base import CameraDevice
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
    except ImportError as e:
        log("libcamera not available: %s", e)
        return {}
    try:
        return get_libcamera_devices()
    except Exception:
        log.error("Error querying libcamera devices", exc_info=True)
        return {}


def _find_libcamera_id(device_str: str, lc_devices: dict[str, dict[str, Any]]) -> str:
    """
    Return the libcamera camera_id matching *device_str*, or "".

    Matches against:
    - the camera_id itself (exact match)
    - any /dev/videoN path exposed via the camera's SystemDevices
    - a bare video-device number (e.g. "0" -> "/dev/video0")
    """
    if device_str in lc_devices:
        return device_str
    path = device_str
    if path.isdigit():
        path = f"/dev/video{path}"
    for cid, info in lc_devices.items():
        paths = info.get("devices") or ([info["device"]] if info.get("device") else [])
        if path in paths:
            return cid
    return ""


def open_camera(device_str: str) -> CameraDevice | None:
    """
    Open a camera device appropriate for *device_str*, or return None if no
    capture backend is available.

    Selection priority:
    1. (Windows) If DirectShow devices are available, use DirectShowCamera.
    2. (macOS) If AVFoundation devices are available, use AVFoundationCamera.
    3. (Linux) If libcamera is available and *device_str* matches a known
       camera ID (or is an AUTO_OPTIONS value), use LibcameraCamera.
    """
    log("open_camera(%s)", device_str)

    if sys.platform == "win32":
        from xpra.platform.win32.webcam import _get_directshow_devices, _find_directshow_index

        ds_devices = _get_directshow_devices()
        log("directshow_devices=%s", ds_devices)
        if ds_devices:
            device_index = _find_directshow_index(device_str, ds_devices)
            log("using DirectShow backend for %r (device_index=%i)", device_str, device_index)
            from xpra.platform.win32.directshow_camera import DirectShowCamera
            return DirectShowCamera(device_index)

    if sys.platform == "darwin":
        from xpra.platform.darwin.webcam import _get_avfoundation_devices, _find_avfoundation_id

        avf_devices = _get_avfoundation_devices()
        log("avfoundation_devices=%s", avf_devices)
        if avf_devices:
            unique_id = _find_avfoundation_id(device_str, avf_devices)
            if unique_id:
                log("using AVFoundation backend for %r (uniqueID=%r)", device_str, unique_id)
                from xpra.platform.darwin.avfoundation_camera import AVFoundationCamera
                return AVFoundationCamera(unique_id)

    lc_devices = _get_libcamera_devices()
    log("libcamera_devices=%s", lc_devices)
    if lc_devices:
        if device_str in AUTO_OPTIONS:
            camera_id = next(iter(lc_devices))
        else:
            camera_id = _find_libcamera_id(device_str, lc_devices)
        if camera_id:
            log("using libcamera backend for %r (camera_id=%r)", device_str, camera_id)
            from xpra.webcam.libcamera_camera import LibcameraCamera
            return LibcameraCamera(camera_id)

    log.warn("Warning: no webcam capture backend available for %r", device_str)
    return None


def make_csc(src_format: str, w: int, h: int, dst_formats: Sequence[str]):
    """
    Create and initialise a CSC converter from *src_format* to the first
    matching format in *dst_formats*, or return None if none is found.

    Discovers available CSC modules via the codec loader (get_csc_modules /
    load_codec) so the choice of backend is determined by what is installed,
    without relying on the global VideoHelper singleton being pre-initialised.
    """
    dst_formats = [f for f in dst_formats if f != src_format]
    if not dst_formats:
        return None
    from xpra.codecs.loader import load_codec
    from xpra.codecs.video import get_csc_modules
    from xpra.util.objects import typedict
    for dst_format in dst_formats:
        for name in get_csc_modules():
            mod = load_codec(name)
            if mod is None:
                continue
            for spec in mod.get_specs():
                if spec.input_colorspace != src_format:
                    continue
                if dst_format not in spec.output_colorspaces:
                    continue
                try:
                    conv = spec.codec_class()
                    conv.init_context(w, h, src_format, w, h, dst_format, typedict())
                    log("make_csc: using %s (%s) for %s->%s", name, spec.codec_class, src_format, dst_format)
                    return conv
                except Exception as e:
                    log("make_csc: %s spec failed: %s", name, e)
    log.warn("Warning: no CSC converter found for %s→%s", src_format, dst_formats)
    return None
