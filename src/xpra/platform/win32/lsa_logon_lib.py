#!/usr/bin/env python
# This file is part of Xpra.
# This code is released under the terms of the MIT license:
# https://opensource.org/licenses/MIT
# This LSA code was found here:
# https://stackoverflow.com/questions/43114209/

import os
import sys
import ctypes
import collections

from ctypes import wintypes

ntdll = ctypes.WinDLL('ntdll')
secur32 = ctypes.WinDLL('secur32')
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)

MAX_COMPUTER_NAME_LENGTH = 15

SECURITY_LOGON_TYPE = wintypes.ULONG
Interactive = 2
Network = 3
Batch = 4
Service = 5

LOGON_SUBMIT_TYPE = wintypes.ULONG
PROFILE_BUFFER_TYPE = wintypes.ULONG

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

DELETE       = 0x00010000
READ_CONTROL = 0x00020000
WRITE_DAC    = 0x00040000
WRITE_OWNER  = 0x00080000

STANDARD_RIGHTS_REQUIRED = (DELETE       |
                            READ_CONTROL |
                            WRITE_DAC    |
                            WRITE_OWNER)

TOKEN_ASSIGN_PRIMARY    = 0x0001
TOKEN_DUPLICATE         = 0x0002
TOKEN_IMPERSONATE       = 0x0004
TOKEN_QUERY             = 0x0008
TOKEN_QUERY_SOURCE      = 0x0010
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_ADJUST_GROUPS     = 0x0040
TOKEN_ADJUST_DEFAULT    = 0x0080
TOKEN_ADJUST_SESSIONID  = 0x0100

TOKEN_ALL_ACCESS = (STANDARD_RIGHTS_REQUIRED |
                    TOKEN_ASSIGN_PRIMARY     |
                    TOKEN_DUPLICATE          |
                    TOKEN_IMPERSONATE        |
                    TOKEN_QUERY              |
                    TOKEN_QUERY_SOURCE       |
                    TOKEN_ADJUST_PRIVILEGES  |
                    TOKEN_ADJUST_GROUPS      |
                    TOKEN_ADJUST_DEFAULT     |
                    TOKEN_ADJUST_SESSIONID)

DUPLICATE_CLOSE_SOURCE = 0x00000001
DUPLICATE_SAME_ACCESS  = 0x00000002

TOKEN_TYPE = wintypes.ULONG
TokenPrimary       = 1
TokenImpersonation = 2

SECURITY_IMPERSONATION_LEVEL = wintypes.ULONG
SecurityAnonymous      = 0
SecurityIdentification = 1
SecurityImpersonation  = 2
SecurityDelegation     = 3

class NTSTATUS(wintypes.LONG):

    def to_error(self):
        return ntdll.RtlNtStatusToDosError(self)

    def __repr__(self):
        name = self.__class__.__name__
        status = wintypes.ULONG.from_buffer(self)           #@UndefinedVariable
        return '%s(%#010x)' % (name, status.value)

PNTSTATUS = ctypes.POINTER(NTSTATUS)

class BOOL(wintypes.BOOL):
    def __repr__(self):
        name = self.__class__.__name__
        return '%s(%s)' % (name, bool(self))

class HANDLE(wintypes.HANDLE):
    __slots__ = 'closed',

    def __int__(self):
        return self.value or 0

    def Detach(self):
        if not getattr(self, 'closed', False):
            self.closed = True
            value = int(self)
            self.value = None
            return value
        raise ValueError("already closed")

    def Close(self, CloseHandle=kernel32.CloseHandle):
        if self and not getattr(self, 'closed', False):
            CloseHandle(self.Detach())

    __del__ = Close

    def __repr__(self):
        return "%s(%d)" % (self.__class__.__name__, int(self))

class LARGE_INTEGER(wintypes.LARGE_INTEGER):
    # https://msdn.microsoft.com/en-us/library/ff553204
    ntdll.RtlSecondsSince1970ToTime.restype = None
    _unix_epoch = wintypes.LARGE_INTEGER()
    ntdll.RtlSecondsSince1970ToTime(0, ctypes.byref(_unix_epoch))
    _unix_epoch = _unix_epoch.value

    def __int__(self):
        return self.value

    def __repr__(self):
        name = self.__class__.__name__
        return '%s(%d)' % (name, self.value)

    def as_time(self):
        time100ns = self.value - self._unix_epoch
        if time100ns >= 0:
            return time100ns / 1e7
        raise ValueError('value predates the Unix epoch')

    @classmethod
    def from_time(cls, t):
        time100ns = int(t * 10**7)
        return cls(time100ns + cls._unix_epoch)

