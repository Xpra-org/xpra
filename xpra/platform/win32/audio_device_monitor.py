# This file is part of Xpra.
# Copyright (C) 2026 Netflix, Inc.
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# ABOUTME: Pure ctypes IMMNotificationClient for audio device change detection.
# ABOUTME: Avoids comtypes COMObject which crashes in frozen builds (GIL + COM thread issue).
#
# COM interface references (Microsoft Learn):
#   IMMNotificationClient: https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nn-mmdeviceapi-immnotificationclient
#   IMMDeviceEnumerator:   https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nn-mmdeviceapi-immdeviceenumerator
#   IUnknown:              https://learn.microsoft.com/en-us/windows/win32/api/unknwn/nn-unknwn-iunknown
#   GUID struct:           https://learn.microsoft.com/en-us/windows/win32/api/guiddef/ns-guiddef-guid
#   EDataFlow enum:        https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/ne-mmdeviceapi-edataflow
#   ERole enum:            https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/ne-mmdeviceapi-erole

import ctypes
from ctypes import Structure, POINTER, byref, c_void_p, c_long, WINFUNCTYPE, HRESULT
from ctypes.wintypes import DWORD, LPCWSTR

from xpra.common import noop
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("audio")

GLib = gi_import("GLib")

# COM constants (from WinError.h and objbase.h)
S_OK = 0
E_NOINTERFACE = 0x80004002
CLSCTX_ALL = 0x17
COINIT_MULTITHREADED = 0x0


class GUID(Structure):
    """Win32 GUID structure (guiddef.h)."""
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __eq__(self, other):
        return (self.Data1 == other.Data1 and self.Data2 == other.Data2 and
                self.Data3 == other.Data3 and
                bytes(self.Data4) == bytes(other.Data4))


# GUIDs from mmdeviceapi.h — verified against Windows SDK 10.0.22621.0:
IID_IUnknown = GUID(0x00000000, 0x0000, 0x0000,
                     (ctypes.c_ubyte * 8)(0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
# {7991EEC9-7E89-4D85-8390-6C703CEC60C0}
IID_IMMNotificationClient = GUID(0x7991EEC9, 0x7E89, 0x4D85,
                                  (ctypes.c_ubyte * 8)(0x83, 0x90, 0x6C, 0x70, 0x3C, 0xEC, 0x60, 0xC0))
# {A95664D2-9614-4F35-A746-DE8DB63617E6}
IID_IMMDeviceEnumerator = GUID(0xA95664D2, 0x9614, 0x4F35,
                                (ctypes.c_ubyte * 8)(0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6))
# {BCDE0395-E52F-467C-8E3D-C4579291692E}
CLSID_MMDeviceEnumerator = GUID(0xBCDE0395, 0xE52F, 0x467C,
                                 (ctypes.c_ubyte * 8)(0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E))

# IMMNotificationClient vtable function signatures.
# Each COM method's first parameter is the `this` pointer.
# Signatures match the C declarations in mmdeviceapi.h.
_QI = WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))       # IUnknown::QueryInterface
_ADDREF = WINFUNCTYPE(ctypes.c_ulong, c_void_p)                              # IUnknown::AddRef
_RELEASE = WINFUNCTYPE(ctypes.c_ulong, c_void_p)                             # IUnknown::Release
_ON_STATE = WINFUNCTYPE(HRESULT, c_void_p, LPCWSTR, DWORD)                   # OnDeviceStateChanged(deviceId, newState)
_ON_ADDED = WINFUNCTYPE(HRESULT, c_void_p, LPCWSTR)                          # OnDeviceAdded(deviceId)
_ON_REMOVED = WINFUNCTYPE(HRESULT, c_void_p, LPCWSTR)                        # OnDeviceRemoved(deviceId)
_ON_DEFAULT = WINFUNCTYPE(HRESULT, c_void_p, ctypes.c_uint, ctypes.c_uint, LPCWSTR)  # OnDefaultDeviceChanged(flow, role, deviceId)
_ON_PROPERTY = WINFUNCTYPE(HRESULT, c_void_p, LPCWSTR, c_void_p)             # OnPropertyValueChanged(deviceId, key)

