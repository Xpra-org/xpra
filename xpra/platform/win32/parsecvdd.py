#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#
# ctypes bindings for the Parsec Virtual Display Driver (parsec-vdd).
# Based on the public C header:
#   https://github.com/nomi-san/parsec-vdd/blob/main/core/parsec-vdd.h
#
# The driver must be installed separately. It exposes a device interface that
# is opened via SetupDi, then controlled through DeviceIoControl IOCTL codes.
# A background ping (VddUpdate) must be sent at least every 100 ms to keep
# added virtual displays alive.
#
# Typical usage:
#   handle = open_device()
#   idx    = add_display(handle)        # returns display slot index (0-7)
#   # ... run shadow server targeting the new monitor ...
#   remove_display(handle, idx)
#   close_device(handle)

import sys
import threading
from ctypes import (
    Structure, POINTER,
    WinDLL, WinError, get_last_error,
    byref, sizeof, cast, create_string_buffer,
    c_void_p, c_char, c_short,
)
from ctypes.wintypes import HANDLE, DWORD, BOOL, WORD, LONG
from enum import IntEnum

from xpra.log import Logger

log = Logger("vdd")

# ---------------------------------------------------------------------------
# Windows API helpers
# ---------------------------------------------------------------------------

kernel32 = WinDLL("kernel32", use_last_error=True)
setupapi = WinDLL("setupapi", use_last_error=True)
cfgmgr32 = WinDLL("CfgMgr32", use_last_error=True)

INVALID_HANDLE_VALUE = HANDLE(-1).value

GENERIC_READ    = 0x80000000
GENERIC_WRITE   = 0x40000000
FILE_SHARE_READ  = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING   = 3
FILE_ATTRIBUTE_NORMAL      = 0x00000080
FILE_FLAG_NO_BUFFERING     = 0x20000000
FILE_FLAG_OVERLAPPED       = 0x40000000
FILE_FLAG_WRITE_THROUGH    = 0x80000000

DIGCF_PRESENT         = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
DIGCF_ALLCLASSES      = 0x00000004

SPDRP_HARDWAREID = 1
REG_SZ           = 1
REG_MULTI_SZ     = 7

DN_DRIVER_LOADED = 0x00000002
DN_STARTED       = 0x00000008
DN_HAS_PROBLEM   = 0x00000400

CM_PROB_NEED_RESTART      = 0x0000000E
CM_PROB_DISABLED          = 0x0000001D
CM_PROB_HARDWARE_DISABLED = 0x00000046
CM_PROB_DISABLED_SERVICE  = 0x00000020
CM_PROB_FAILED_POST_START = 0x0000002B

CR_SUCCESS = 0x00000000


# ---------------------------------------------------------------------------
# SetupDi structures
# ---------------------------------------------------------------------------

class GUID(Structure):
    _fields_ = [
        ("Data1", DWORD),
        ("Data2", WORD),
        ("Data3", WORD),
        ("Data4", c_char * 8),
    ]

    def __init__(self, data1=0, data2=0, data3=0, data4=b"\x00" * 8):
        super().__init__()
        self.Data1 = data1
        self.Data2 = data2
        self.Data3 = data3
        self.Data4 = data4


class SP_DEVINFO_DATA(Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("ClassGuid", GUID),
        ("DevInst", DWORD),
        ("Reserved", c_void_p),
    ]

    def __init__(self):
        super().__init__()
        self.cbSize = sizeof(self)


class SP_DEVICE_INTERFACE_DATA(Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", DWORD),
        ("Reserved", c_void_p),
    ]

    def __init__(self):
        super().__init__()
        self.cbSize = sizeof(self)


class SP_DEVICE_INTERFACE_DETAIL_DATA_A(Structure):
    # Variable-length; we allocate a buffer and cast to this type.
    _fields_ = [
        ("cbSize", DWORD),
        ("DevicePath", c_char * 1),   # placeholder — actual path follows
    ]


class OVERLAPPED(Structure):
    _fields_ = [
        ("Internal", c_void_p),
        ("InternalHigh", c_void_p),
        ("Offset", DWORD),
        ("OffsetHigh", DWORD),
        ("hEvent", HANDLE),
    ]


# ---------------------------------------------------------------------------
# Parsec VDD constants
# ---------------------------------------------------------------------------