CHAR = ctypes.c_char
WCHAR = ctypes.c_wchar
PCHAR = ctypes.POINTER(CHAR)
PWCHAR = ctypes.POINTER(WCHAR)

class STRING(ctypes.Structure):
    _fields_ = (('Length',        wintypes.USHORT),
                ('MaximumLength', wintypes.USHORT),
                ('Buffer',        PCHAR))

PSTRING = ctypes.POINTER(STRING)

class UNICODE_STRING(ctypes.Structure):
    _fields_ = (('Length',        wintypes.USHORT),
                ('MaximumLength', wintypes.USHORT),
                ('Buffer',        PWCHAR))

PUNICODE_STRING = ctypes.POINTER(UNICODE_STRING)

class LUID(ctypes.Structure):
    _fields_ = (('LowPart',  wintypes.DWORD),
                ('HighPart', wintypes.LONG))

    def __new__(cls, value=0):
        return cls.from_buffer_copy(ctypes.c_ulonglong(value))

    def __int__(self):
        return ctypes.c_ulonglong.from_buffer(self).value       #@UndefinedVariable

    def __repr__(self):
        name = self.__class__.__name__
        return '%s(%#x)' % (name, int(self))

PLUID = ctypes.POINTER(LUID)
PSID = wintypes.LPVOID

class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = (('Sid',        PSID),
                ('Attributes', wintypes.DWORD))

PSID_AND_ATTRIBUTES = ctypes.POINTER(SID_AND_ATTRIBUTES)

class TOKEN_GROUPS(ctypes.Structure):
    _fields_ = (('GroupCount', wintypes.DWORD),
                ('Groups',     SID_AND_ATTRIBUTES * 1))

PTOKEN_GROUPS = ctypes.POINTER(TOKEN_GROUPS)

class TOKEN_SOURCE(ctypes.Structure):
    _fields_ = (('SourceName', CHAR * TOKEN_SOURCE_LENGTH),
                ('SourceIdentifier', LUID))
    def __init__(self, SourceName=None, SourceIdentifier=None):
        if SourceName is not None:
            if not isinstance(SourceName, bytes):
                SourceName = SourceName.encode('mbcs')
            self.SourceName = SourceName
        if SourceIdentifier is None:
            luid = self.SourceIdentifier
            ntdll.NtAllocateLocallyUniqueId(ctypes.byref(luid))
        else:
            self.SourceIdentifier = SourceIdentifier

PTOKEN_SOURCE = ctypes.POINTER(TOKEN_SOURCE)

py_source_context = TOKEN_SOURCE(b"PYTHON  ")
py_origin_name = b"Python-%d" % os.getpid()
py_logon_process_name = b"PythonLogonProcess-%d" % os.getpid()

SIZE_T = ctypes.c_size_t

class QUOTA_LIMITS(ctypes.Structure):
    _fields_ = (('PagedPoolLimit',        SIZE_T),
                ('NonPagedPoolLimit',     SIZE_T),
                ('MinimumWorkingSetSize', SIZE_T),
                ('MaximumWorkingSetSize', SIZE_T),
                ('PagefileLimit',         SIZE_T),
                ('TimeLimit',             wintypes.LARGE_INTEGER))

PQUOTA_LIMITS = ctypes.POINTER(QUOTA_LIMITS)

PULONG = ctypes.POINTER(wintypes.ULONG)
LSA_OPERATIONAL_MODE = wintypes.ULONG
PLSA_OPERATIONAL_MODE = PULONG
PHANDLE = ctypes.POINTER(wintypes.HANDLE)
PLPVOID = ctypes.POINTER(wintypes.LPVOID)
LPDWORD = ctypes.POINTER(wintypes.DWORD)

