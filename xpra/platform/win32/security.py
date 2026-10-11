#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import sys
from ctypes import (  # @UnresolvedImport
    WinDLL, Structure, POINTER, byref, sizeof, cast, get_last_error, create_unicode_buffer,
    create_string_buffer, c_int, c_uint32,
)
from ctypes.wintypes import BOOL, DWORD, HANDLE, LPVOID, LPCWSTR, LPWSTR, LONG

from xpra.log import Logger
from xpra.util.env import envbool

log = Logger("win32")

# `PROCESS_MITIGATION_POLICY` values we use:
ProcessExtensionPointDisablePolicy = 6
ProcessImageLoadPolicy = 10

# `SetDefaultDllDirectories` flags:
# `DEFAULT_DIRS` is the application directory, `System32` and any directory
# added with `AddDllDirectory`. It excludes the current directory and `PATH`.
LOAD_LIBRARY_SEARCH_DEFAULT_DIRS = 0x00001000

TOKEN_QUERY = 0x0008
TOKEN_ADJUST_PRIVILEGES = 0x0020
TokenPrivileges = 3
SE_PRIVILEGE_REMOVED = 0x00000004
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NOT_ALL_ASSIGNED = 1300

# `SeChangeNotifyPrivilege` is "bypass traverse checking":
# without it, every path lookup would need list access on each parent directory.
KEEP_PRIVILEGES: frozenset[str] = frozenset({"SeChangeNotifyPrivilege"})
# only kept by processes that already hold `SeTcbPrivilege`, ie: the proxy server running as `SYSTEM`,
# which needs them to log users on with `LsaLogonUser` and start their processes with `CreateProcessAsUser`:
LOGON_PRIVILEGES: frozenset[str] = frozenset({
    "SeTcbPrivilege",
    "SeAssignPrimaryTokenPrivilege",
    "SeIncreaseQuotaPrivilege",
    "SeImpersonatePrivilege",
})

# There is no job object with UI restrictions:
# any `JOB_OBJECT_UILIMIT_*` flag, even an unrelated one like `JOB_OBJECT_UILIMIT_EXITWINDOWS`,
# makes `GetClipboardData` return `NULL` for data owned by processes outside the job.


# noinspection PyTypeChecker
class PROCESS_MITIGATION_IMAGE_LOAD_POLICY(Structure):
    _fields_ = [
        ("NoRemoteImages", c_uint32, 1),
        ("NoLowMandatoryLabelImages", c_uint32, 1),
        ("PreferSystem32Images", c_uint32, 1),
        ("AuditNoRemoteImages", c_uint32, 1),
        ("AuditNoLowMandatoryLabelImages", c_uint32, 1),
        ("ReservedFlags", c_uint32, 27),
    ]


# noinspection PyTypeChecker
class PROCESS_MITIGATION_EXTENSION_POINT_DISABLE_POLICY(Structure):
    _fields_ = [
        ("DisableExtensionPoints", c_uint32, 1),
        ("ReservedFlags", c_uint32, 31),
    ]


class LUID(Structure):
    _fields_ = [
        ("LowPart", DWORD),
        ("HighPart", LONG),
    ]


class LUID_AND_ATTRIBUTES(Structure):
    _fields_ = [
        ("Luid", LUID),
        ("Attributes", DWORD),
    ]


def token_privileges_struct(count: int):
    class TOKEN_PRIVILEGES(Structure):
        _fields_ = [
            ("PrivilegeCount", DWORD),
            ("Privileges", LUID_AND_ATTRIBUTES * count),
        ]
    return TOKEN_PRIVILEGES


kernel32 = WinDLL("kernel32", use_last_error=True)
advapi32 = WinDLL("advapi32", use_last_error=True)

GetCurrentProcess = kernel32.GetCurrentProcess
GetCurrentProcess.argtypes = []
GetCurrentProcess.restype = HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [HANDLE]
CloseHandle.restype = BOOL

OpenProcessToken = advapi32.OpenProcessToken
OpenProcessToken.argtypes = [HANDLE, DWORD, POINTER(HANDLE)]
OpenProcessToken.restype = BOOL

GetTokenInformation = advapi32.GetTokenInformation
GetTokenInformation.argtypes = [HANDLE, c_int, LPVOID, DWORD, POINTER(DWORD)]
GetTokenInformation.restype = BOOL

AdjustTokenPrivileges = advapi32.AdjustTokenPrivileges
AdjustTokenPrivileges.argtypes = [HANDLE, BOOL, LPVOID, DWORD, LPVOID, LPVOID]
AdjustTokenPrivileges.restype = BOOL

LookupPrivilegeNameW = advapi32.LookupPrivilegeNameW
LookupPrivilegeNameW.argtypes = [LPCWSTR, POINTER(LUID), LPWSTR, POINTER(DWORD)]
LookupPrivilegeNameW.restype = BOOL

SetProcessMitigationPolicy = kernel32.SetProcessMitigationPolicy
SetProcessMitigationPolicy.argtypes = [DWORD, LPVOID, HANDLE]
SetProcessMitigationPolicy.restype = BOOL