VDD_DISPLAY_ID   = b"PSCCDD0"
VDD_DISPLAY_NAME = b"ParsecVDA"
VDD_ADAPTER_NAME = b"Parsec Virtual Display Adapter"
VDD_HARDWARE_ID  = b"Root\\Parsec\\VDA"

# Adapter GUID: {00b41627-04c4-429e-a26e-0265cf50c8fa}
VDD_ADAPTER_GUID = GUID(
    0x00b41627, 0x04c4, 0x429e,
    b"\xa2\x6e\x02\x65\xcf\x50\xc8\xfa",
)

# Class GUID (Display class): {4d36e968-e325-11ce-bfc1-08002be10318}
VDD_CLASS_GUID = GUID(
    0x4d36e968, 0xe325, 0x11ce,
    b"\xbf\xc1\x08\x00\x2b\xe1\x03\x18",
)

# Maximum virtual displays per adapter (driver supports 16; use 8 to avoid lag)
VDD_MAX_DISPLAYS = 8

# IOCTL codes (see header comments for CTL_CODE breakdown)
VDD_IOCTL_ADD     = 0x0022e004
VDD_IOCTL_REMOVE  = 0x0022a008
VDD_IOCTL_UPDATE  = 0x0022a00c
VDD_IOCTL_VERSION = 0x0022e010


# ---------------------------------------------------------------------------
# DeviceStatus
# ---------------------------------------------------------------------------

class DeviceStatus(IntEnum):
    OK                = 0   # Ready to use
    INACCESSIBLE      = 1   # Device node found but not accessible
    UNKNOWN           = 2   # Loaded but in an unrecognised state
    UNKNOWN_PROBLEM   = 3   # DN_HAS_PROBLEM with unrecognised problem code
    DISABLED          = 4   # Manually disabled
    DRIVER_ERROR      = 5   # CM_PROB_FAILED_POST_START
    RESTART_REQUIRED  = 6   # Needs reboot before use
    DISABLED_SERVICE  = 7   # Underlying service is disabled
    NOT_INSTALLED     = 8   # Hardware ID not found in device tree


# ---------------------------------------------------------------------------
# Low-level kernel32 / setupapi / cfgmgr32 bindings
# ---------------------------------------------------------------------------

_CreateEventA = kernel32.CreateEventA
_CreateEventA.restype  = HANDLE
_CreateEventA.argtypes = [c_void_p, BOOL, BOOL, c_void_p]

_CloseHandle = kernel32.CloseHandle
_CloseHandle.restype  = BOOL
_CloseHandle.argtypes = [HANDLE]

_CreateFileA = kernel32.CreateFileA
_CreateFileA.restype  = HANDLE
_CreateFileA.argtypes = [
    c_void_p, DWORD, DWORD, c_void_p, DWORD, DWORD, HANDLE,
]

_DeviceIoControl = kernel32.DeviceIoControl
_DeviceIoControl.restype  = BOOL
_DeviceIoControl.argtypes = [
    HANDLE, DWORD,                    # hDevice, dwIoControlCode
    c_void_p, DWORD,                  # lpInBuffer, nInBufferSize
    c_void_p, DWORD,                  # lpOutBuffer, nOutBufferSize
    POINTER(DWORD),                   # lpBytesReturned
    POINTER(OVERLAPPED),              # lpOverlapped
]

_GetOverlappedResultEx = kernel32.GetOverlappedResultEx
_GetOverlappedResultEx.restype  = BOOL
_GetOverlappedResultEx.argtypes = [
    HANDLE, POINTER(OVERLAPPED), POINTER(DWORD), DWORD, BOOL,
]

_SetupDiGetClassDevsA = setupapi.SetupDiGetClassDevsA
_SetupDiGetClassDevsA.restype  = HANDLE   # HDEVINFO
_SetupDiGetClassDevsA.argtypes = [
    POINTER(GUID), c_void_p, c_void_p, DWORD,
]

_SetupDiDestroyDeviceInfoList = setupapi.SetupDiDestroyDeviceInfoList
_SetupDiDestroyDeviceInfoList.restype  = BOOL
_SetupDiDestroyDeviceInfoList.argtypes = [HANDLE]