class ContiguousUnicode(ctypes.Structure):
    # _string_names_: sequence matched to underscore-prefixed fields

    def _get_unicode_string(self, name):
        wchar_size = ctypes.sizeof(WCHAR)
        s = getattr(self, '_%s' % name)
        length = s.Length // wchar_size
        buf = s.Buffer
        if buf:
            return buf[:length]
        return None

    def _set_unicode_buffer(self, value):
        cls = type(self)
        wchar_size = ctypes.sizeof(WCHAR)
        bufsize = (len(value) + 1) * wchar_size
        ctypes.resize(self, ctypes.sizeof(cls) + bufsize)
        addr = ctypes.addressof(self) + ctypes.sizeof(cls)
        ctypes.memmove(addr, value, bufsize)

    def _set_unicode_string(self, name, value):
        values = []
        for n in self._string_names_:
            if n == name:
                values.append(value or u'')
            else:
                values.append(getattr(self, n) or u'')
        self._set_unicode_buffer(u'\x00'.join(values))

        cls = type(self)
        wchar_size = ctypes.sizeof(WCHAR)
        addr = ctypes.addressof(self) + ctypes.sizeof(cls)
        for n, v in zip(self._string_names_, values):
            ptr = ctypes.cast(addr, PWCHAR)
            ustr = getattr(self, '_%s' % n)
            length = ustr.Length = len(v) * wchar_size
            full_length = length + wchar_size
            if ((n == name and value is None) or
                (n != name and not (length or ustr.Buffer))):
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
            super(ContiguousUnicode, self).__setattr__(name, value)

    @classmethod
    def from_address_copy(cls, address, size=None):
        x = ctypes.Structure.__new__(cls)       #@UndefinedVariable
        if size is not None:
            ctypes.resize(x, size)
        ctypes.memmove(ctypes.byref(x), address, ctypes.sizeof(x))
        delta = ctypes.addressof(x) - address
        for n in cls._string_names_:
            ustr = getattr(x, '_%s' % n)
            addr = ctypes.c_void_p.from_buffer(ustr.Buffer)     #@UndefinedVariable
            if addr:
                addr.value += delta
        return x

class AuthInfo(ContiguousUnicode):
    # _message_type_: from a logon-submit-type enumeration
    def __init__(self):
        self.MessageType = self._message_type_

class MSV1_0_INTERACTIVE_LOGON(AuthInfo):
    _message_type_ = MsV1_0InteractiveLogon
    _string_names_ = 'LogonDomainName', 'UserName', 'Password'

    _fields_ = (('MessageType',      LOGON_SUBMIT_TYPE),
                ('_LogonDomainName', UNICODE_STRING),
                ('_UserName',        UNICODE_STRING),
                ('_Password',        UNICODE_STRING))

    def __init__(self, UserName=None, Password=None, LogonDomainName=None):
        super(MSV1_0_INTERACTIVE_LOGON, self).__init__()
        if LogonDomainName is not None:
            self.LogonDomainName = LogonDomainName
        if UserName is not None:
            self.UserName = UserName
        if Password is not None:
            self.Password = Password

class S4ULogon(AuthInfo):
    _string_names_ = 'UserPrincipalName', 'DomainName'

    _fields_ = (('MessageType',        LOGON_SUBMIT_TYPE),
                ('Flags',              wintypes.ULONG),
                ('_UserPrincipalName', UNICODE_STRING),
                ('_DomainName',        UNICODE_STRING))

    def __init__(self, UserPrincipalName=None, DomainName=None, Flags=0):
        super(S4ULogon, self).__init__()
        self.Flags = Flags
        if UserPrincipalName is not None:
            self.UserPrincipalName = UserPrincipalName
        if DomainName is not None:
            self.DomainName = DomainName

class MSV1_0_S4U_LOGON(S4ULogon):
    _message_type_ = MsV1_0S4ULogon

class KERB_S4U_LOGON(S4ULogon):
    _message_type_ = KerbS4ULogon

PMSV1_0_S4U_LOGON = ctypes.POINTER(MSV1_0_S4U_LOGON)
PKERB_S4U_LOGON = ctypes.POINTER(KERB_S4U_LOGON)

class ProfileBuffer(ContiguousUnicode):
    # _message_type_
    def __init__(self):
        self.MessageType = self._message_type_

