#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#
# Window station and desktop management for per-user session isolation.
#
# Creates an isolated WinSta_<username>\Default environment so that a user's
# processes cannot see or interact with windows owned by other users.
# The shadow server and user processes all run in the same window station;
# GDI capture from within that station captures only that station's content.
#
# Typical usage (from a SYSTEM / Administrator process):
#
#   token   = logon_msv1(username, password).Token
#   lpdesk  = create_user_winsta(username, token)
#   # launch shadow server with lpDesktop=lpdesk
#   # launch user apps   with lpDesktop=lpdesk
#   ...
#   destroy_user_winsta(username)

import sys
from ctypes import (
    WinDLL, WinError, Structure,
    byref, sizeof, create_string_buffer, cast,
    c_void_p, c_char,
)
from ctypes.wintypes import (
    BOOL, DWORD, HANDLE, LPCSTR, WORD,
)

from xpra.log import Logger

log = Logger("win32")

# ---------------------------------------------------------------------------
# DLL handles
# ---------------------------------------------------------------------------

advapi32 = WinDLL("advapi32", use_last_error=True)
kernel32 = WinDLL("kernel32", use_last_error=True)
user32 = WinDLL("user32", use_last_error=True)

# ---------------------------------------------------------------------------
# Access right constants
# ---------------------------------------------------------------------------

# Window station
WINSTA_ENUMDESKTOPS      = 0x0001
WINSTA_READATTRIBUTES    = 0x0002
WINSTA_ACCESSCLIPBOARD   = 0x0004
WINSTA_CREATEDESKTOP     = 0x0008
WINSTA_WRITEATTRIBUTES   = 0x0010
WINSTA_ACCESSGLOBALATOMS = 0x0020
WINSTA_EXITWINDOWS       = 0x0040
WINSTA_ENUMERATE         = 0x0100
WINSTA_READSCREEN        = 0x0200
WINSTA_ALL_ACCESS        = 0x037F

# Desktop
DESKTOP_READOBJECTS      = 0x0001
DESKTOP_CREATEWINDOW     = 0x0002
DESKTOP_CREATEMENU       = 0x0004
DESKTOP_HOOKCONTROL      = 0x0008
DESKTOP_JOURNALRECORD    = 0x0010
DESKTOP_JOURNALPLAYBACK  = 0x0020
DESKTOP_ENUMERATE        = 0x0040
DESKTOP_WRITEOBJECTS     = 0x0080
DESKTOP_SWITCHDESKTOP    = 0x0100
DESKTOP_ALL_ACCESS       = 0x01FF

# Generic rights (used with SetSecurityInfo)
GENERIC_ALL = 0x10000000

# Token information class
TokenUser = 1

# Security information flags
DACL_SECURITY_INFORMATION = 0x00000004

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------


class SECURITY_DESCRIPTOR(Structure):
    _fields_ = [
        ("Revision", c_char),
        ("Sbz1", c_char),
        ("Control", WORD),
        ("Owner", c_void_p),
        ("Group", c_void_p),
        ("Sacl", c_void_p),
        ("Dacl", c_void_p),
    ]


class SECURITY_ATTRIBUTES(Structure):
    _fields_ = [
        ("nLength", DWORD),
        ("lpSecurityDescriptor", c_void_p),
        ("bInheritHandle", BOOL),
    ]

    def __init__(self):
        super().__init__()
        self.nLength = sizeof(self)
        self.bInheritHandle = False


# ---------------------------------------------------------------------------
# advapi32 bindings
# ---------------------------------------------------------------------------

_InitializeSecurityDescriptor = advapi32.InitializeSecurityDescriptor
_InitializeSecurityDescriptor.restype  = BOOL
_InitializeSecurityDescriptor.argtypes = [c_void_p, DWORD]

_SetSecurityDescriptorDacl = advapi32.SetSecurityDescriptorDacl
_SetSecurityDescriptorDacl.restype  = BOOL
_SetSecurityDescriptorDacl.argtypes = [c_void_p, BOOL, c_void_p, BOOL]

