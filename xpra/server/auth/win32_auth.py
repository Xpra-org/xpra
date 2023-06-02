#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Tuple
from ctypes import (
    byref, addressof, POINTER,
    windll, FormatError, GetLastError,  # @UnresolvedImport
    )
from ctypes.wintypes import LPCWSTR, DWORD, HANDLE, BOOL

from xpra.server.auth.sys_auth_base import SysAuthenticator, log
from xpra.util import envbool
from xpra.platform.win32.common import CloseHandle

LOG_CREDENTIALS = envbool("XPRA_LOG_CREDENTIALS", False)

MAX_COMPUTERNAME_LENGTH = 15
LOGON32_LOGON_NETWORK_CLEARTEXT = 8
LOGON32_PROVIDER_DEFAULT = 0

LogonUser = windll.Advapi32.LogonUserW
LogonUser.argtypes = [LPCWSTR, LPCWSTR, LPCWSTR, DWORD, DWORD, POINTER(HANDLE)]
LogonUser.restype = BOOL


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        #fugly: keep hold of the password so the win32 proxy can use it
        self.password = ""

    def get_uid(self) -> int:
        return 0

    def get_gid(self) -> int:
        return 0

    def get_password(self) -> str:
        return self.password

    def get_challenge(self, digests) -> Tuple[bytes,str]:
        self.req_xor(digests)
        return super().get_challenge(["xor"])

    def check(self, password:str) -> bool:
        token = HANDLE()
        domain = '' #os.environ.get('COMPUTERNAME')
        if LOG_CREDENTIALS:
            log("LogonUser(%s, %s, %s, CLEARTEXT, DEFAULT, %#x)",
                self.username, domain, password, addressof(token))
        status = LogonUser(self.username, domain, password,
                     LOGON32_LOGON_NETWORK_CLEARTEXT,
                     LOGON32_PROVIDER_DEFAULT,
                     byref(token))
        log("LogonUser(..)=%#x", status)
        if status:
            CloseHandle(token)
            self.password = password
            return True
        log.error("Error: win32 authentication failed:")
        log.error(" %s", FormatError(GetLastError()))
        return False

    def __repr__(self):
        return "win32"


def main(argv) -> int:
    #pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Auth-Test", "Auth-Test"):
        enable_color()
        for x in ("-v", "--verbose"):
            if x in tuple(argv):
                log.enable_debug()
                argv.remove(x)
        if len(argv)!=3:
            log.warn("invalid number of arguments")
            log.warn("usage: %s [--verbose] username password", argv[0])
            return 1
        username = argv[1]
        password = argv[2]
        a = Authenticator(username=username)
        if a.check(password):
            log.info("authentication succeeded")
            return 0
        log.error("authentication failed")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
