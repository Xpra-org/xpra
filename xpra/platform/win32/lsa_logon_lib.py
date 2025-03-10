#!/usr/bin/env python3
# This file is part of Xpra.
# This code is released under the terms of the MIT license:
# https://opensource.org/licenses/MIT
# This LSA code was found here:
# https://stackoverflow.com/questions/43114209/

import os
import sys
from ctypes import (
    Structure, POINTER,
    get_last_error, WinError, WinDLL,
    create_unicode_buffer, create_string_buffer, resize, addressof, byref, sizeof, memmove, cast,
    c_char, c_wchar, c_ulonglong, c_size_t, c_void_p,
)
from ctypes.wintypes import ULONG, LONG, BOOL, LARGE_INTEGER, USHORT, DWORD, LPVOID, LPWSTR, HANDLE
from collections import namedtuple

from xpra.log import Logger

log = Logger("win32")

ntdll = WinDLL('ntdll')
secur32 = WinDLL('secur32')
kernel32 = WinDLL('kernel32', use_last_error=True)
advapi32 = WinDLL('advapi32', use_last_error=True)

CHAR = c_char
WCHAR = c_wchar
PCHAR = POINTER(CHAR)
PWCHAR = POINTER(WCHAR)
SIZE_T = c_size_t
PULONG = POINTER(ULONG)
LSA_OPERATIONAL_MODE = ULONG
PLSA_OPERATIONAL_MODE = PULONG
PHANDLE = POINTER(HANDLE)
PLPVOID = POINTER(LPVOID)
LPDWORD = POINTER(DWORD)

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [HANDLE]

MAX_COMPUTER_NAME_LENGTH = 15

SECURITY_LOGON_TYPE = ULONG
Interactive = 2
Network = 3
Batch = 4
Service = 5

LOGON_SUBMIT_TYPE = ULONG
PROFILE_BUFFER_TYPE = ULONG

MsV1_0InteractiveLogon = 2
MsV1_0Lm20Logon = 3
MsV1_0NetworkLogon = 4
MsV1_0WorkstationUnlockLogon = 7
MsV1_0S4ULogon = 12
MsV1_0NoElevationLogon = 82

KerbInteractiveLogon = 2
KerbWorkstationUnlockLogon = 7
KerbS4ULogon = 12

MSV1_0_S4U_LOGON_FLAG_CHECK_LOGONHOURS = 0x2

KERB_S4U_LOGON_FLAG_CHECK_LOGONHOURS = 0x2
KERB_S4U_LOGON_FLAG_IDENTITY = 0x8

TOKEN_SOURCE_LENGTH = 8

NEGOTIATE_PACKAGE_NAME = b'Negotiate'
MICROSOFT_KERBEROS_NAME = b'Kerberos'
MSV1_0_PACKAGE_NAME = b'MICROSOFT_AUTHENTICATION_PACKAGE_V1_0'

DELETE = 0x00010000
READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
WRITE_OWNER = 0x00080000

STANDARD_RIGHTS_REQUIRED = DELETE | READ_CONTROL | WRITE_DAC | WRITE_OWNER

TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_IMPERSONATE = 0x0004
TOKEN_QUERY = 0x0008
TOKEN_QUERY_SOURCE = 0x0010
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_ADJUST_GROUPS = 0x0040
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_ADJUST_SESSIONID = 0x0100

TOKEN_ALL_ACCESS = (
    STANDARD_RIGHTS_REQUIRED | TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_IMPERSONATE |
    TOKEN_QUERY | TOKEN_QUERY_SOURCE | TOKEN_ADJUST_PRIVILEGES | TOKEN_ADJUST_GROUPS |
    TOKEN_ADJUST_DEFAULT | TOKEN_ADJUST_SESSIONID
)

DUPLICATE_CLOSE_SOURCE = 0x00000001
DUPLICATE_SAME_ACCESS = 0x00000002

TOKEN_TYPE = ULONG
TokenPrimary = 1
TokenImpersonation = 2

SECURITY_IMPERSONATION_LEVEL = ULONG
SecurityAnonymous = 0
SecurityIdentification = 1
SecurityImpersonation = 2
SecurityDelegation = 3


class NTSTATUS(LONG):

    def to_error(self):
        return ntdll.RtlNtStatusToDosError(self)

    def __repr__(self):
        name = self.__class__.__name__
        status = ULONG.from_buffer(self)
        return '{}({:#010x})'.format(name, status.value)