_SetupDiEnumDeviceInfo = setupapi.SetupDiEnumDeviceInfo
_SetupDiEnumDeviceInfo.restype  = BOOL
_SetupDiEnumDeviceInfo.argtypes = [HANDLE, DWORD, POINTER(SP_DEVINFO_DATA)]

_SetupDiGetDeviceRegistryPropertyA = setupapi.SetupDiGetDeviceRegistryPropertyA
_SetupDiGetDeviceRegistryPropertyA.restype  = BOOL
_SetupDiGetDeviceRegistryPropertyA.argtypes = [
    HANDLE, POINTER(SP_DEVINFO_DATA),
    DWORD, POINTER(DWORD), c_void_p, DWORD, POINTER(DWORD),
]

_SetupDiEnumDeviceInterfaces = setupapi.SetupDiEnumDeviceInterfaces
_SetupDiEnumDeviceInterfaces.restype  = BOOL
_SetupDiEnumDeviceInterfaces.argtypes = [
    HANDLE, c_void_p, POINTER(GUID), DWORD,
    POINTER(SP_DEVICE_INTERFACE_DATA),
]

_SetupDiGetDeviceInterfaceDetailA = setupapi.SetupDiGetDeviceInterfaceDetailA
_SetupDiGetDeviceInterfaceDetailA.restype  = BOOL
_SetupDiGetDeviceInterfaceDetailA.argtypes = [
    HANDLE, POINTER(SP_DEVICE_INTERFACE_DATA),
    c_void_p, DWORD, POINTER(DWORD), c_void_p,
]

_CM_Get_DevNode_Status = cfgmgr32.CM_Get_DevNode_Status
_CM_Get_DevNode_Status.restype  = DWORD   # CONFIGRET
_CM_Get_DevNode_Status.argtypes = [
    POINTER(DWORD), POINTER(DWORD), DWORD, DWORD,
]


# ---------------------------------------------------------------------------
# Device status query
# ---------------------------------------------------------------------------

def _iter_hardware_ids(class_guid: GUID | None = None) -> list[tuple[str, DWORD]]:
    """
    Enumerate all present devices, yielding (hardware_id_token, DevInst) pairs.
    Pass class_guid=None to scan all classes (DIGCF_ALLCLASSES).
    Used internally and by dump_devices() for diagnostics.
    """
    results = []
    flags = DIGCF_PRESENT | (DIGCF_ALLCLASSES if class_guid is None else 0)
    guid_ref = byref(class_guid) if class_guid is not None else None
    dev_info = _SetupDiGetClassDevsA(guid_ref, None, None, flags)
    if dev_info == INVALID_HANDLE_VALUE:
        return results

    try:
        dev_info_data = SP_DEVINFO_DATA()
        index = 0
        while _SetupDiEnumDeviceInfo(dev_info, index, byref(dev_info_data)):
            index += 1
            required = DWORD(0)
            _SetupDiGetDeviceRegistryPropertyA(
                dev_info, byref(dev_info_data),
                SPDRP_HARDWAREID, None, None, 0, byref(required),
            )
            if required.value == 0:
                continue
            buf = create_string_buffer(required.value)
            reg_type = DWORD(0)
            if not _SetupDiGetDeviceRegistryPropertyA(
                dev_info, byref(dev_info_data),
                SPDRP_HARDWAREID, byref(reg_type),
                buf, required.value, byref(required),
            ):
                continue
            if reg_type.value not in (REG_SZ, REG_MULTI_SZ):
                continue
            raw = buf.raw
            offset = 0
            while offset < len(raw):
                end = raw.find(b"\x00", offset)
                if end == offset:
                    break
                token = raw[offset:end].decode("ascii", errors="replace")
                results.append((token, dev_info_data.DevInst))
                offset = end + 1
    finally:
        _SetupDiDestroyDeviceInfoList(dev_info)
    return results


def dump_devices(filter_str: str = "parsec") -> None:
    """
    Print all device hardware IDs containing *filter_str* (case-insensitive).
    Run this to find the exact hardware ID and class registered by the driver.
    """
    print(f"Scanning all present devices (filter={filter_str!r}) …")
    needle = filter_str.lower()
    found  = 0
    for token, dev_inst in _iter_hardware_ids(class_guid=None):
        if needle in token.lower():
            print(f"  HardwareID : {token!r}   DevInst={dev_inst}")
            found += 1
    if found == 0:
        print("  (no matches — try a different filter or check Device Manager)")