SetDefaultDllDirectories = kernel32.SetDefaultDllDirectories
SetDefaultDllDirectories.argtypes = [DWORD]
SetDefaultDllDirectories.restype = BOOL


def _set_policy(name: str, policy: int, structure) -> bool:
    if not SetProcessMitigationPolicy(policy, byref(structure), sizeof(structure)):
        log.warn("Warning: failed to enable the %s process mitigation policy", name)
        log.warn(" error %i", get_last_error())
        return False
    log("%s process mitigation policy enabled", name)
    return True


def restrict_image_loads() -> bool:
    """Refuse to load DLLs from remote paths, and prefer the ones in `System32`."""
    policy = PROCESS_MITIGATION_IMAGE_LOAD_POLICY()
    policy.NoRemoteImages = 1
    policy.PreferSystem32Images = 1
    return _set_policy("image load", ProcessImageLoadPolicy, policy)


def disable_extension_points() -> bool:
    """
    Prevent legacy extension point DLLs from being loaded into this process:
    `AppInit_DLLs`, Winsock LSPs, global window hooks and legacy IMEs.

    This also blocks legacy `IMM32` input methods, which is why it is opt-in:
    modern `TSF` input methods are unaffected, but CJK input may still regress.
    """
    policy = PROCESS_MITIGATION_EXTENSION_POINT_DISABLE_POLICY()
    policy.DisableExtensionPoints = 1
    return _set_policy("extension point disable", ProcessExtensionPointDisablePolicy, policy)


def restrict_dll_directories() -> bool:
    """
    Remove the current directory and `PATH` from the DLL search order.

    Only applied to frozen builds, which ship every DLL they need beside the
    executable. Source checkouts are left alone: they can rely on `PATH` to
    locate the `MSYS2` libraries, depending on which interpreter started them.
    """
    if not getattr(sys, "frozen", False):
        log("not a frozen build, leaving the DLL search order alone")
        return False
    if not SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS):
        log.warn("Warning: failed to restrict the DLL search order")
        log.warn(" error %i", get_last_error())
        return False
    log("DLL search order restricted to the default directories")
    return True


def get_privilege_name(luid: LUID) -> str:
    size = DWORD(64)
    buf = create_unicode_buffer(size.value)
    if not LookupPrivilegeNameW(None, byref(luid), buf, byref(size)):
        return ""
    return buf.value


def get_token_privileges(token: HANDLE):
    size = DWORD(0)
    GetTokenInformation(token, TokenPrivileges, None, 0, byref(size))
    if not size.value:
        raise OSError(get_last_error(), "GetTokenInformation(TokenPrivileges) failed")
    buf = create_string_buffer(size.value)
    if not GetTokenInformation(token, TokenPrivileges, buf, size, byref(size)):
        raise OSError(get_last_error(), "GetTokenInformation(TokenPrivileges) failed")
    count = cast(buf, POINTER(DWORD)).contents.value
    return cast(buf, POINTER(token_privileges_struct(count))).contents


def remove_privileges(keep: frozenset[str] = KEEP_PRIVILEGES) -> list[str]:
    """
    Permanently remove every privilege not in `keep` from the process token.

    Removed privileges cannot be added back, not even by this process.
    Returns the names of the privileges removed.
    """
    token = HANDLE()
    if not OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_ADJUST_PRIVILEGES, byref(token)):
        log.warn("Warning: failed to open the process token")
        log.warn(" error %i", get_last_error())
        return []
    try:
        try:
            privileges = get_token_privileges(token)
        except OSError as e:
            log.warn("Warning: failed to query the process privileges")
            log.warn(" %s", e)
            return []
        names = [get_privilege_name(p.Luid) for p in privileges.Privileges]
        if "SeTcbPrivilege" in names:
            keep = keep | LOGON_PRIVILEGES
        indexes = [i for i, name in enumerate(names) if name and name not in keep]
        if not indexes:
            log("no privileges to remove, kept %s", names)
            return []
        removed = [names[i] for i in indexes]
        changes = token_privileges_struct(len(indexes))()
        changes.PrivilegeCount = len(indexes)
        for j, i in enumerate(indexes):
            changes.Privileges[j].Luid = privileges.Privileges[i].Luid
            changes.Privileges[j].Attributes = SE_PRIVILEGE_REMOVED
        if not AdjustTokenPrivileges(token, False, byref(changes), 0, None, None) \
                or get_last_error() == ERROR_NOT_ALL_ASSIGNED:
            log.warn("Warning: failed to remove the process privileges")
            log.warn(" error %i", get_last_error())
            return []
        log("removed privileges %s, kept %s", removed, [name for name in names if name not in removed])
        return removed
    finally:
        CloseHandle(token)


def harden_process() -> None:
    """Apply Xpra's process mitigation policies. Failures are not fatal."""
    restrict_dll_directories()
    restrict_image_loads()
    remove_privileges()
    if envbool("XPRA_WIN32_DISABLE_EXTENSION_POINTS", False):
        disable_extension_points()