PNTSTATUS = POINTER(NTSTATUS)


class MANAGED_HANDLE(HANDLE):
    __slots__ = 'closed',

    def __int__(self):
        return self.value or 0

    def detach(self):
        if not getattr(self, 'closed', False):
            self.closed = True
            value = int(self)
            self.value = None
            return value
        raise ValueError("already closed")

    def close(self):
        if self and not getattr(self, 'closed', False):
            CloseHandle(self.detach())

    __del__ = close

    def __repr__(self):
        return "%s(%d)" % (self.__class__.__name__, int(self))


class LARGE_INTEGER_TIME(LARGE_INTEGER):
    # https://msdn.microsoft.com/en-us/library/ff553204
    ntdll.RtlSecondsSince1970ToTime.restype = None
    _unix_epoch_LI = LARGE_INTEGER()
    ntdll.RtlSecondsSince1970ToTime(0, byref(_unix_epoch_LI))
    _unix_epoch = _unix_epoch_LI.value

    def __int__(self):
        return self.value

    def __repr__(self):
        name = self.__class__.__name__
        return '%s(%d)' % (name, self.value)

    def as_time(self) -> float:
        time100ns = self.value - self._unix_epoch
        if time100ns >= 0:
            return time100ns / 1e7
        raise ValueError('value predates the Unix epoch')

    @classmethod
    def from_time(cls, t):
        time100ns = int(t * 10 ** 7)
        return cls(time100ns + cls._unix_epoch)


class STRING(Structure):
    _fields_ = (
        ('Length', USHORT),
        ('MaximumLength', USHORT),
        ('Buffer', PCHAR),
    )


PSTRING = POINTER(STRING)


class UNICODE_STRING(Structure):
    _fields_ = (
        ('Length', USHORT),
        ('MaximumLength', USHORT),
        ('Buffer', PWCHAR),
    )


PUNICODE_STRING = POINTER(UNICODE_STRING)


class LUID(Structure):
    _fields_ = (
        ('LowPart', DWORD),
        ('HighPart', LONG),
    )

    def __new__(cls, value=0):
        return cls.from_buffer_copy(c_ulonglong(value))

    def __int__(self):
        return c_ulonglong.from_buffer(self).value

    def __repr__(self):
        name = self.__class__.__name__
        return '%s(%#x)' % (name, int(self))


PLUID = POINTER(LUID)
PSID = LPVOID


class SID_AND_ATTRIBUTES(Structure):
    _fields_ = (
        ('Sid', PSID),
        ('Attributes', DWORD),
    )


PSID_AND_ATTRIBUTES = POINTER(SID_AND_ATTRIBUTES)


class TOKEN_GROUPS(Structure):
    _fields_ = (
        ('GroupCount', DWORD),
        ('Groups', SID_AND_ATTRIBUTES * 1),
    )


PTOKEN_GROUPS = POINTER(TOKEN_GROUPS)


class TOKEN_SOURCE(Structure):
    # noinspection PyTypeChecker
    _fields_ = (
        ('SourceName', CHAR * TOKEN_SOURCE_LENGTH),
        ('SourceIdentifier', LUID),
    )

    def __init__(self, SourceName=None, SourceIdentifier=None):
        super().__init__()
        if SourceName is not None:
            if not isinstance(SourceName, bytes):
                SourceName = SourceName.encode('mbcs')
            self.SourceName = SourceName
        if SourceIdentifier is None:
            luid = self.SourceIdentifier
            ntdll.NtAllocateLocallyUniqueId(byref(luid))
        else:
            self.SourceIdentifier = SourceIdentifier


PTOKEN_SOURCE = POINTER(TOKEN_SOURCE)

py_source_context = TOKEN_SOURCE(b"PYTHON  ")
py_origin_name = b"Python-%d" % os.getpid()
py_logon_process_name = b"PythonLogonProcess-%d" % os.getpid()


class QUOTA_LIMITS(Structure):
    _fields_ = (
        ('PagedPoolLimit', SIZE_T),
        ('NonPagedPoolLimit', SIZE_T),
        ('MinimumWorkingSetSize', SIZE_T),
        ('MaximumWorkingSetSize', SIZE_T),
        ('PagefileLimit', SIZE_T),
        ('TimeLimit', LARGE_INTEGER_TIME),
    )