def query_device_status() -> DeviceStatus:
    """
    Walk the device tree to find the Parsec VDA node and return its status.
    Mirrors QueryDeviceStatus() from parsec-vdd.h, but:
      - Scans ALL device classes (not just the Display class) so the search
        is not broken if the driver registers under an unexpected class.
      - Compares hardware IDs case-insensitively; Windows stores them
        uppercased (ROOT\\PARSEC\\VDA) even though the .inf may use mixed case.
    """
    target = VDD_HARDWARE_ID.decode("ascii").upper()

    dev_info = _SetupDiGetClassDevsA(None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if dev_info == INVALID_HANDLE_VALUE:
        return DeviceStatus.INACCESSIBLE

    status = DeviceStatus.NOT_INSTALLED
    try:
        dev_info_data = SP_DEVINFO_DATA()
        index = 0
        found = False

        while not found and _SetupDiEnumDeviceInfo(dev_info, index, byref(dev_info_data)):
            index += 1

            # Query required buffer size for SPDRP_HARDWAREID
            required = DWORD(0)
            _SetupDiGetDeviceRegistryPropertyA(
                dev_info, byref(dev_info_data),
                SPDRP_HARDWAREID, None, None, 0, byref(required),
            )
            if required.value == 0:
                continue

            buf      = create_string_buffer(required.value)
            reg_type = DWORD(0)
            if not _SetupDiGetDeviceRegistryPropertyA(
                dev_info, byref(dev_info_data),
                SPDRP_HARDWAREID, byref(reg_type),
                buf, required.value, byref(required),
            ):
                continue

            if reg_type.value not in (REG_SZ, REG_MULTI_SZ):
                continue

            # REG_MULTI_SZ: sequence of NUL-terminated strings, double-NUL at end
            raw    = buf.raw
            offset = 0
            matched = False
            while offset < len(raw):
                end = raw.find(b"\x00", offset)
                if end == offset:
                    break
                token = raw[offset:end].decode("ascii", errors="replace").upper()
                if token == target:
                    matched = True
                    break
                offset = end + 1

            if not matched:
                continue

            # Hardware ID matched — check CM device node status
            found       = True
            dev_status  = DWORD(0)
            problem_num = DWORD(0)
            cr = _CM_Get_DevNode_Status(
                byref(dev_status), byref(problem_num),
                dev_info_data.DevInst, 0,
            )
            if cr != CR_SUCCESS:
                status = DeviceStatus.NOT_INSTALLED
            elif dev_status.value & (DN_DRIVER_LOADED | DN_STARTED):
                status = DeviceStatus.OK
            elif dev_status.value & DN_HAS_PROBLEM:
                p = problem_num.value
                if p == CM_PROB_NEED_RESTART:
                    status = DeviceStatus.RESTART_REQUIRED
                elif p in (CM_PROB_DISABLED, CM_PROB_HARDWARE_DISABLED):
                    status = DeviceStatus.DISABLED
                elif p == CM_PROB_DISABLED_SERVICE:
                    status = DeviceStatus.DISABLED_SERVICE
                elif p == CM_PROB_FAILED_POST_START:
                    status = DeviceStatus.DRIVER_ERROR
                else:
                    status = DeviceStatus.UNKNOWN_PROBLEM
            else:
                status = DeviceStatus.UNKNOWN
    finally:
        _SetupDiDestroyDeviceInfoList(dev_info)

    return status


# ---------------------------------------------------------------------------
# Device handle management
# ---------------------------------------------------------------------------

def open_device() -> HANDLE:
    """
    Open a handle to the Parsec VDD adapter device.
    Returns a valid HANDLE or raises WinError / RuntimeError on failure.
    Mirrors OpenDeviceHandle() from parsec-vdd.h.
    Call close_device() when done.
    """
    dev_info = _SetupDiGetClassDevsA(
        byref(VDD_ADAPTER_GUID), None, None,
        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
    )
    if dev_info == INVALID_HANDLE_VALUE:
        raise WinError(get_last_error())

    handle = HANDLE(INVALID_HANDLE_VALUE)
    try:
        iface_data = SP_DEVICE_INTERFACE_DATA()
        i = 0
        while _SetupDiEnumDeviceInterfaces(
            dev_info, None, byref(VDD_ADAPTER_GUID), i, byref(iface_data),
        ):
            # First call: get required buffer size
            detail_size = DWORD(0)
            _SetupDiGetDeviceInterfaceDetailA(
                dev_info, byref(iface_data), None, 0, byref(detail_size), None,
            )

            if detail_size.value == 0:
                i += 1
                continue

            # Allocate buffer and set cbSize (sizeof the fixed part = 5 on x86/x64)
            detail_buf = create_string_buffer(detail_size.value)
            detail_ptr = cast(detail_buf, POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_A))
            detail_ptr.contents.cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_A)

            if _SetupDiGetDeviceInterfaceDetailA(
                dev_info, byref(iface_data),
                detail_ptr, detail_size.value, byref(detail_size), None,
            ):
                # DevicePath starts at offset 4 (after cbSize DWORD)
                path = detail_buf.raw[4:].split(b"\x00", 1)[0]
                h = _CreateFileA(
                    path,
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None,
                    OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL | FILE_FLAG_NO_BUFFERING | FILE_FLAG_OVERLAPPED | FILE_FLAG_WRITE_THROUGH,
                    None,
                )
                if h and h != HANDLE(INVALID_HANDLE_VALUE).value:
                    handle = HANDLE(h)
                    break

            i += 1
    finally:
        _SetupDiDestroyDeviceInfoList(dev_info)

    if handle.value == INVALID_HANDLE_VALUE or not handle.value:
        raise RuntimeError(
            "Failed to open Parsec VDD device handle. "
            "Is the driver installed and the device enabled?"
        )
    log("open_device() -> handle %#x", handle.value)
    return handle


