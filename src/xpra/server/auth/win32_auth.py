# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
assert init and log #tests will disable logging from here

from ctypes import windll, byref, POINTER, FormatError, GetLastError
from ctypes.wintypes import LPCWSTR, DWORD, HANDLE, BOOL

MAX_COMPUTERNAME_LENGTH = 15
LOGON32_LOGON_NETWORK_CLEARTEXT = 8
LOGON32_PROVIDER_DEFAULT = 0

CloseHandle = windll.Kernel32.CloseHandle
CloseHandle.argtypes = [HANDLE]
CloseHandle.restype = BOOL

LogonUser = windll.Advapi32.LogonUserW
LogonUser.argtypes = [LPCWSTR, LPCWSTR, LPCWSTR, DWORD, DWORD, POINTER(HANDLE)]
LogonUser.restype = BOOL


class Authenticator(SysAuthenticator):

    def get_uid(self):
        return 0

    def get_gid(self):
        return 0

    def get_challenge(self, digests):
        if b"xor" not in digests:
            raise Exception("win32 authenticator requires the 'xor' digest")
        return SysAuthenticator.get_challenge(self, [b"xor"])

    def check(self, password):
        token = HANDLE()
        domain = '' #os.environ.get('COMPUTERNAME')
        status = LogonUser(self.username, domain, password,
                     LOGON32_LOGON_NETWORK_CLEARTEXT,
                     LOGON32_PROVIDER_DEFAULT,
                     byref(token))
        error = GetLastError()
        if status:
            CloseHandle(token)
            return True
        log.error("Error: win32 authentication failed:")
        log.error(" %s", FormatError(error))
        return True

    def __repr__(self):
        return "win32"