PQUOTA_LIMITS = POINTER(QUOTA_LIMITS)


class ContiguousUnicode(Structure):
    # _string_names_: sequence matched to underscore-prefixed fields

    def _get_unicode_string(self, name):
        wchar_size = sizeof(WCHAR)
        s = getattr(self, '_%s' % name)
        length = s.Length // wchar_size
        buf = s.Buffer
        if buf:
            return buf[:length]
        return None

    def _set_unicode_buffer(self, value):
        cls = type(self)
        wchar_size = sizeof(WCHAR)
        bufsize = (len(value) + 1) * wchar_size
        resize(self, sizeof(cls) + bufsize)
        addr = addressof(self) + sizeof(cls)
        src_buf = create_unicode_buffer(value)
        memmove(addr, addressof(src_buf), bufsize)  # NOSONAR

    def _set_unicode_string(self, name, value):
        values = []
        for n in self._string_names_:
            if n == name:
                values.append(value or '')
            else:
                values.append(getattr(self, n) or '')
        self._set_unicode_buffer('\x00'.join(values))

        cls = type(self)
        wchar_size = sizeof(WCHAR)
        addr = addressof(self) + sizeof(cls)
        for n, v in zip(self._string_names_, values):
            ptr = cast(addr, PWCHAR)
            ustr = getattr(self, '_%s' % n)
            length = ustr.Length = len(v) * wchar_size
            full_length = length + wchar_size
            if (n == name and value is None) or (n != name and not (length or ustr.Buffer)):
                ustr.Buffer = None
                ustr.MaximumLength = 0
            else:
                ustr.Buffer = ptr
                ustr.MaximumLength = full_length
            addr += full_length

    def __getattr__(self, name):
        if name not in self._string_names_:
            raise AttributeError
        return self._get_unicode_string(name)

    def __setattr__(self, name, value):
        if name in self._string_names_:
            self._set_unicode_string(name, value)
        else:
            super().__setattr__(name, value)

    @classmethod
    def from_address_copy(cls, address, size=None):
        x = Structure.__new__(cls)
        if size is not None:
            resize(x, size)
        memmove(byref(x), address, sizeof(x))
        delta = addressof(x) - address
        for n in cls._string_names_:
            ustr = getattr(x, '_%s' % n)
            addr = c_void_p.from_buffer(ustr.Buffer)
            if addr:
                addr.value += delta
        return x


class AuthInfo(ContiguousUnicode):
    # _message_type_: from a logon-submit-type enumeration
    def __init__(self):
        super().__init__()
        self.MessageType = self._message_type_


class MSV1_0_INTERACTIVE_LOGON(AuthInfo):
    _message_type_ = MsV1_0InteractiveLogon
    _string_names_ = 'LogonDomainName', 'UserName', 'Password'

    _fields_ = (
        ('MessageType', LOGON_SUBMIT_TYPE),
        ('_LogonDomainName', UNICODE_STRING),
        ('_UserName', UNICODE_STRING),
        ('_Password', UNICODE_STRING),
    )

    def __init__(self, UserName=None, Password=None, LogonDomainName=None):
        super().__init__()
        if LogonDomainName is not None:
            self.LogonDomainName = LogonDomainName
        if UserName is not None:
            self.UserName = UserName
        if Password is not None:
            self.Password = Password


class S4ULogon(AuthInfo):
    _string_names_ = 'UserPrincipalName', 'DomainName'

    _fields_ = (
        ('MessageType', LOGON_SUBMIT_TYPE),
        ('Flags', ULONG),
        ('_UserPrincipalName', UNICODE_STRING),
        ('_DomainName', UNICODE_STRING),
    )

    def __init__(self, UserPrincipalName=None, DomainName=None, Flags=0):
        super().__init__()
        self.Flags = Flags
        if UserPrincipalName is not None:
            self.UserPrincipalName = UserPrincipalName
        if DomainName is not None:
            self.DomainName = DomainName


class MSV1_0_S4U_LOGON(S4ULogon):
    _message_type_ = MsV1_0S4ULogon


class KERB_S4U_LOGON(S4ULogon):
    _message_type_ = KerbS4ULogon


PMSV1_0_S4U_LOGON = POINTER(MSV1_0_S4U_LOGON)
PKERB_S4U_LOGON = POINTER(KERB_S4U_LOGON)


class ProfileBuffer(ContiguousUnicode):
    # _message_type_
    def __init__(self):
        super().__init__()
        self.MessageType = self._message_type_


