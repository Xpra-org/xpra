# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
macOS webcam platform glue: AVFoundation device enumeration + hot-plug.

Mirrors :mod:`xpra.platform.win32.webcam` (post-DirectShow capture support):
the public helpers ``_get_avfoundation_devices`` and ``_find_avfoundation_id``
are consumed by :func:`xpra.webcam.open_camera`.
"""

from typing import Any
from collections.abc import Callable

from xpra.log import Logger

log = Logger("webcam")

AUTO_OPTIONS = ("auto", "on", "yes", "true")


def get_avfoundation_devices() -> dict[str, dict[str, Any]]:
    """
    Return a dict of ``{uniqueID: info}`` for AVFoundation video capture devices.

    Uses ``AVCaptureDeviceDiscoverySession`` (macOS 10.15+) when available,
    falling back to the deprecated ``+devicesWithMediaType:`` API.
    Returns an empty dict if AVFoundation cannot be imported.
    """
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeVideo
    except ImportError as e:
        log("AVFoundation not available: %s", e)
        return {}

    devices = []
    try:
        import AVFoundation as _avf
        device_types: list = [_avf.AVCaptureDeviceTypeBuiltInWideAngleCamera]
        # External camera types vary across macOS versions; pick up whatever is present.
        for name in ("AVCaptureDeviceTypeExternal",
                     "AVCaptureDeviceTypeExternalUnknown",
                     "AVCaptureDeviceTypeDeskViewCamera",
                     "AVCaptureDeviceTypeContinuityCamera"):
            constant = getattr(_avf, name, None)
            if constant is not None:
                device_types.append(constant)
        session = _avf.AVCaptureDeviceDiscoverySession.\
            discoverySessionWithDeviceTypes_mediaType_position_(
                device_types, AVMediaTypeVideo, 0,
            )
        devices = list(session.devices() or ())
        log("discovery-session devices: %s", devices)
    except (ImportError, AttributeError) as e:
        log("AVCaptureDeviceDiscoverySession unavailable (%s), falling back", e)

    if not devices:
        try:
            devices = list(AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo) or ())
            log("devicesWithMediaType: %s", devices)
        except Exception as e:
            log("devicesWithMediaType_() failed: %s", e)
            return {}

    result: dict[str, dict[str, Any]] = {}
    for device in devices:
        try:
            unique_id = str(device.uniqueID())
        except Exception:
            continue
        info = {
            "card": str(device.localizedName()),
            "device": unique_id,
            "description": str(device.modelID()),
        }
        result[unique_id] = info
    return result


def _get_avfoundation_devices() -> dict[str, dict[str, Any]]:
    """Wrapper used by :func:`xpra.webcam.open_camera`. Never raises."""
    try:
        return get_avfoundation_devices()
    except Exception as e:
        log("_get_avfoundation_devices() error: %s", e)
        return {}


def _find_avfoundation_id(device_str: str, avf_devices: dict[str, dict[str, Any]]) -> str:
    """
    Map *device_str* to an AVFoundation ``uniqueID``.

    Matches against:
    - automatic device selection values ("auto", "on", "yes", "true")
    - an exact ``uniqueID`` already present in *avf_devices*
    - a bare integer ("0", "1", ...) indexed into enumeration order
    Returns ``""`` if no match.
    """
    if not avf_devices:
        return ""
    if device_str in AUTO_OPTIONS:
        return next(iter(avf_devices))
    if device_str in avf_devices:
        return device_str
    try:
        idx = int(device_str)
    except ValueError:
        return ""
    ids = list(avf_devices.keys())
    if 0 <= idx < len(ids):
        return ids[idx]
    return ""


def get_all_video_devices(capture_only=True) -> dict[int, dict[str, Any]]:
    """
    Required by :mod:`xpra.platform.webcam`'s contract (integer-keyed).
    Indexes over the AVFoundation enumeration.
    """
    return {i: info for i, info in enumerate(get_avfoundation_devices().values())}


def get_virtual_video_devices() -> dict:
    # No v4l2loopback equivalent on macOS.
    return {}


# ── Hot-plug notifications ─────────────────────────────────────────────────────

_observer = None


def _build_observer():
    """Create the NSObject observer class lazily so AVFoundation import
    failures don't break module load."""
    import objc
    from Foundation import NSObject

    class _DeviceObserver(NSObject):
        @objc.typedSelector(b'v@:@')
        def deviceChanged_(self, notification):
            log("AVFoundation deviceChanged: %s", notification)
            from xpra.platform.webcam import _fire_video_device_change
            _fire_video_device_change()

    return _DeviceObserver


def _install_observer() -> None:
    global _observer
    if _observer is not None:
        return
    try:
        from Foundation import NSNotificationCenter
        from AVFoundation import (
            AVCaptureDeviceWasConnectedNotification,
            AVCaptureDeviceWasDisconnectedNotification,
        )
    except ImportError as e:
        log("hot-plug notifications unavailable: %s", e)
        return
    try:
        observer_cls = _build_observer()
        _observer = observer_cls.alloc().init()
        nc = NSNotificationCenter.defaultCenter()
        nc.addObserver_selector_name_object_(
            _observer, b"deviceChanged:",
            AVCaptureDeviceWasConnectedNotification, None,
        )
        nc.addObserver_selector_name_object_(
            _observer, b"deviceChanged:",
            AVCaptureDeviceWasDisconnectedNotification, None,
        )
        log("installed AVFoundation device-change observer")
    except Exception:
        log("error installing AVFoundation device-change observer", exc_info=True)
        _observer = None


def _uninstall_observer() -> None:
    global _observer
    if _observer is None:
        return
    try:
        from Foundation import NSNotificationCenter
        NSNotificationCenter.defaultCenter().removeObserver_(_observer)
    except Exception:
        log("error removing AVFoundation device-change observer", exc_info=True)
    _observer = None


def add_video_device_change_callback(callback: Callable) -> None:
    from xpra.platform.webcam import _video_device_change_callbacks
    log("add_video_device_change_callback(%s)", callback)
    if not _video_device_change_callbacks:
        _install_observer()
    _video_device_change_callbacks.append(callback)


def remove_video_device_change_callback(callback: Callable) -> None:
    from xpra.platform.webcam import _video_device_change_callbacks
    log("remove_video_device_change_callback(%s)", callback)
    if callback in _video_device_change_callbacks:
        _video_device_change_callbacks.remove(callback)
    if not _video_device_change_callbacks:
        _uninstall_observer()