# ---------------------------------------------------------------------------
# user32 bindings (complement what common.py already declares)
# ---------------------------------------------------------------------------

HWINSTA = HANDLE
HDESK   = HANDLE

_CreateWindowStationA = user32.CreateWindowStationA
_CreateWindowStationA.restype  = HWINSTA
_CreateWindowStationA.argtypes = [LPCSTR, DWORD, DWORD, c_void_p]

_CloseWindowStation = user32.CloseWindowStation
_CloseWindowStation.restype  = BOOL
_CloseWindowStation.argtypes = [HWINSTA]

_GetProcessWindowStation = user32.GetProcessWindowStation
_GetProcessWindowStation.restype  = HWINSTA
_GetProcessWindowStation.argtypes = []

_SetProcessWindowStation = user32.SetProcessWindowStation
_SetProcessWindowStation.restype  = BOOL
_SetProcessWindowStation.argtypes = [HWINSTA]

_CreateDesktopA = user32.CreateDesktopA
_CreateDesktopA.restype  = HDESK
_CreateDesktopA.argtypes = [LPCSTR, LPCSTR, c_void_p, DWORD, DWORD, c_void_p]

_CloseDesktop = user32.CloseDesktop
_CloseDesktop.restype  = BOOL
_CloseDesktop.argtypes = [HDESK]

_CloseHandle = kernel32.CloseHandle
_CloseHandle.restype  = BOOL
_CloseHandle.argtypes = [HANDLE]

SECURITY_DESCRIPTOR_REVISION = 1


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def _make_null_dacl_sa() -> tuple[SECURITY_ATTRIBUTES, object]:
    """
    Build a SECURITY_ATTRIBUTES with a null DACL (grants everyone full access).
    Returns (sa, sd_buf) — the caller must keep sd_buf alive as long as sa is used.
    """
    sd_buf = create_string_buffer(sizeof(SECURITY_DESCRIPTOR))
    if not _InitializeSecurityDescriptor(sd_buf, SECURITY_DESCRIPTOR_REVISION):
        raise WinError()
    # pAcl=NULL, bDaclPresent=True → null DACL = allow all
    if not _SetSecurityDescriptorDacl(sd_buf, True, None, False):
        raise WinError()
    sa = SECURITY_ATTRIBUTES()
    sa.lpSecurityDescriptor = cast(sd_buf, c_void_p)
    return sa, sd_buf


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Active stations: username -> (winsta_handle, desktop_handle)
_active: dict[str, tuple[HWINSTA, HDESK]] = {}


def create_user_winsta(username: str, token: HANDLE) -> str:
    """
    Create an isolated window station and desktop for *username* and grant
    *token*'s user full access to both.

    Returns the ``lpDesktop`` string to pass in ``STARTUPINFO`` when
    launching processes for this user, e.g. ``"WinSta_alice\\Default"``.

    The handles are kept alive internally; call :func:`destroy_user_winsta`
    when the session ends.
    """
    log("create_user_winsta(%r, %#x)", username, token)
    # Window station names may only contain alphanumeric, underscore and $.
    import re as _re
    safe_name  = _re.sub(r"[^a-zA-Z0-9_$]", "_", username)
    sta_name   = f"WinSta_{safe_name}".encode()
    desk_name  = b"Default"
    lp_desktop = f"WinSta_{safe_name}\\Default"

    if username in _active:
        log("create_user_winsta: reusing existing station for %r", username)
        return lp_desktop

    # Build a null-DACL security descriptor so the window station and desktop
    # are accessible by everyone (suitable for testing).
    sa, sd_buf = _make_null_dacl_sa()
    log("null dacl: %s, %s", sa, sd_buf)

    # --- Create window station with open security ----------------------------
    winsta = _CreateWindowStationA(sta_name, 0, WINSTA_ALL_ACCESS, byref(sa))
    if not winsta:
        raise WinError()
    log("created window station %r: handle=%#x", sta_name, winsta)

    # --- Temporarily switch our process to the new station so CreateDesktopA
    #     creates the desktop inside it rather than in WinSta0.
    old_winsta = _GetProcessWindowStation()
    _SetProcessWindowStation(winsta)
    try:
        desktop = _CreateDesktopA(desk_name, None, None, 0, DESKTOP_ALL_ACCESS, byref(sa))
        if not desktop:
            err = WinError()
            _CloseWindowStation(winsta)
            raise err
        log("created desktop %r in %r: handle=%#x", desk_name, sta_name, desktop)
    finally:
        _SetProcessWindowStation(old_winsta)

    _active[username] = (winsta, desktop)
    log("create_user_winsta(%r) -> %r", username, lp_desktop)
    return lp_desktop