class MSV1_0_INTERACTIVE_PROFILE(ProfileBuffer):
    _message_type_ = MsV1_0InteractiveLogon
    _string_names_ = ('LogonScript', 'HomeDirectory', 'FullName',
                      'ProfilePath', 'HomeDirectoryDrive', 'LogonServer')
    _fields_ = (
        ('MessageType', PROFILE_BUFFER_TYPE),
        ('LogonCount', USHORT),
        ('BadPasswordCount', USHORT),
        ('LogonTime', LARGE_INTEGER_TIME),
        ('LogoffTime', LARGE_INTEGER_TIME),
        ('KickOffTime', LARGE_INTEGER_TIME),
        ('PasswordLastSet', LARGE_INTEGER_TIME),
        ('PasswordCanChange', LARGE_INTEGER_TIME),
        ('PasswordMustChange', LARGE_INTEGER_TIME),
        ('_LogonScript', UNICODE_STRING),
        ('_HomeDirectory', UNICODE_STRING),
        ('_FullName', UNICODE_STRING),
        ('_ProfilePath', UNICODE_STRING),
        ('_HomeDirectoryDrive', UNICODE_STRING),
        ('_LogonServer', UNICODE_STRING),
        ('UserFlags', ULONG),
    )

    def __repr__(self):
        return f"<MSV1_0_INTERACTIVE_PROFILE>({self.FullName!r})"


class SECURITY_ATTRIBUTES(Structure):
    _fields_ = (
        ('nLength', DWORD),
        ('lpSecurityDescriptor', LPVOID),
        ('bInheritHandle', BOOL),
    )

    def __init__(self, **kwds):
        self.nLength = sizeof(self)
        super().__init__(**kwds)


LPSECURITY_ATTRIBUTES = POINTER(SECURITY_ATTRIBUTES)


def _check_status(result, func, args):
    if result.value < 0:
        raise WinError(result.to_error())
    return args


def _check_bool(result, func, args):
    if not result:
        raise WinError(get_last_error())
    return args


def WIN(func, restype, *argtypes) -> None:
    func.restype = restype
    func.argtypes = argtypes
    if issubclass(restype, NTSTATUS):
        func.errcheck = _check_status
    elif issubclass(restype, BOOL):
        func.errcheck = _check_bool


# https://msdn.microsoft.com/en-us/library/ms683179
WIN(kernel32.GetCurrentProcess, HANDLE)

# https://msdn.microsoft.com/en-us/library/ms724251
WIN(kernel32.DuplicateHandle, BOOL,
    HANDLE,  # _In_  hSourceProcessHandle
    HANDLE,  # _In_  hSourceHandle
    HANDLE,  # _In_  hTargetProcessHandle
    PHANDLE,  # _Out_ lpTargetHandle
    DWORD,  # _In_  dwDesiredAccess
    BOOL,  # _In_  bInheritHandle
    DWORD)  # _In_  dwOptions

# https://msdn.microsoft.com/en-us/library/ms724295
WIN(kernel32.GetComputerNameW, BOOL,
    LPWSTR,  # _Out_   lpBuffer
    LPDWORD)  # _Inout_ lpnSize

# https://msdn.microsoft.com/en-us/library/aa379295
WIN(advapi32.OpenProcessToken, BOOL,
    HANDLE,  # _In_  ProcessHandle
    DWORD,  # _In_  DesiredAccess
    PHANDLE)  # _Out_ TokenHandle

# https://msdn.microsoft.com/en-us/library/aa446617
WIN(advapi32.DuplicateTokenEx, BOOL,
    HANDLE,  # _In_     hExistingToken
    DWORD,  # _In_     dwDesiredAccess
    LPSECURITY_ATTRIBUTES,  # _In_opt_ lpTokenAttributes
    SECURITY_IMPERSONATION_LEVEL,  # _In_     ImpersonationLevel
    TOKEN_TYPE,  # _In_     TokenType
    PHANDLE)  # _Out_    phNewToken

# https://msdn.microsoft.com/en-us/library/ff566415
WIN(ntdll.NtAllocateLocallyUniqueId, NTSTATUS,
    PLUID)  # _Out_ LUID

# https://msdn.microsoft.com/en-us/library/aa378279
WIN(secur32.LsaFreeReturnBuffer, NTSTATUS,
    LPVOID, )  # _In_ Buffer