class MSV1_0_INTERACTIVE_PROFILE(ProfileBuffer):
    _message_type_ = MsV1_0InteractiveLogon
    _string_names_ = ('LogonScript', 'HomeDirectory', 'FullName',
                      'ProfilePath', 'HomeDirectoryDrive', 'LogonServer')
    _fields_ = (('MessageType',         PROFILE_BUFFER_TYPE),
                ('LogonCount',          wintypes.USHORT),
                ('BadPasswordCount',    wintypes.USHORT),
                ('LogonTime',           LARGE_INTEGER),
                ('LogoffTime',          LARGE_INTEGER),
                ('KickOffTime',         LARGE_INTEGER),
                ('PasswordLastSet',     LARGE_INTEGER),
                ('PasswordCanChange',   LARGE_INTEGER),
                ('PasswordMustChange',  LARGE_INTEGER),
                ('_LogonScript',        UNICODE_STRING),
                ('_HomeDirectory',      UNICODE_STRING),
                ('_FullName',           UNICODE_STRING),
                ('_ProfilePath',        UNICODE_STRING),
                ('_HomeDirectoryDrive', UNICODE_STRING),
                ('_LogonServer',        UNICODE_STRING),
                ('UserFlags',           wintypes.ULONG))

class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = (('nLength',              wintypes.DWORD),
                ('lpSecurityDescriptor', wintypes.LPVOID),
                ('bInheritHandle',       wintypes.BOOL))
    def __init__(self, **kwds):
        self.nLength = ctypes.sizeof(self)
        super(SECURITY_ATTRIBUTES, self).__init__(**kwds)

LPSECURITY_ATTRIBUTES = ctypes.POINTER(SECURITY_ATTRIBUTES)

def _check_status(result, func, args):
    if result.value < 0:
        raise ctypes.WinError(result.to_error())
    return args

def _check_bool(result, func, args):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return args

def WIN(func, restype, *argtypes):
    func.restype = restype
    func.argtypes = argtypes
    if issubclass(restype, NTSTATUS):
        func.errcheck = _check_status
    elif issubclass(restype, BOOL):
        func.errcheck = _check_bool

# https://msdn.microsoft.com/en-us/library/ms683179
WIN(kernel32.GetCurrentProcess, wintypes.HANDLE)

# https://msdn.microsoft.com/en-us/library/ms724251
WIN(kernel32.DuplicateHandle, BOOL,
    wintypes.HANDLE, # _In_  hSourceProcessHandle
    wintypes.HANDLE, # _In_  hSourceHandle
    wintypes.HANDLE, # _In_  hTargetProcessHandle
    PHANDLE,         # _Out_ lpTargetHandle
    wintypes.DWORD,  # _In_  dwDesiredAccess
    wintypes.BOOL,   # _In_  bInheritHandle
    wintypes.DWORD)  # _In_  dwOptions

# https://msdn.microsoft.com/en-us/library/ms724295
WIN(kernel32.GetComputerNameW, BOOL,
    wintypes.LPWSTR, # _Out_   lpBuffer
    LPDWORD)         # _Inout_ lpnSize

# https://msdn.microsoft.com/en-us/library/aa379295
WIN(advapi32.OpenProcessToken, BOOL,
    wintypes.HANDLE, # _In_  ProcessHandle
    wintypes.DWORD,  # _In_  DesiredAccess
    PHANDLE)         # _Out_ TokenHandle

# https://msdn.microsoft.com/en-us/library/aa446617
WIN(advapi32.DuplicateTokenEx, BOOL,
    wintypes.HANDLE,              # _In_     hExistingToken
    wintypes.DWORD,               # _In_     dwDesiredAccess
    LPSECURITY_ATTRIBUTES,        # _In_opt_ lpTokenAttributes
    SECURITY_IMPERSONATION_LEVEL, # _In_     ImpersonationLevel
    TOKEN_TYPE,                   # _In_     TokenType
    PHANDLE)                      # _Out_    phNewToken

# https://msdn.microsoft.com/en-us/library/ff566415
WIN(ntdll.NtAllocateLocallyUniqueId, NTSTATUS,
    PLUID) # _Out_ LUID

# https://msdn.microsoft.com/en-us/library/aa378279
WIN(secur32.LsaFreeReturnBuffer, NTSTATUS,
    wintypes.LPVOID,) # _In_ Buffer