def close_device(handle: HANDLE) -> None:
    """Close a handle previously returned by open_device()."""
    if handle and handle.value not in (0, INVALID_HANDLE_VALUE):
        log("close_device(%#x)", handle.value)
        _CloseHandle(handle)


# ---------------------------------------------------------------------------
# Core IOCTL helper
# ---------------------------------------------------------------------------

def _vdd_iocontrol(handle: HANDLE, code: int, data: bytes | None = None) -> int:
    """
    Send an IOCTL to the VDD adapter and return the DWORD output buffer.
    Uses overlapped I/O with a 5-second timeout, mirroring VddIoControl().
    Returns -1 on failure (does not raise, matches C behaviour).
    """
    if not handle or handle.value in (0, INVALID_HANDLE_VALUE):
        return -1

    in_buf = create_string_buffer(32)   # fixed 32-byte input buffer
    if data:
        n = min(len(data), 32)
        in_buf.raw = data[:n] + b"\x00" * (32 - n)

    out_buf    = DWORD(0)
    overlapped = OVERLAPPED()
    event      = _CreateEventA(None, True, False, None)
    if not event:
        return -1
    overlapped.hEvent = event

    try:
        transferred = DWORD(0)
        _DeviceIoControl(
            handle, code,
            in_buf, sizeof(in_buf),
            byref(out_buf), sizeof(out_buf),
            None,
            byref(overlapped),
        )
        if not _GetOverlappedResultEx(handle, byref(overlapped), byref(transferred), 5000, False):
            return -1
    finally:
        _CloseHandle(event)

    return out_buf.value


# ---------------------------------------------------------------------------
# Public VDD operations
# ---------------------------------------------------------------------------

def vdd_version(handle: HANDLE) -> int:
    """Return the driver minor version number."""
    return _vdd_iocontrol(handle, VDD_IOCTL_VERSION)


def vdd_update(handle: HANDLE) -> None:
    """
    Ping the driver to keep all virtual displays alive.
    Must be called at least every 100 ms from a background thread.
    """
    _vdd_iocontrol(handle, VDD_IOCTL_UPDATE)


def add_display(handle: HANDLE) -> int:
    """
    Plug a new virtual display.
    Returns the display slot index (0 .. VDD_MAX_DISPLAYS-1), or -1 on failure.
    The index is required for remove_display().
    """
    idx = _vdd_iocontrol(handle, VDD_IOCTL_ADD)
    vdd_update(handle)
    log("add_display() -> index %d", idx)
    return idx