# https://msdn.microsoft.com/en-us/library/aa378265
WIN(secur32.LsaConnectUntrusted, NTSTATUS,
    PHANDLE, )  # _Out_ LsaHandle

#https://msdn.microsoft.com/en-us/library/aa378318
WIN(secur32.LsaRegisterLogonProcess, NTSTATUS,
    PSTRING,  # _In_  LogonProcessName
    PHANDLE,  # _Out_ LsaHandle
    PLSA_OPERATIONAL_MODE)  # _Out_ SecurityMode

# https://msdn.microsoft.com/en-us/library/aa378269
WIN(secur32.LsaDeregisterLogonProcess, NTSTATUS,
    HANDLE)  # _In_ LsaHandle

# https://msdn.microsoft.com/en-us/library/aa378297
WIN(secur32.LsaLookupAuthenticationPackage, NTSTATUS,
    HANDLE,  # _In_  LsaHandle
    PSTRING,  # _In_  PackageName
    PULONG)  # _Out_ AuthenticationPackage

# https://msdn.microsoft.com/en-us/library/aa378292
WIN(secur32.LsaLogonUser, NTSTATUS,
    HANDLE,  # _In_     LsaHandle
    PSTRING,  # _In_     OriginName
    SECURITY_LOGON_TYPE,  # _In_     LogonType
    ULONG,  # _In_     AuthenticationPackage
    LPVOID,  # _In_     AuthenticationInformation
    ULONG,  # _In_     AuthenticationInformationLength
    PTOKEN_GROUPS,  # _In_opt_ LocalGroups
    PTOKEN_SOURCE,  # _In_     SourceContext
    PLPVOID,  # _Out_    ProfileBuffer
    PULONG,  # _Out_    ProfileBufferLength
    PLUID,  # _Out_    LogonId
    PHANDLE,  # _Out_    Token
    PQUOTA_LIMITS,  # _Out_    Quotas
    PNTSTATUS)  # _Out_    SubStatus


def duplicate_token(source_token=None, access=TOKEN_ALL_ACCESS,
                    impersonation_level=SecurityImpersonation,
                    token_type=TokenPrimary, attributes=None) -> MANAGED_HANDLE:
    close_source = False
    if source_token is None:
        close_source = True
        source_token = MANAGED_HANDLE()
        advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ALL_ACCESS, byref(source_token))
    token = MANAGED_HANDLE()
    try:
        advapi32.DuplicateTokenEx(source_token, access, attributes, impersonation_level, token_type, byref(token))
    finally:
        if close_source:
            source_token.close()
    return token


def lsa_connect_untrusted() -> int:
    handle = HANDLE()
    secur32.LsaConnectUntrusted(byref(handle))
    return handle.value


def lsa_register_logon_process(logon_process_name) -> int:
    if not isinstance(logon_process_name, bytes):
        logon_process_name = logon_process_name.encode('mbcs')
    logon_process_name = logon_process_name[:127]
    buf = create_string_buffer(logon_process_name, 128)
    name = STRING(len(logon_process_name), len(buf), buf)
    handle = HANDLE()
    mode = LSA_OPERATIONAL_MODE()
    secur32.LsaRegisterLogonProcess(byref(name), byref(handle), byref(mode))
    return handle.value


def lsa_lookup_authentication_package(lsa_handle, package_name):
    if not isinstance(package_name, bytes):
        package_name = package_name.encode('mbcs')
    package_name = package_name[:127]
    buf = create_string_buffer(package_name)
    name = STRING(len(package_name), len(buf), buf)
    package = ULONG()
    secur32.LsaLookupAuthenticationPackage(lsa_handle, byref(name), byref(package))
    return package.value


# Low-level LSA logon

LOGONINFO = namedtuple('LOGONINFO', ('Token', 'LogonId', 'Profile', 'Quotas'))


