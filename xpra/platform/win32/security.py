#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import sys
from ctypes import WinDLL, Structure, byref, sizeof, get_last_error, c_uint32  # @UnresolvedImport
from ctypes.wintypes import BOOL, DWORD, HANDLE, LPVOID

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


kernel32 = WinDLL("kernel32", use_last_error=True)

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


def harden_process() -> None:
    """Apply Xpra's process mitigation policies. Failures are not fatal."""
    restrict_dll_directories()
    restrict_image_loads()
    if envbool("XPRA_WIN32_DISABLE_EXTENSION_POINTS", False):
        disable_extension_points()