def remove_display(handle: HANDLE, index: int) -> None:
    """
    Unplug the virtual display at *index*.
    The index must be the value originally returned by add_display().
    """
    # Driver expects a 16-bit big-endian index in the input buffer
    index_data = bytes([index & 0xFF, (index >> 8) & 0xFF])
    _vdd_iocontrol(handle, VDD_IOCTL_REMOVE, index_data)
    vdd_update(handle)
    log("remove_display(%d)", index)


# ---------------------------------------------------------------------------
# Monitor resolution by VDD slot  (used by shadow-device and WM_DISPLAYCHANGE)
# ---------------------------------------------------------------------------

class _DISPLAY_DEVICE(Structure):
    """DISPLAY_DEVICEA — passed to EnumDisplayDevicesA."""
    _fields_ = [
        ("cb", DWORD),
        ("DeviceName", c_char * 32),
        ("DeviceString", c_char * 128),
        ("StateFlags", DWORD),
        ("DeviceID", c_char * 128),
        ("DeviceKey", c_char * 128),
    ]

    def __init__(self):
        super().__init__()
        self.cb = sizeof(self)


# user32 — EnumDisplayDevicesA lives there, not in setupapi
_user32 = WinDLL("user32", use_last_error=True)
_EnumDisplayDevicesA = _user32.EnumDisplayDevicesA
_EnumDisplayDevicesA.restype  = BOOL
_EnumDisplayDevicesA.argtypes = [c_void_p, DWORD, POINTER(_DISPLAY_DEVICE), DWORD]

_DISPLAY_DEVICE_ACTIVE = 0x00000001   # adapter is part of the desktop


# ---------------------------------------------------------------------------
# Display mode enumeration / change  (EnumDisplaySettingsExA / ChangeDisplaySettingsExA)
# ---------------------------------------------------------------------------

class DEVMODEA(Structure):
    """Standard fixed-layout DEVMODEA — only the display fields are used here."""
    _fields_ = [
        ("dmDeviceName", c_char * 32),
        ("dmSpecVersion", WORD),
        ("dmDriverVersion", WORD),
        ("dmSize", WORD),
        ("dmDriverExtra", WORD),
        ("dmFields", DWORD),
        ("dmOrientation", c_short),
        ("dmPaperSize", c_short),
        ("dmPaperLength", c_short),
        ("dmPaperWidth", c_short),
        ("dmScale", c_short),
        ("dmCopies", c_short),
        ("dmDefaultSource", c_short),
        ("dmPrintQuality", c_short),
        ("dmColor", c_short),
        ("dmDuplex", c_short),
        ("dmYResolution", c_short),
        ("dmTTOption", c_short),
        ("dmCollate", c_short),
        ("dmFormName", c_char * 32),
        ("dmLogPixels", WORD),
        ("dmBitsPerPel", DWORD),
        ("dmPelsWidth", DWORD),
        ("dmPelsHeight", DWORD),
        ("dmDisplayFlags", DWORD),
        ("dmDisplayFrequency", DWORD),
        ("dmICMMethod", DWORD),
        ("dmICMIntent", DWORD),
        ("dmMediaType", DWORD),
        ("dmDitherType", DWORD),
        ("dmReserved1", DWORD),
        ("dmReserved2", DWORD),
        ("dmPanningWidth", DWORD),
        ("dmPanningHeight", DWORD),
    ]


ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
DM_BITSPERPEL        = 0x00040000
DM_PELSWIDTH         = 0x00080000
DM_PELSHEIGHT        = 0x00100000
DM_DISPLAYFREQUENCY  = 0x00400000
CDS_UPDATEREGISTRY   = 0x00000001
DISP_CHANGE_SUCCESSFUL = 0

_EnumDisplaySettingsExA = _user32.EnumDisplaySettingsExA
_EnumDisplaySettingsExA.restype  = BOOL
_EnumDisplaySettingsExA.argtypes = [c_void_p, DWORD, POINTER(DEVMODEA), DWORD]

_ChangeDisplaySettingsExA = _user32.ChangeDisplaySettingsExA
_ChangeDisplaySettingsExA.restype  = LONG
_ChangeDisplaySettingsExA.argtypes = [c_void_p, POINTER(DEVMODEA), HANDLE, DWORD, c_void_p]


