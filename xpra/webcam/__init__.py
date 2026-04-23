# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Webcam capture abstraction.

Provides a unified factory (open_camera) that selects between libcamera
(preferred on Linux when available) and cv2 (OpenCV) backends, plus CSC helpers.

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
        return get_libcamera_devices()
    except (ImportError, Exception) as e:
        log("libcamera devices not available: %s", e)
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


def open_camera(device_str: str) -> CameraDevice | None:
    """
    Open a camera device appropriate for *device_str*, or return None if the
    device should not be used.

    Selection priority:
    1. If libcamera is available and *device_str* matches a known camera ID
       (or is an AUTO_OPTIONS value), use LibcameraCamera.
    2. Otherwise fall back to CV2Camera.

    When a CV2Camera lands on a virtual v4l2 device number, a warning is
    logged and None is returned unless XPRA_WEBCAM_ALLOW_VIRTUAL is set.
    """
    log("open_camera(%s)", device_str)
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

    virt_devices: dict[int, Any] = {}
    non_virtual: dict[int, Any] = {}
    try:
        from xpra.platform.webcam import get_virtual_video_devices, get_all_video_devices
        virt_devices = get_virtual_video_devices()
        all_video_devices = get_all_video_devices()  # pylint: disable=assignment-from-none
        non_virtual = {k: v for k, v in all_video_devices.items() if k not in virt_devices}
        log("virtual video devices=%s", virt_devices)
        log("all video devices=%s", all_video_devices)
        log("found %s non-virtual video devices: %s", len(non_virtual), non_virtual)
    except ImportError as e:
        log("no webcam_util: %s", e)

    device_no = _parse_device_no(device_str, non_virtual)
    log("using cv2 backend for %r (device_no=%i)", device_str, device_no)
    from xpra.webcam.cv2_camera import CV2Camera
    from xpra.util.env import envbool
    webcam_device = CV2Camera(device_no)
    if virt_devices and device_no in virt_devices:
        log.warn("Warning: video device %s is a virtual device", virt_devices.get(device_no, device_no))
        if envbool("XPRA_WEBCAM_ALLOW_VIRTUAL", False):
            log.warn(" environment override - this may hang..")
        else:
            log.warn(" cowardly refusing to use it")
            log.warn(" set XPRA_WEBCAM_ALLOW_VIRTUAL=1 to force enable it")
            webcam_device.release()
            return None
    return webcam_device


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