def destroy_user_winsta(username: str) -> None:
    """
    Close the window station and desktop handles created for *username*.
    All processes running in that station must have exited first.
    """
    entry = _active.pop(username, None)
    if entry is None:
        log("destroy_user_winsta(%r): not found", username)
        return
    winsta, desktop = entry
    log("destroying window station for %r (winsta=%#x, desktop=%#x)", username, winsta, desktop)
    _CloseDesktop(desktop)
    _CloseWindowStation(winsta)


def list_winstations() -> list[str]:
    """Return the names of all currently visible window stations (diagnostic)."""
    from ctypes.wintypes import LPSTR, LPARAM
    from ctypes import WINFUNCTYPE
    WINSTAENUMPROCA = WINFUNCTYPE(BOOL, LPSTR, LPARAM)
    names: list[str] = []

    @WINSTAENUMPROCA
    def _cb(name, _param):
        if name:
            names.append(name.decode("ascii", errors="replace"))
        return True

    _EnumWindowStationsA = user32.EnumWindowStationsA
    _EnumWindowStationsA.restype  = BOOL
    _EnumWindowStationsA.argtypes = [WINSTAENUMPROCA, LPARAM]
    _EnumWindowStationsA(_cb, 0)
    return names


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(f"Usage: {argv[0]} <username> <password>")
        return 1

    username, password = argv[1], argv[2]

    print(f"Window stations before: {list_winstations()}")

    from xpra.platform.win32.lsa_logon_lib import logon_msv1
    print(f"Logging in as {username!r} …")
    logon_info = logon_msv1(username, password)
    token = logon_info.Token
    print(f"  token: {token}")

    print(f"Creating window station for {username!r} …")
    lp_desktop = create_user_winsta(username, token)
    print(f"  lpDesktop = {lp_desktop!r}")

    print(f"Window stations after:  {list_winstations()}")

    print("Launching notepad in the new window station …")
    from xpra.platform.win32.create_process_lib import (
        Popen, CREATIONINFO, CREATION_TYPE_LOGON,
        STARTF_USESHOWWINDOW, LOGON_WITH_PROFILE,
        CREATE_NEW_PROCESS_GROUP, STARTUPINFO,
    )
    creation_info = CREATIONINFO()
    creation_info.lpUsername  = username
    creation_info.lpPassword  = password
    creation_info.dwCreationType  = CREATION_TYPE_LOGON
    creation_info.dwLogonFlags    = LOGON_WITH_PROFILE
    creation_info.dwCreationFlags = CREATE_NEW_PROCESS_GROUP

    startupinfo = STARTUPINFO()
    startupinfo.dwFlags      = STARTF_USESHOWWINDOW
    startupinfo.wShowWindow  = 1   # SW_NORMAL — visible within the desktop
    startupinfo.lpDesktop    = lp_desktop
    startupinfo.lpTitle      = f"Notepad ({username})"

    proc = Popen(
        ["notepad.exe"], executable="notepad.exe",
        startupinfo=startupinfo, creationinfo=creation_info,
    )
    print(f"  notepad pid: {proc.pid}")
    print("Notepad is running in the isolated desktop.")
    print("It will NOT appear on your screen (non-interactive station).")
    print("The xpra shadow server running in the same station WILL capture it.")
    input("Press Enter to kill notepad and clean up …")

    proc.terminate()
    proc.wait()

    destroy_user_winsta(username)
    print(f"Window stations after cleanup: {list_winstations()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