def _device_path(device: str) -> bytes:
    """Normalise a 'DISPLAYn' or '\\\\.\\DISPLAYn' name to the bytes form the API expects."""
    name = device if device.startswith("\\\\.\\") else "\\\\.\\" + device
    return name.encode("ascii")


def set_resolution(device: str, width: int, height: int, refresh: int = 0) -> bool:
    """
    Change the resolution of the display *device* (e.g. "DISPLAY3").
    The requested mode must be advertised by the monitor's EDID.
    Returns True on success.
    """
    bname = _device_path(device)
    devmode = DEVMODEA()
    devmode.dmSize = sizeof(DEVMODEA)
    if not _EnumDisplaySettingsExA(bname, ENUM_CURRENT_SETTINGS, byref(devmode), 0):
        log.warn("Warning: cannot read current display settings for %r", device)
        return False
    devmode.dmPelsWidth = width
    devmode.dmPelsHeight = height
    devmode.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT
    if refresh > 0:
        devmode.dmDisplayFrequency = refresh
        devmode.dmFields |= DM_DISPLAYFREQUENCY
    r = _ChangeDisplaySettingsExA(bname, byref(devmode), None, CDS_UPDATEREGISTRY, None)
    if r != DISP_CHANGE_SUCCESSFUL:
        log.warn("Warning: failed to set %s to %ix%i (ChangeDisplaySettingsEx returned %i)",
                 device, width, height, r)
        return False
    log("set_resolution(%s, %i, %i) -> ok", device, width, height)
    return True


def get_supported_resolutions(device: str) -> list[tuple[int, int]]:
    """
    Enumerate the distinct (width, height) modes advertised by *device*,
    sorted largest first.  Used to probe a live VDD monitor's EDID.
    """
    bname = _device_path(device)
    devmode = DEVMODEA()
    devmode.dmSize = sizeof(DEVMODEA)
    seen: set[tuple[int, int]] = set()
    i = 0
    while _EnumDisplaySettingsExA(bname, i, byref(devmode), 0):
        i += 1
        seen.add((int(devmode.dmPelsWidth), int(devmode.dmPelsHeight)))
    res = sorted(seen, reverse=True)
    log("get_supported_resolutions(%s)=%s", device, res)
    return res


def list_vdd_monitors() -> list[str]:
    """
    Return the ``DISPLAYn`` names (without prefix) of every *active*
    parsec-vdd virtual monitor, in enumeration order.
    """
    adapter = _DISPLAY_DEVICE()
    out: list[str] = []
    i = 0
    while _EnumDisplayDevicesA(None, i, byref(adapter), 0):
        i += 1
        if adapter.DeviceString != VDD_ADAPTER_NAME:
            continue
        if not (adapter.StateFlags & _DISPLAY_DEVICE_ACTIVE):
            continue
        raw = adapter.DeviceName.decode("ascii", errors="replace")
        out.append(raw.lstrip("\\\\.\\"))
    return out


# A short, curated subset of the resolutions advertised by the parsec-vdd EDID,
# used to populate the client's "add monitor" menu before any VDD monitor exists.
# The driver actually advertises ~27 modes (retrievable from a live monitor via
# get_supported_resolutions()); we only offer the common ones here to keep the
# menu manageable. Every entry below has been confirmed present in the EDID, so
# ChangeDisplaySettings() will accept them.
VDD_DEFAULT_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (3840, 2160),   # 4K UHD
    (2560, 1440),   # QHD
    (1920, 1200),   # WUXGA (16:10)
    (1920, 1080),   # FHD
    (1600, 900),
    (1366, 768),
    (1280, 720),    # HD
)


def get_vdd_resolutions() -> list[str]:
    """Return the parsec-vdd default resolutions as ``"WxH"`` strings."""
    return ["%ix%i" % (w, h) for w, h in VDD_DEFAULT_RESOLUTIONS]


