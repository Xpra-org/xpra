# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from ctypes import byref, sizeof
from ctypes.wintypes import ULARGE_INTEGER

from xpra.platform.win32.common import (
    MEMORYSTATUSEX,
    GetPhysicallyInstalledSystemMemory,
    GlobalMemoryStatusEx,
)


def get_total_physical_memory() -> int:
    # don't use `wmi` here: it requires COM to be initialized on the calling thread,
    # and this can be called from any thread (ie: the server's info thread)
    try:
        # this is the amount of RAM installed, as reported by the SMBIOS,
        # but it fails with ERROR_INVALID_DATA if the SMBIOS data is malformed (ie: in some VMs):
        total_kb = ULARGE_INTEGER(0)
        if GetPhysicallyInstalledSystemMemory(byref(total_kb)) and total_kb.value:
            return int(total_kb.value) * 1024
        # fallback: the memory usable by the OS, slightly lower than the amount installed
        memstatus = MEMORYSTATUSEX()
        memstatus.dwLength = sizeof(MEMORYSTATUSEX)
        if GlobalMemoryStatusEx(byref(memstatus)):
            return int(memstatus.ullTotalPhys)
    except OSError:
        pass
    return 0


def get_sys_info():
    return {
        "total-physical-memory": get_total_physical_memory(),
    }

def get_name():
    try:
        from ctypes import (
            WinError, get_last_error,  # @UnresolvedImport
            byref, create_string_buffer,
            )
        from ctypes.wintypes import DWORD
        from xpra.platform.win32.common import GetUserNameA
        max_len = 256
        size = DWORD(max_len)
        buf = create_string_buffer(max_len + 1)
        if not GetUserNameA(byref(buf), byref(size)):
            raise WinError(get_last_error())
        return buf.value[:size.value].decode()
    except Exception:
        return os.environ.get("USERNAME", "")

def get_version_info():
    return {}