# https://msdn.microsoft.com/en-us/library/aa378265
WIN(secur32.LsaConnectUntrusted, NTSTATUS,
    PHANDLE,) # _Out_ LsaHandle

#https://msdn.microsoft.com/en-us/library/aa378318
WIN(secur32.LsaRegisterLogonProcess, NTSTATUS,
    PSTRING,               # _In_  LogonProcessName
    PHANDLE,               # _Out_ LsaHandle
    PLSA_OPERATIONAL_MODE) # _Out_ SecurityMode

# https://msdn.microsoft.com/en-us/library/aa378269
WIN(secur32.LsaDeregisterLogonProcess, NTSTATUS,
    wintypes.HANDLE) # _In_ LsaHandle

# https://msdn.microsoft.com/en-us/library/aa378297
WIN(secur32.LsaLookupAuthenticationPackage, NTSTATUS,
    wintypes.HANDLE, # _In_  LsaHandle
    PSTRING,         # _In_  PackageName
    PULONG)          # _Out_ AuthenticationPackage

# https://msdn.microsoft.com/en-us/library/aa378292
WIN(secur32.LsaLogonUser, NTSTATUS,
    wintypes.HANDLE,     # _In_     LsaHandle
    PSTRING,             # _In_     OriginName
    SECURITY_LOGON_TYPE, # _In_     LogonType
    wintypes.ULONG,      # _In_     AuthenticationPackage
    wintypes.LPVOID,     # _In_     AuthenticationInformation
    wintypes.ULONG,      # _In_     AuthenticationInformationLength
    PTOKEN_GROUPS,       # _In_opt_ LocalGroups
    PTOKEN_SOURCE,       # _In_     SourceContext
    PLPVOID,             # _Out_    ProfileBuffer
    PULONG,              # _Out_    ProfileBufferLength
    PLUID,               # _Out_    LogonId
    PHANDLE,             # _Out_    Token
    PQUOTA_LIMITS,       # _Out_    Quotas
    PNTSTATUS)           # _Out_    SubStatus


def duplicate_token(source_token=None, access=TOKEN_ALL_ACCESS,
                    impersonation_level=SecurityImpersonation,
                    token_type=TokenPrimary, attributes=None):
    close_source = False
    if source_token is None:
        close_source = True
        source_token = HANDLE()
        advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
            TOKEN_ALL_ACCESS, ctypes.byref(source_token))
    token = HANDLE()
    try:
        advapi32.DuplicateTokenEx(source_token, access, attributes,
            impersonation_level, token_type, ctypes.byref(token))
    finally:
        if close_source:
            source_token.Close()
    return token

def lsa_connect_untrusted():
    handle = wintypes.HANDLE()
    secur32.LsaConnectUntrusted(ctypes.byref(handle))
    return handle.value

def lsa_register_logon_process(logon_process_name):
    if not isinstance(logon_process_name, bytes):
        logon_process_name = logon_process_name.encode('mbcs')
    logon_process_name = logon_process_name[:127]
    buf = ctypes.create_string_buffer(logon_process_name, 128)
    name = STRING(len(logon_process_name), len(buf), buf)
    handle = wintypes.HANDLE()
    mode = LSA_OPERATIONAL_MODE()
    secur32.LsaRegisterLogonProcess(ctypes.byref(name),
        ctypes.byref(handle), ctypes.byref(mode))
    return handle.value

def lsa_lookup_authentication_package(lsa_handle, package_name):
    if not isinstance(package_name, bytes):
        package_name = package_name.encode('mbcs')
    package_name = package_name[:127]
    buf = ctypes.create_string_buffer(package_name)
    name = STRING(len(package_name), len(buf), buf)
    package = wintypes.ULONG()
    secur32.LsaLookupAuthenticationPackage(lsa_handle, ctypes.byref(name),
        ctypes.byref(package))
    return package.value


# Low-level LSA logon

LOGONINFO = collections.namedtuple('LOGONINFO',
                                   ('Token', 'LogonId', 'Profile', 'Quotas')
                                   )