def find_monitor_by_slot(slot_index: int) -> str:
    """
    Return the current ``DISPLAYn`` name (without any ``\\\\.\\`` prefix) for
    the parsec-vdd virtual display at *slot_index*.

    Iterates all display adapters via ``EnumDisplayDevicesA``, counts those
    whose ``DeviceString`` matches ``VDD_ADAPTER_NAME`` and are currently
    active (``DISPLAY_DEVICE_ACTIVE``), and returns the *slot_index*-th one.

    Returns an empty string when the slot has no active display (driver not
    running, or that slot not yet plugged in via ``add_display``).
    """
    adapter = _DISPLAY_DEVICE()
    vdd_count = 0
    i = 0
    while _EnumDisplayDevicesA(None, i, byref(adapter), 0):
        i += 1
        if adapter.DeviceString != VDD_ADAPTER_NAME:
            continue
        if not (adapter.StateFlags & _DISPLAY_DEVICE_ACTIVE):
            # Slot exists in the driver but no display is currently plugged in.
            continue
        if vdd_count == slot_index:
            raw = adapter.DeviceName.decode("ascii", errors="replace")
            device = raw.lstrip("\\\\.\\")
            log("find_monitor_by_slot(%d) -> %r (enum index %d)", slot_index, device, i - 1)
            return device
        vdd_count += 1
    log("find_monitor_by_slot(%d): not found (%d active vdd adapters seen)", slot_index, vdd_count)
    return ""


# ---------------------------------------------------------------------------
# Keep-alive thread
# ---------------------------------------------------------------------------

class VddKeepAlive:
    """
    Background thread that pings the VDD adapter every 50 ms so that all
    virtual displays remain connected.  Stop it before closing the handle.

    Usage::

        ka = VddKeepAlive(handle)
        ka.start()
        ...
        ka.stop()
        close_device(handle)
    """

    def __init__(self, handle: HANDLE, interval: float = 0.05):
        self._handle   = handle
        self._interval = interval
        self._stop_evt = threading.Event()
        self._thread   = threading.Thread(
            target=self._run, name="vdd-keepalive", daemon=True,
        )

    def start(self) -> None:
        log("VddKeepAlive.start()")
        self._thread.start()

    def stop(self) -> None:
        log("VddKeepAlive.stop()")
        self._stop_evt.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop_evt.wait(self._interval):
            vdd_update(self._handle)


# ---------------------------------------------------------------------------
# Context manager for a single virtual display lifetime
# ---------------------------------------------------------------------------

class VirtualDisplay:
    """
    Context manager that opens the device, starts the keep-alive ping,
    adds one virtual display, and tears everything down on exit.

    Usage::

        with VirtualDisplay() as vd:
            print(f"Display index {vd.index} is live — monitor should appear in EnumDisplayMonitors")
            # run shadow server here
    """

    def __init__(self):
        self.handle: HANDLE | None = None
        self.index: int = -1
        self._ka: VddKeepAlive | None = None

    def __enter__(self) -> "VirtualDisplay":
        self.handle = open_device()
        self._ka    = VddKeepAlive(self.handle)
        self._ka.start()
        self.index  = add_display(self.handle)
        if self.index < 0:
            self._ka.stop()
            close_device(self.handle)
            raise RuntimeError("add_display() failed — driver returned index -1")
        return self

    def __exit__(self, *_) -> None:
        if self.index >= 0 and self.handle:
            remove_display(self.handle, self.index)
        if self._ka:
            self._ka.stop()
        if self.handle:
            close_device(self.handle)
        self.handle = None
        self.index  = -1


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    import time

    print("Parsec VDD smoke test")
    print("---------------------")

    # Always dump matching devices first so we can see the real hardware ID
    # even if the status check fails.
    dump_devices("parsec")
    print()

    status = query_device_status()
    print(f"Driver status : {status.name}")
    if status != DeviceStatus.OK:
        print("Driver is not ready — aborting.")
        print()
        print("Hint: if dump_devices() showed a different hardware ID above,")
        print(f"  update VDD_HARDWARE_ID (currently {VDD_HARDWARE_ID!r})")
        return 1

    print("Opening device handle …")
    handle = open_device()
    assert handle.value is not None
    print(f"  handle       : {handle.value:#x}")

    version = vdd_version(handle)
    print(f"  driver minor : {version}")

    ka = VddKeepAlive(handle)
    ka.start()

    print("Adding virtual display …")
    idx = add_display(handle)
    print(f"  display index: {idx}")
    if idx < 0:
        print("  FAILED")
        ka.stop()
        close_device(handle)
        return 1

    print("Sleeping 5 s — check Device Manager / Display Settings for the new monitor.")
    time.sleep(5)

    print("Removing virtual display …")
    remove_display(handle, idx)

    ka.stop()
    close_device(handle)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