def lsa_logon_user(auth_info, local_groups=None, origin_name=py_origin_name,
                   source_context=None, auth_package=None, logon_type=None,
                   lsa_handle=None) -> LOGONINFO:
    log("lsa_logon_user%s", (auth_info, local_groups, origin_name,
                             source_context, auth_package, logon_type,
                             lsa_handle))
    if local_groups is None:
        plocal_groups = PTOKEN_GROUPS()
    else:
        plocal_groups = byref(local_groups)
    if source_context is None:
        source_context = py_source_context
    if not isinstance(origin_name, bytes):
        origin_name = origin_name.encode('mbcs')
    buf = create_string_buffer(origin_name)
    origin_name = STRING(len(origin_name), len(buf), buf)
    if auth_package is None:
        if isinstance(auth_info, MSV1_0_S4U_LOGON):
            auth_package = NEGOTIATE_PACKAGE_NAME
        elif isinstance(auth_info, KERB_S4U_LOGON):
            auth_package = MICROSOFT_KERBEROS_NAME
        else:
            auth_package = MSV1_0_PACKAGE_NAME
    if logon_type is None:
        if isinstance(auth_info, S4ULogon):
            logon_type = Batch
        else:
            logon_type = Interactive
    profile_buffer = LPVOID()
    profile_buffer_length = ULONG()
    profile = None
    logonid = LUID()
    htoken = MANAGED_HANDLE()
    quotas = QUOTA_LIMITS()
    substatus = NTSTATUS()
    deregister = False
    if lsa_handle is None:
        lsa_handle = lsa_connect_untrusted()
        deregister = True
    try:
        if isinstance(auth_package, (str, bytes)):
            auth_package = lsa_lookup_authentication_package(lsa_handle, auth_package)
        try:
            args = (
                lsa_handle, byref(origin_name),
                logon_type, auth_package, byref(auth_info),
                sizeof(auth_info), plocal_groups,
                byref(source_context), byref(profile_buffer),
                byref(profile_buffer_length), byref(logonid),
                byref(htoken), byref(quotas),
                byref(substatus),
            )
            log("LsaLogonUser%s", args)
            secur32.LsaLogonUser(*args)
        except OSError:
            if substatus.value:
                raise WinError(substatus.to_error()) from None
            raise
        finally:
            if profile_buffer:
                address = profile_buffer.value
                buftype = PROFILE_BUFFER_TYPE.from_address(address).value
                if buftype == MsV1_0InteractiveLogon:
                    profile = MSV1_0_INTERACTIVE_PROFILE.from_address_copy(address, profile_buffer_length.value)
                secur32.LsaFreeReturnBuffer(address)
    finally:
        if deregister:
            secur32.LsaDeregisterLogonProcess(lsa_handle)
    return LOGONINFO(htoken, logonid, profile, quotas)


# High-level LSA logons

def logon_msv1(name: str, password: str, domain=None, local_groups=None,
               origin_name=py_origin_name, source_context=None) -> LOGONINFO:
    return lsa_logon_user(MSV1_0_INTERACTIVE_LOGON(name, password, domain),
                          local_groups, origin_name, source_context)


def logon_msv1_s4u(name: str, local_groups=None,
                   origin_name=py_origin_name,
                   source_context=None) -> LOGONINFO:
    domain = create_unicode_buffer(MAX_COMPUTER_NAME_LENGTH + 1)
    length = DWORD(len(domain))
    kernel32.GetComputerNameW(domain, byref(length))
    return lsa_logon_user(MSV1_0_S4U_LOGON(name, domain.value),
                          local_groups, origin_name, source_context)


def logon_kerb_s4u(name: str, realm=None, local_groups=None,
                   origin_name=py_origin_name,
                   source_context=None,
                   logon_process_name=py_logon_process_name) -> LOGONINFO:
    lsa_handle = lsa_register_logon_process(logon_process_name)
    try:
        return lsa_logon_user(KERB_S4U_LOGON(name, realm),
                              local_groups, origin_name, source_context,
                              lsa_handle=lsa_handle)
    finally:
        secur32.LsaDeregisterLogonProcess(lsa_handle)


def main() -> int:
    from xpra.platform import program_context
    from xpra.log import enable_color, consume_verbose_argv
    with program_context("LSA-Logon-Test", "LSA Logon Test"):
        enable_color()
        consume_verbose_argv(sys.argv, "win32")
        if len(sys.argv) not in (2, 3):
            log.warn("invalid number of arguments")
            log.warn("usage: %s [--verbose] username [password]", sys.argv[0])
            return 1
        username = sys.argv[1]
        password = "" if len(sys.argv) < 3 else sys.argv[2]
        try:
            if password:
                logon_msv1(username, password)
            else:
                logon_msv1_s4u(username)
            return 0
        except Exception as e:
            log.error("Logon failed: %s", e)
            return 1


if __name__ == "__main__":
    sys.exit(main())
