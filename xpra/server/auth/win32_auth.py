# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import windll, byref, addressof, POINTER, FormatError, GetLastError
from ctypes.wintypes import LPCWSTR, DWORD, HANDLE, BOOL

from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
from xpra.util import envbool
from xpra.os_util import bytestostr
from xpra.platform.win32.common import CloseHandle
assert init and log #tests will disable logging from here

LOG_CREDENTIALS = envbool("XPRA_LOG_CREDENTIALS", False)

MAX_COMPUTERNAME_LENGTH = 15
LOGON32_LOGON_NETWORK_CLEARTEXT = 8
LOGON32_PROVIDER_DEFAULT = 0

LogonUser = windll.Advapi32.LogonUserW
LogonUser.argtypes = [LPCWSTR, LPCWSTR, LPCWSTR, DWORD, DWORD, POINTER(HANDLE)]
LogonUser.restype = BOOL


class Authenticator(SysAuthenticator):

    def get_uid(self):
        return 0

    def get_gid(self):
        return 0

    def get_challenge(self, digests):
        if "xor" not in digests:
            raise Exception("win32 authenticator requires the 'xor' digest")
        return SysAuthenticator.get_challenge(self, ["xor"])

    def check(self, password):
        token = HANDLE()
        domain = '' #os.environ.get('COMPUTERNAME')
        password_str = bytestostr(password)
        if LOG_CREDENTIALS:
            log("LogonUser(%s, %s, %s, CLEARTEXT, DEFAULT, %#x)",
                self.username, domain, password_str, addressof(token))
        status = LogonUser(self.username, domain, password_str,
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

    def __repr__(self):
        return "win32"


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("Auth-Test", "Auth-Test"):
        enable_color()
        for x in ("-v", "--verbose"):
            if x in tuple(sys.argv):
                log.enable_debug()
                sys.argv.remove(x)
        if len(sys.argv)!=3:
            log.warn("invalid number of arguments")
            log.warn("usage: %s [--verbose] username password", sys.argv[0])
            return 1
        username = sys.argv[1]
        password = sys.argv[2]
        a = Authenticator(username)
        if a.check(password):
            log.info("authentication succeeded")
            return 0
        log.error("authentication failed")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
