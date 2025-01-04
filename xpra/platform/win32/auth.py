#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import (
    byref, addressof,
    FormatError, GetLastError,  # @UnresolvedImport
)
from ctypes.wintypes import HANDLE

from xpra.util.env import envbool
from xpra.platform.win32.common import CloseHandle, LogonUser
from xpra.log import Logger

log = Logger("win32", "auth")

LOG_CREDENTIALS = envbool("XPRA_LOG_CREDENTIALS", False)

MAX_COMPUTERNAME_LENGTH = 15
LOGON32_LOGON_NETWORK_CLEARTEXT = 8
LOGON32_PROVIDER_DEFAULT = 0


def check(domain="", username: str = "", password: str = "") -> bool:
    token = HANDLE()
    # domain = os.environ.get('COMPUTERNAME')
    if LOG_CREDENTIALS:
        log("LogonUser(%s, %s, %s, CLEARTEXT, DEFAULT, %#x)",
            username, domain, password, addressof(token))
    status = LogonUser(username, domain, password,
                       LOGON32_LOGON_NETWORK_CLEARTEXT,
                       LOGON32_PROVIDER_DEFAULT,
                       byref(token))
    log("LogonUser(..)=%#x", status)
    if status:
        CloseHandle(token)
        return True
    log.error("Error: win32 authentication failed:")
    log.error(" %s", FormatError(GetLastError()))
    return False