# IMMDeviceEnumerator method signatures (caller side, for Register/Unregister)
_ENUM_REGISTER = WINFUNCTYPE(HRESULT, c_void_p, c_void_p)    # RegisterEndpointNotificationCallback
_ENUM_UNREGISTER = WINFUNCTYPE(HRESULT, c_void_p, c_void_p)  # UnregisterEndpointNotificationCallback


class _Vtbl(Structure):
    """IMMNotificationClient vtable layout.

    Inherits IUnknown (QueryInterface, AddRef, Release) then adds the
    5 notification methods in the order declared in mmdeviceapi.h.
    """
    _fields_ = [
        ("QueryInterface", _QI),
        ("AddRef", _ADDREF),
        ("Release", _RELEASE),
        ("OnDeviceStateChanged", _ON_STATE),
        ("OnDeviceAdded", _ON_ADDED),
        ("OnDeviceRemoved", _ON_REMOVED),
        ("OnDefaultDeviceChanged", _ON_DEFAULT),
        ("OnPropertyValueChanged", _ON_PROPERTY),
    ]


class _Client(Structure):
    """COM object layout: vtable pointer followed by instance data.

    All COM objects begin with a pointer to their vtable (lpVtbl).
    We add ref_count as instance data for our IUnknown implementation.
    """
    _fields_ = [
        ("lpVtbl", POINTER(_Vtbl)),
        ("ref_count", c_long),
    ]


# module state
_event = None           # Windows Event HANDLE
_poll_timer = 0
_on_change = noop       # callback
_enumerator = None      # IMMDeviceEnumerator raw pointer
_client = None          # _Client instance (prevent GC)
_vtbl = None            # _Vtbl instance (prevent GC)
_registered = False
_com_initialized = False

# prevent GC of the WINFUNCTYPE closures:
_prevent_gc = []

POLL_INTERVAL_MS = 100


def _make_callbacks():
    """Create the COM vtable callback functions."""

    @_QI
    def qi(this, riid, ppv):
        if riid[0] == IID_IUnknown or riid[0] == IID_IMMNotificationClient:
            ppv[0] = this
            impl = ctypes.cast(this, POINTER(_Client))
            impl[0].ref_count += 1
            return S_OK
        ppv[0] = None
        return E_NOINTERFACE

    @_ADDREF
    def addref(this):
        impl = ctypes.cast(this, POINTER(_Client))
        impl[0].ref_count += 1
        return impl[0].ref_count

    @_RELEASE
    def release(this):
        impl = ctypes.cast(this, POINTER(_Client))
        impl[0].ref_count -= 1
        return impl[0].ref_count

    @_ON_DEFAULT
    def on_default(this, flow, role, device_id):
        # Xpra uses the default DirectSound/WASAPI output, not the voice endpoint.
        # wasapisink's default role is console; ignore unrelated role changes.
        if flow == 0 and role == 0 and _event:
            ctypes.windll.kernel32.SetEvent(_event)
        return S_OK

    @_ON_STATE
    def on_state(this, device_id, new_state):
        return S_OK

    @_ON_ADDED
    def on_added(this, device_id):
        return S_OK

    @_ON_REMOVED
    def on_removed(this, device_id):
        return S_OK

    @_ON_PROPERTY
    def on_property(this, device_id, key):
        return S_OK

    return qi, addref, release, on_state, on_added, on_removed, on_default, on_property


def _check_event() -> bool:
    """GLib timer callback: check if the device change event was signaled."""
    if not _event:
        return False
    # non-blocking check:
    WAIT_OBJECT_0 = 0
    result = ctypes.windll.kernel32.WaitForSingleObject(_event, 0)
    if result == WAIT_OBJECT_0:
        log("audio device change detected")
        _on_change()
    return True     # keep polling