def lsa_logon_user(auth_info, local_groups=None, origin_name=py_origin_name,
                   source_context=None, auth_package=None, logon_type=None,
                   lsa_handle=None):
    from xpra.log import Logger
    log = Logger("win32")
    log("lsa_logon_user%s", (auth_info, local_groups, origin_name,
                   source_context, auth_package, logon_type,
                   lsa_handle))
    if local_groups is None:
        plocal_groups = PTOKEN_GROUPS()
    else:
        plocal_groups = ctypes.byref(local_groups)
    if source_context is None:
        source_context = py_source_context
    if not isinstance(origin_name, bytes):
        origin_name = origin_name.encode('mbcs')
    buf = ctypes.create_string_buffer(origin_name)
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
    profile_buffer = wintypes.LPVOID()
    profile_buffer_length = wintypes.ULONG()
    profile = None
    logonid = LUID()
    htoken = HANDLE()
    quotas = QUOTA_LIMITS()
    substatus = NTSTATUS()
    deregister = False
    if lsa_handle is None:
        lsa_handle = lsa_connect_untrusted()
        deregister = True
    try:
        if isinstance(auth_package, (str, bytes)):
            auth_package = lsa_lookup_authentication_package(lsa_handle,
                                auth_package)
        try:
            args = (lsa_handle, ctypes.byref(origin_name),
                logon_type, auth_package, ctypes.byref(auth_info),
                ctypes.sizeof(auth_info), plocal_groups,
                ctypes.byref(source_context), ctypes.byref(profile_buffer),
                ctypes.byref(profile_buffer_length), ctypes.byref(logonid),
                ctypes.byref(htoken), ctypes.byref(quotas),
                ctypes.byref(substatus))
            log("LsaLogonUser%s", args)
            secur32.LsaLogonUser(*args)
        except WindowsError:            #@UndefinedVariable
            if substatus.value:
                raise ctypes.WinError(substatus.to_error())
            raise
        finally:
            if profile_buffer:
                address = profile_buffer.value
                buftype = PROFILE_BUFFER_TYPE.from_address(address).value
                if buftype == MsV1_0InteractiveLogon:
                    profile = MSV1_0_INTERACTIVE_PROFILE.from_address_copy(
                                address, profile_buffer_length.value)
                secur32.LsaFreeReturnBuffer(address)
    finally:
        if deregister:
            secur32.LsaDeregisterLogonProcess(lsa_handle)
    return LOGONINFO(htoken, logonid, profile, quotas)


# High-level LSA logons

def logon_msv1(name, password, domain=None, local_groups=None,
                origin_name=py_origin_name, source_context=None):
    return lsa_logon_user(MSV1_0_INTERACTIVE_LOGON(name, password, domain),
                local_groups, origin_name, source_context)

def logon_msv1_s4u(name, local_groups=None, origin_name=py_origin_name,
                    source_context=None):
    domain = ctypes.create_unicode_buffer(MAX_COMPUTER_NAME_LENGTH + 1)
    length = wintypes.DWORD(len(domain))
    kernel32.GetComputerNameW(domain, ctypes.byref(length))
    return lsa_logon_user(MSV1_0_S4U_LOGON(name, domain.value),
                local_groups, origin_name, source_context)

def logon_kerb_s4u(name, realm=None, local_groups=None,
                     origin_name=py_origin_name,
                     source_context=None,
                     logon_process_name=py_logon_process_name):
    lsa_handle = lsa_register_logon_process(logon_process_name)
    try:
        return lsa_logon_user(KERB_S4U_LOGON(name, realm),
                    local_groups, origin_name, source_context,
                    lsa_handle=lsa_handle)
    finally:
        secur32.LsaDeregisterLogonProcess(lsa_handle)


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color, Logger, enable_debug_for
    log = Logger("win32")
    with program_context("LSA-Logon-Test", "LSA Logon Test"):
        enable_color()
        for x in ("-v", "--verbose"):
            if x in list(sys.argv):
                enable_debug_for("win32")
                sys.argv.remove(x)
        if len(sys.argv)!=2:
            log.warn("invalid number of arguments")
            log.warn("usage: %s [--verbose] username", sys.argv[0])
            return 1
        username = sys.argv[1]
        try:
            logon_msv1_s4u(username)
            return 0
        except Exception as e:
            log.error("Logon failed: %s", e)
            return 1

if __name__ == "__main__":
    sys.exit(main())
