# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Awareness-independent monitor geometry via the win32 `QueryDisplayConfig` API.

Unlike `GetSystemMetrics` / `GetMonitorInfo`, which return coordinates in the
*process's* DPI-awareness space (physical pixels only when Per-Monitor-v2 aware),
`QueryDisplayConfig` reports the low-level display topology directly, so the
result does not depend on the caller's DPI awareness at all.

For every active path it exposes two distinct things:
 * the SOURCE mode: the desktop *surface* (in true device pixels) and its origin
   in the virtual desktop - this is the coordinate space that windows and the
   pointer actually live in.
 * the TARGET mode: the actual scanout raster sent to the panel (active/total
   size, pixel clock and vertical refresh) - i.e. what the GPU scans out.

When the SOURCE size differs from the TARGET active size, a hardware/GPU scaler
sits between the desktop surface and the panel (e.g. a non-native resolution
selected with GPU scaling), so the window coordinate space cannot be 1:1 with
scanout - see `scaled` in the returned dictionaries.
"""

from typing import Any
from ctypes import (
    Structure, Union, POINTER, byref, sizeof,
    c_uint16, c_uint32, c_int32, c_uint64,
)
from ctypes.wintypes import WCHAR, LONG

from xpra.platform.win32.common import user32
from xpra.log import Logger

log = Logger("win32", "screen")

# QueryDisplayConfig flags:
QDC_ONLY_ACTIVE_PATHS = 0x00000002

# DISPLAYCONFIG_MODE_INFO_TYPE:
DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE = 1
DISPLAYCONFIG_MODE_INFO_TYPE_TARGET = 2

# DISPLAYCONFIG_DEVICE_INFO_TYPE:
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2

# marks `modeInfoIdx` as unused (newer per-source/target index fields in use):
DISPLAYCONFIG_PATH_MODE_IDX_INVALID = 0xFFFFFFFF

# DISPLAYCONFIG_SCALING values (path.targetInfo.scaling):
SCALING_NAMES: dict[int, str] = {
    1: "identity",
    2: "centered",
    3: "stretched",
    4: "aspect-ratio-centered-max",
    5: "custom",
    128: "preferred",
}

ERROR_SUCCESS = 0
CCHDEVICENAME = 32

UINT32 = c_uint32
INT32 = c_int32
UINT64 = c_uint64


class LUID(Structure):
    _fields_ = [
        ("LowPart", UINT32),
        ("HighPart", INT32),
    ]


class POINTL(Structure):
    _fields_ = [
        ("x", LONG),
        ("y", LONG),
    ]


class RECTL(Structure):
    _fields_ = [
        ("left", LONG),
        ("top", LONG),
        ("right", LONG),
        ("bottom", LONG),
    ]


class DISPLAYCONFIG_RATIONAL(Structure):
    _fields_ = [
        ("Numerator", UINT32),
        ("Denominator", UINT32),
    ]

    def as_float(self) -> float:
        return self.Numerator / self.Denominator if self.Denominator else 0.0


class DISPLAYCONFIG_PATH_SOURCE_INFO(Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", UINT32),
        ("modeInfoIdx", UINT32),
        ("statusFlags", UINT32),
    ]


class DISPLAYCONFIG_PATH_TARGET_INFO(Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", UINT32),
        ("modeInfoIdx", UINT32),
        ("outputTechnology", UINT32),
        ("rotation", UINT32),
        ("scaling", UINT32),
        ("refreshRate", DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", UINT32),
        ("targetAvailable", UINT32),  # BOOL
        ("statusFlags", UINT32),
    ]


class DISPLAYCONFIG_PATH_INFO(Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", UINT32),
    ]


class DISPLAYCONFIG_2DREGION(Structure):
    _fields_ = [
        ("cx", UINT32),
        ("cy", UINT32),
    ]


class DISPLAYCONFIG_VIDEO_SIGNAL_INFO(Structure):
    _fields_ = [
        ("pixelRate", UINT64),
        ("hSyncFreq", DISPLAYCONFIG_RATIONAL),
        ("vSyncFreq", DISPLAYCONFIG_RATIONAL),
        ("activeSize", DISPLAYCONFIG_2DREGION),
        ("totalSize", DISPLAYCONFIG_2DREGION),
        ("videoStandard", UINT32),
        ("scanLineOrdering", UINT32),
    ]


class DISPLAYCONFIG_TARGET_MODE(Structure):
    _fields_ = [
        ("targetVideoSignalInfo", DISPLAYCONFIG_VIDEO_SIGNAL_INFO),
    ]


class DISPLAYCONFIG_SOURCE_MODE(Structure):
    _fields_ = [
        ("width", UINT32),
        ("height", UINT32),
        ("pixelFormat", UINT32),
        ("position", POINTL),
    ]


class DISPLAYCONFIG_DESKTOP_IMAGE_INFO(Structure):
    _fields_ = [
        ("PathSourceSize", POINTL),
        ("DesktopImageRegion", RECTL),
        ("DesktopImageClip", RECTL),
    ]


class DISPLAYCONFIG_MODE_INFO_union(Union):
    _fields_ = [
        ("targetMode", DISPLAYCONFIG_TARGET_MODE),
        ("sourceMode", DISPLAYCONFIG_SOURCE_MODE),
        ("desktopImageInfo", DISPLAYCONFIG_DESKTOP_IMAGE_INFO),
    ]


class DISPLAYCONFIG_MODE_INFO(Structure):
    _anonymous_ = ("u", )
    _fields_ = [
        ("infoType", UINT32),
        ("id", UINT32),
        ("adapterId", LUID),
        ("u", DISPLAYCONFIG_MODE_INFO_union),
    ]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(Structure):
    _fields_ = [
        ("type", UINT32),
        ("size", UINT32),
        ("adapterId", LUID),
        ("id", UINT32),
    ]


class DISPLAYCONFIG_SOURCE_DEVICE_NAME(Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", WCHAR * CCHDEVICENAME),
    ]


class DISPLAYCONFIG_TARGET_DEVICE_NAME(Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        # `flags` is a bitfield; bit 2 (`edidIdsValid`) tells us whether the
        # EDID manufacturer / product ids below are populated:
        ("flags", UINT32),
        ("outputTechnology", UINT32),
        ("edidManufactureId", c_uint16),
        ("edidProductCodeId", c_uint16),
        ("connectorInstance", UINT32),
        ("monitorFriendlyDeviceName", WCHAR * 64),
        ("monitorDevicePath", WCHAR * 128),
    ]


# DISPLAYCONFIG_TARGET_DEVICE_NAME_FLAGS.edidIdsValid:
DISPLAYCONFIG_EDID_IDS_VALID = 0x4


GetDisplayConfigBufferSizes = user32.GetDisplayConfigBufferSizes
GetDisplayConfigBufferSizes.argtypes = [UINT32, POINTER(UINT32), POINTER(UINT32)]
GetDisplayConfigBufferSizes.restype = LONG

QueryDisplayConfig = user32.QueryDisplayConfig
QueryDisplayConfig.argtypes = [
    UINT32, POINTER(UINT32), POINTER(DISPLAYCONFIG_PATH_INFO),
    POINTER(UINT32), POINTER(DISPLAYCONFIG_MODE_INFO), POINTER(UINT32),
]
QueryDisplayConfig.restype = LONG

DisplayConfigGetDeviceInfo = user32.DisplayConfigGetDeviceInfo
DisplayConfigGetDeviceInfo.argtypes = [POINTER(DISPLAYCONFIG_DEVICE_INFO_HEADER)]
DisplayConfigGetDeviceInfo.restype = LONG


def _source_device_name(adapter_id: LUID, source_id: int) -> str:
    # resolve the GDI device name (ie: "\\.\DISPLAY1") for a source,
    # so the result can be correlated with `GetMonitorInfo` / `EnumDisplayMonitors`:
    req = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
    req.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
    req.header.size = sizeof(DISPLAYCONFIG_SOURCE_DEVICE_NAME)
    req.header.adapterId = adapter_id
    req.header.id = source_id
    if DisplayConfigGetDeviceInfo(byref(req.header)) != ERROR_SUCCESS:
        return ""
    return req.viewGdiDeviceName


def _decode_pnp_id(edid_mfg: int) -> str:
    # Windows returns the EDID manufacturer id as a little-endian WORD; swap it
    # back to EDID byte order, then unpack the three 5-bit letter codes (1 = 'A'):
    v = ((edid_mfg & 0xff) << 8) | ((edid_mfg >> 8) & 0xff)
    letters = "".join(chr(((v >> shift) & 0x1f) + 0x40) for shift in (10, 5, 0))
    # only accept it if every code maps to an uppercase letter (ie: "DEL", "SAM"):
    if all("A" <= c <= "Z" for c in letters):
        return letters
    return ""


def _target_device_name(adapter_id: LUID, target_id: int) -> tuple[str, str]:
    # resolve the human-friendly model name (ie: "DELL U2415") and the EDID
    # manufacturer PNP id (ie: "DEL") for a target - the physical panel behind
    # a source. Empty strings are returned when the data is unavailable:
    req = DISPLAYCONFIG_TARGET_DEVICE_NAME()
    req.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME
    req.header.size = sizeof(DISPLAYCONFIG_TARGET_DEVICE_NAME)
    req.header.adapterId = adapter_id
    req.header.id = target_id
    if DisplayConfigGetDeviceInfo(byref(req.header)) != ERROR_SUCCESS:
        return "", ""
    model = req.monitorFriendlyDeviceName or ""
    manufacturer = ""
    if req.flags & DISPLAYCONFIG_EDID_IDS_VALID:
        manufacturer = _decode_pnp_id(req.edidManufactureId)
    return manufacturer, model


def get_display_config() -> dict[str, dict[str, Any]]:
    """
    Query the active display topology.

    Returns a dictionary keyed by GDI device name (ie: "\\\\.\\DISPLAY1"), each
    value describing the SOURCE (desktop surface) and TARGET (scanout) modes in
    true device pixels, independently of the process DPI awareness.
    """
    num_paths = UINT32(0)
    num_modes = UINT32(0)
    r = GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, byref(num_paths), byref(num_modes))
    if r != ERROR_SUCCESS:
        log("GetDisplayConfigBufferSizes() failed with error %i", r)
        return {}
    paths = (DISPLAYCONFIG_PATH_INFO * num_paths.value)()
    modes = (DISPLAYCONFIG_MODE_INFO * num_modes.value)()
    r = QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS,
                           byref(num_paths), paths,
                           byref(num_modes), modes, None)
    if r != ERROR_SUCCESS:
        log("QueryDisplayConfig() failed with error %i", r)
        return {}
    info: dict[str, dict[str, Any]] = {}
    for path in paths[:num_paths.value]:
        src_idx = path.sourceInfo.modeInfoIdx
        tgt_idx = path.targetInfo.modeInfoIdx
        entry: dict[str, Any] = {}
        if src_idx != DISPLAYCONFIG_PATH_MODE_IDX_INVALID and src_idx < num_modes.value:
            mode = modes[src_idx]
            if mode.infoType == DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE:
                sm = mode.sourceMode
                entry["source"] = {
                    "position": (sm.position.x, sm.position.y),
                    "width": sm.width,
                    "height": sm.height,
                }
        if tgt_idx != DISPLAYCONFIG_PATH_MODE_IDX_INVALID and tgt_idx < num_modes.value:
            mode = modes[tgt_idx]
            if mode.infoType == DISPLAYCONFIG_MODE_INFO_TYPE_TARGET:
                vsi = mode.targetMode.targetVideoSignalInfo
                entry["target"] = {
                    "active-size": (vsi.activeSize.cx, vsi.activeSize.cy),
                    "total-size": (vsi.totalSize.cx, vsi.totalSize.cy),
                    "pixel-clock": vsi.pixelRate,
                    # vertical refresh in mHz (to match xpra's "refresh-rate" convention):
                    "refresh-rate": round(vsi.vSyncFreq.as_float() * 1000),
                }
        entry["scaling"] = SCALING_NAMES.get(path.targetInfo.scaling, "unknown")
        # a hardware/GPU scaler is in the path when the desktop surface size
        # differs from the scanned-out active raster:
        src = entry.get("source")
        tgt = entry.get("target")
        name = _source_device_name(path.sourceInfo.adapterId, path.sourceInfo.id)
        if src and tgt:
            scaled = (src["width"], src["height"]) != tgt["active-size"]
            entry["scaled"] = scaled
            if scaled:
                # the desktop surface (where windows and the pointer live) does not
                # match the scanned-out raster, so a hardware/GPU scaler is in the
                # path and window coordinates cannot be 1:1 with GPU scanout:
                log.info("monitor %s: %ix%i desktop surface scaled to %ix%i scanout (%s)",
                         name or "?", src["width"], src["height"],
                         tgt["active-size"][0], tgt["active-size"][1], entry["scaling"])
        if name:
            manufacturer, model = _target_device_name(path.targetInfo.adapterId, path.targetInfo.id)
            if manufacturer:
                entry["manufacturer"] = manufacturer
            if model:
                entry["model"] = model
            info[name] = entry
    log("get_display_config()=%s", info)
    return info