def start(on_change) -> None:
    """Register IMMNotificationClient and start polling the event."""
    global _event, _poll_timer, _on_change, _enumerator, _client, _vtbl, _registered, _com_initialized

    if _poll_timer:
        _on_change = on_change
        return
    if _registered:
        # A previous unregister failed. Keep its COM callback alive and reuse it.
        _on_change = on_change
        _poll_timer = GLib.timeout_add(POLL_INTERVAL_MS, _check_event)
        return
    ole32 = ctypes.windll.ole32
    ole32.CoCreateInstance.argtypes = (POINTER(GUID), c_void_p, DWORD, POINTER(GUID), POINTER(c_void_p))
    ole32.CoCreateInstance.restype = HRESULT
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateEventW.argtypes = (c_void_p, ctypes.c_int, ctypes.c_int, LPCWSTR)
    kernel32.CreateEventW.restype = c_void_p
    kernel32.WaitForSingleObject.argtypes = (c_void_p, DWORD)
    kernel32.SetEvent.argtypes = (c_void_p,)
    kernel32.CloseHandle.argtypes = (c_void_p,)
    # CoCreateInstance works in the existing GUI thread apartment.
    hr = ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    if hr not in (S_OK, 1, -2147417850):  # S_FALSE, RPC_E_CHANGED_MODE
        raise OSError("CoInitializeEx failed: 0x%08x" % (hr & 0xFFFFFFFF))
    _com_initialized = hr in (S_OK, 1)

    # create the notification client with pure ctypes vtable:
    callbacks = _make_callbacks()
    _prevent_gc.extend(callbacks)
    qi, addref, release, on_state, on_added, on_removed, on_default, on_property = callbacks

    _vtbl = _Vtbl(qi, addref, release, on_state, on_added, on_removed, on_default, on_property)
    _client = _Client(ctypes.pointer(_vtbl), 1)

    # create IMMDeviceEnumerator:
    _enumerator = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
        byref(IID_IMMDeviceEnumerator), byref(_enumerator),
    )
    if hr != 0:
        stop()
        raise OSError("CoCreateInstance(MMDeviceEnumerator) failed: 0x%08x" % (hr & 0xFFFFFFFF))

    # The callback must have somewhere to record a change as soon as registration succeeds.
    # Auto-reset keeps notifications raised while a previous change is being handled.
    _event = kernel32.CreateEventW(None, False, False, None)
    if not _event:
        stop()
        raise OSError("CreateEventW failed")
    _on_change = on_change

    # register the notification callback via IMMDeviceEnumerator vtable.
    # vtable index 6 = RegisterEndpointNotificationCallback:
    #   0: QueryInterface, 1: AddRef, 2: Release (IUnknown)
    #   3: EnumAudioEndpoints, 4: GetDefaultAudioEndpoint, 5: GetDevice
    #   6: RegisterEndpointNotificationCallback
    #   7: UnregisterEndpointNotificationCallback
    # ref: https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nn-mmdeviceapi-immdeviceenumerator
    vtable = ctypes.cast(_enumerator, POINTER(POINTER(c_void_p * 20)))[0]
    register_fn = _ENUM_REGISTER(vtable[0][6])
    hr = register_fn(_enumerator, byref(_client))
    if hr != 0:
        stop()
        raise OSError("RegisterEndpointNotificationCallback failed: 0x%08x" % (hr & 0xFFFFFFFF))
    _registered = True

    # Changes delivered during registration remain signaled until polling starts.
    _poll_timer = GLib.timeout_add(POLL_INTERVAL_MS, _check_event)
    log("audio device monitor started")


def stop() -> bool:
    """Unregister and clean up."""
    global _event, _poll_timer, _on_change, _enumerator, _client, _vtbl, _registered, _com_initialized

    if _poll_timer:
        GLib.source_remove(_poll_timer)
        _poll_timer = 0
    _on_change = noop

    if _registered:
        try:
            vtable = ctypes.cast(_enumerator, POINTER(POINTER(c_void_p * 20)))[0]
            unregister_fn = _ENUM_UNREGISTER(vtable[0][7])
            hr = unregister_fn(_enumerator, byref(_client))
        except Exception:
            log.warn("Warning: audio device notification unregister failed; retaining callback", exc_info=True)
            return False
        if hr != S_OK:
            log.warn("Warning: audio device notification unregister failed: 0x%08x; retaining callback",
                     hr & 0xFFFFFFFF)
            return False
        _registered = False

    if _enumerator:
        # Release
        vtable = ctypes.cast(_enumerator, POINTER(POINTER(c_void_p * 20)))[0]
        release_fn = _RELEASE(vtable[0][2])
        release_fn(_enumerator)
        _enumerator = None

    if _event:
        ctypes.windll.kernel32.CloseHandle(_event)
        _event = None

    _client = None
    _vtbl = None
    _prevent_gc.clear()
    if _com_initialized:
        ctypes.windll.ole32.CoUninitialize()
        _com_initialized = False
    log("audio device monitor stopped")
    return True
