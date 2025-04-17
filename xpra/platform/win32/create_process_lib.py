#!/usr/bin/env python3
# This file is part of Xpra.
# This code is released under the terms of the CC-BY-SA license:
# https://creativecommons.org/licenses/by-sa/2.0/legalcode
# This subprocess.Popen code was found here:
# https://stackoverflow.com/questions/29566330/

# pylint: disable=unused-argument

import os
import subprocess
from ctypes import (
    get_last_error, WinError, WinDLL,  # @UnresolvedImport
    Structure, POINTER, sizeof,
)
from ctypes import wintypes
from ctypes.wintypes import BYTE, BOOL, WORD, DWORD, LPWSTR, LPCWSTR, LPVOID   # @UnresolvedImport

from xpra.log import Logger
log = Logger("win32")

kernel32 = WinDLL('kernel32', use_last_error=True)
advapi32 = WinDLL('advapi32', use_last_error=True)

ERROR_INVALID_HANDLE = 0x0006
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
INVALID_DWORD_VALUE = DWORD(-1).value

DEBUG_PROCESS                    = 0x00000001
DEBUG_ONLY_THIS_PROCESS          = 0x00000002
CREATE_SUSPENDED                 = 0x00000004
DETACHED_PROCESS                 = 0x00000008
CREATE_NEW_CONSOLE               = 0x00000010
CREATE_NEW_PROCESS_GROUP         = 0x00000200
CREATE_UNICODE_ENVIRONMENT       = 0x00000400
CREATE_SEPARATE_WOW_VDM          = 0x00000800
CREATE_SHARED_WOW_VDM            = 0x00001000
INHERIT_PARENT_AFFINITY          = 0x00010000
CREATE_PROTECTED_PROCESS         = 0x00040000
EXTENDED_STARTUPINFO_PRESENT     = 0x00080000
CREATE_BREAKAWAY_FROM_JOB        = 0x01000000
CREATE_PRESERVE_CODE_AUTHZ_LEVEL = 0x02000000
CREATE_DEFAULT_ERROR_MODE        = 0x04000000
CREATE_NO_WINDOW                 = 0x08000000

STARTF_USESHOWWINDOW    = 0x00000001
STARTF_USESIZE          = 0x00000002
STARTF_USEPOSITION      = 0x00000004
STARTF_USECOUNTCHARS    = 0x00000008
STARTF_USEFILLATTRIBUTE = 0x00000010
STARTF_RUNFULLSCREEN    = 0x00000020
STARTF_FORCEONFEEDBACK  = 0x00000040
STARTF_FORCEOFFFEEDBACK = 0x00000080
STARTF_USESTDHANDLES    = 0x00000100
STARTF_USEHOTKEY        = 0x00000200
STARTF_TITLEISLINKNAME  = 0x00000800
STARTF_TITLEISAPPID     = 0x00001000
STARTF_PREVENTPINNING   = 0x00002000

SW_HIDE            = 0
SW_SHOWNORMAL      = 1
SW_SHOWMINIMIZED   = 2
SW_SHOWMAXIMIZED   = 3
SW_SHOWNOACTIVATE  = 4
SW_SHOW            = 5
SW_MINIMIZE        = 6
SW_SHOWMINNOACTIVE = 7
SW_SHOWNA          = 8
SW_RESTORE         = 9
SW_SHOWDEFAULT     = 10  #  ~STARTUPINFO
SW_FORCEMINIMIZE   = 11

LOGON_WITH_PROFILE        = 0x00000001
LOGON_NETCREDENTIALS_ONLY = 0x00000002


class HANDLE(wintypes.HANDLE):
    __slots__ = 'closed',

    def __int__(self):
        return self.value or 0

    def Detach(self) -> int:
        if not getattr(self, 'closed', False):
            self.closed = True
            value = int(self)
            self.value = None
            return value
        raise ValueError("already closed")

    def Close(self, CloseHandle=kernel32.CloseHandle) -> None:
        if self and not getattr(self, 'closed', False):
            CloseHandle(self.Detach())

    __del__ = Close

    def __repr__(self):
        return "%s(%d)" % (self.__class__.__name__, int(self))


class PROCESS_INFORMATION(Structure):
    """https://msdn.microsoft.com/en-us/library/ms684873"""
    __slots__ = '_cached_hProcess', '_cached_hThread'

    _fields_ = (
        ('_hProcess', HANDLE),
        ('_hThread', HANDLE),
        ('dwProcessId', DWORD),
        ('dwThreadId', DWORD),
    )

    @property
    def hProcess(self):
        if not hasattr(self, '_cached_hProcess'):
            self._cached_hProcess = self._hProcess
        return self._cached_hProcess

    @property
    def hThread(self):
        if not hasattr(self, '_cached_hThread'):
            self._cached_hThread = self._hThread
        return self._cached_hThread

    def __del__(self):
        try:
            self.hProcess.Close()
        finally:
            self.hThread.Close()


LPPROCESS_INFORMATION = POINTER(PROCESS_INFORMATION)

LPBYTE = POINTER(BYTE)


class STARTUPINFO(Structure):
    """https://msdn.microsoft.com/en-us/library/ms686331"""
    _fields_ = (
        ('cb',              DWORD),
        ('lpReserved',      LPWSTR),
        ('lpDesktop',       LPWSTR),
        ('lpTitle',         LPWSTR),
        ('dwX',             DWORD),
        ('dwY',             DWORD),
        ('dwXSize',         DWORD),
        ('dwYSize',         DWORD),
        ('dwXCountChars',   DWORD),
        ('dwYCountChars',   DWORD),
        ('dwFillAttribute', DWORD),
        ('dwFlags',         DWORD),
        ('wShowWindow',     WORD),
        ('cbReserved2',     WORD),
        ('lpReserved2',     LPBYTE),
        ('hStdInput',       HANDLE),
        ('hStdOutput',      HANDLE),
        ('hStdError',       HANDLE),
    )

    def __init__(self, **kwds):
        self.cb = sizeof(self)
        super().__init__(**kwds)

    def __repr__(self):
        return "<STARTUPINFO>"


class PROC_THREAD_ATTRIBUTE_LIST(Structure):
    pass


PPROC_THREAD_ATTRIBUTE_LIST = POINTER(PROC_THREAD_ATTRIBUTE_LIST)


class STARTUPINFOEX(STARTUPINFO):
    _fields_ = (
        ('lpAttributelist', PPROC_THREAD_ATTRIBUTE_LIST),
    )


LPSTARTUPINFO = POINTER(STARTUPINFO)
LPSTARTUPINFOEX = POINTER(STARTUPINFOEX)


class SECURITY_ATTRIBUTES(Structure):
    _fields_ = (
        ('nLength',              DWORD),
        ('lpSecurityDescriptor', LPVOID),
        ('bInheritHandle',       BOOL),
    )

    def __init__(self, **kwds):
        self.nLength = sizeof(self)
        super().__init__(**kwds)


LPSECURITY_ATTRIBUTES = POINTER(SECURITY_ATTRIBUTES)


class HANDLE_IHV(HANDLE):
    pass


class DWORD_IDV(DWORD):
    pass


def _check_ihv(result, func, args):
    if result.value == INVALID_HANDLE_VALUE:
        raise WinError(get_last_error())
    return result.value


def _check_idv(result, func, args):
    if result.value == INVALID_DWORD_VALUE:
        raise WinError(get_last_error())
    return result.value


def _check_bool(result, func, args):
    if not result:
        raise WinError(get_last_error())
    return args


def WIN(func, restype, *argtypes) -> None:
    func.restype = restype
    func.argtypes = argtypes
    if issubclass(restype, HANDLE_IHV):
        func.errcheck = _check_ihv
    elif issubclass(restype, DWORD_IDV):
        func.errcheck = _check_idv
    else:
        func.errcheck = _check_bool

# https://msdn.microsoft.com/en-us/library/ms724211


WIN(kernel32.CloseHandle, BOOL, HANDLE)  # _In_ HANDLE hObject


# https://msdn.microsoft.com/en-us/library/ms685086
WIN(kernel32.ResumeThread, DWORD_IDV,HANDLE)  # _In_ hThread

# https://msdn.microsoft.com/en-us/library/ms682425
WIN(kernel32.CreateProcessW, BOOL,
    LPCWSTR,       # _In_opt_    lpApplicationName
    LPWSTR,        # _Inout_opt_ lpCommandLine
    LPSECURITY_ATTRIBUTES,  # _In_opt_    lpProcessAttributes
    LPSECURITY_ATTRIBUTES,  # _In_opt_    lpThreadAttributes
    BOOL,          # _In_        bInheritHandles
    DWORD,         # _In_        dwCreationFlags
    LPCWSTR,       # _In_opt_    lpEnvironment
    LPCWSTR,       # _In_opt_    lpCurrentDirectory
    LPSTARTUPINFO,          # _In_        lpStartupInfo
    LPPROCESS_INFORMATION)  # _Out_       lpProcessInformation

# https://msdn.microsoft.com/en-us/library/ms682429
WIN(advapi32.CreateProcessAsUserW, BOOL,
    HANDLE,        # _In_opt_    hToken
    LPCWSTR,       # _In_opt_    lpApplicationName
    LPWSTR,        # _Inout_opt_ lpCommandLine
    LPSECURITY_ATTRIBUTES,  # _In_opt_    lpProcessAttributes
    LPSECURITY_ATTRIBUTES,  # _In_opt_    lpThreadAttributes
    BOOL,          # _In_        bInheritHandles
    DWORD,         # _In_        dwCreationFlags
    LPCWSTR,       # _In_opt_    lpEnvironment
    LPCWSTR,       # _In_opt_    lpCurrentDirectory
    LPSTARTUPINFO,          # _In_        lpStartupInfo
    LPPROCESS_INFORMATION)  # _Out_       lpProcessInformation

# https://msdn.microsoft.com/en-us/library/ms682434
WIN(advapi32.CreateProcessWithTokenW, BOOL,
    HANDLE,        # _In_        hToken
    DWORD,         # _In_        dwLogonFlags
    LPCWSTR,       # _In_opt_    lpApplicationName
    LPWSTR,        # _Inout_opt_ lpCommandLine
    DWORD,         # _In_        dwCreationFlags
    LPCWSTR,       # _In_opt_    lpEnvironment
    LPCWSTR,       # _In_opt_    lpCurrentDirectory
    LPSTARTUPINFO,          # _In_        lpStartupInfo
    LPPROCESS_INFORMATION)  # _Out_       lpProcessInformation

# https://msdn.microsoft.com/en-us/library/ms682431
WIN(advapi32.CreateProcessWithLogonW, BOOL,
    LPCWSTR,       # _In_        lpUsername
    LPCWSTR,       # _In_opt_    lpDomain
    LPCWSTR,       # _In_        lpPassword
    DWORD,         # _In_        dwLogonFlags
    LPCWSTR,       # _In_opt_    lpApplicationName
    LPWSTR,        # _Inout_opt_ lpCommandLine
    DWORD,         # _In_        dwCreationFlags
    LPCWSTR,       # _In_opt_    lpEnvironment
    LPCWSTR,       # _In_opt_    lpCurrentDirectory
    LPSTARTUPINFO,          # _In_        lpStartupInfo
    LPPROCESS_INFORMATION)  # _Out_       lpProcessInformation


CREATION_TYPE_NORMAL = 0
CREATION_TYPE_LOGON = 1
CREATION_TYPE_TOKEN = 2
CREATION_TYPE_USER = 3


class CREATIONINFO:
    __slots__ = (
        'dwCreationType',
        'lpApplicationName', 'lpCommandLine', 'bUseShell',
        'lpProcessAttributes', 'lpThreadAttributes', 'bInheritHandles',
        'dwCreationFlags', 'lpEnvironment', 'lpCurrentDirectory',
        'hToken', 'lpUsername', 'lpDomain', 'lpPassword', 'dwLogonFlags',
    )

    def __init__(self, dwCreationType=CREATION_TYPE_NORMAL,
                 lpApplicationName=None, lpCommandLine=None, bUseShell=False,
                 lpProcessAttributes=None, lpThreadAttributes=None,
                 bInheritHandles=False, dwCreationFlags=0, lpEnvironment=None,
                 lpCurrentDirectory=None, hToken=None, dwLogonFlags=0,
                 lpUsername=None, lpDomain=None, lpPassword=None):
        self.dwCreationType = dwCreationType
        self.lpApplicationName = lpApplicationName
        self.lpCommandLine = lpCommandLine
        self.bUseShell = bUseShell
        self.lpProcessAttributes = lpProcessAttributes
        self.lpThreadAttributes = lpThreadAttributes
        self.bInheritHandles = bInheritHandles
        self.dwCreationFlags = dwCreationFlags
        self.lpEnvironment = lpEnvironment
        self.lpCurrentDirectory = lpCurrentDirectory
        self.hToken = hToken
        self.lpUsername = lpUsername
        self.lpDomain = lpDomain
        self.lpPassword = lpPassword
        self.dwLogonFlags = dwLogonFlags

    def __repr__(self):
        return "<CREATIONINFO>"


def create_environment(environ):
    log("create_environment(%r)", environ)
    if environ is not None:
        items = ['%s=%s' % (k, environ[k]) for k in sorted(environ)]
        return '\x00'.join(items)
    return None


def create_process(commandline=None, creationinfo=None, startupinfo=None):
    log("create_process%s", (commandline, creationinfo, startupinfo))
    if creationinfo is None:
        creationinfo = CREATIONINFO()

    if startupinfo is None:
        startupinfo = STARTUPINFO()
    elif isinstance(startupinfo, subprocess.STARTUPINFO):  # @UndefinedVariable
        startupinfo = STARTUPINFO(dwFlags=startupinfo.dwFlags,
                                  hStdInput=startupinfo.hStdInput,
                                  hStdOutput=startupinfo.hStdOutput,
                                  hStdError=startupinfo.hStdError,
                                  wShowWindow=startupinfo.wShowWindow)

    si, ci, pi = startupinfo, creationinfo, PROCESS_INFORMATION()

    if commandline is None:
        commandline = ci.lpCommandLine

    if commandline is not None:
        if ci.bUseShell:
            si.dwFlags |= STARTF_USESHOWWINDOW
            si.wShowWindow = SW_HIDE
            comspec = os.environ.get("ComSpec", os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe"))
            commandline = f'"{comspec}" /c "{commandline}"'
        log(f"{commandline=!r}")

    dwCreationFlags = ci.dwCreationFlags | CREATE_UNICODE_ENVIRONMENT
    lpEnvironment = create_environment(ci.lpEnvironment)

    if dwCreationFlags & DETACHED_PROCESS and any((
            dwCreationFlags & CREATE_NEW_CONSOLE,
            ci.dwCreationType == CREATION_TYPE_LOGON,
            ci.dwCreationType == CREATION_TYPE_TOKEN,
    )):
        raise RuntimeError('DETACHED_PROCESS is incompatible with '
                           'CREATE_NEW_CONSOLE, which is implied for '
                           'the logon and token creation types')
    if ci.dwCreationType == CREATION_TYPE_NORMAL:
        args = (
            ci.lpApplicationName, commandline,
            ci.lpProcessAttributes, ci.lpThreadAttributes, ci.bInheritHandles,
            dwCreationFlags, lpEnvironment, ci.lpCurrentDirectory,
            si, pi,
        )
        log("CreateProcessW%s", args)
        kernel32.CreateProcessW(*args)
    elif ci.dwCreationType == CREATION_TYPE_LOGON:
        args = (
            ci.lpUsername, ci.lpDomain, ci.lpPassword, ci.dwLogonFlags,
            ci.lpApplicationName, commandline,
            dwCreationFlags, lpEnvironment, ci.lpCurrentDirectory,
            si, pi,
        )
        log("CreateProcessWithLogonW%s", args)
        advapi32.CreateProcessWithLogonW(*args)
    elif ci.dwCreationType == CREATION_TYPE_TOKEN:
        args = (
            int(ci.hToken), ci.dwLogonFlags,
            ci.lpApplicationName, commandline,
            dwCreationFlags, lpEnvironment, ci.lpCurrentDirectory,
            si, pi,
        )
        log("CreateProcessWithTokenW%s", args)
        advapi32.CreateProcessWithTokenW(*args)
    elif ci.dwCreationType == CREATION_TYPE_USER:
        args = (
            int(ci.hToken),
            ci.lpApplicationName, commandline,
            ci.lpProcessAttributes, ci.lpThreadAttributes, ci.bInheritHandles,
            dwCreationFlags, lpEnvironment, ci.lpCurrentDirectory,
            si, pi,
        )
        log("CreateProcessAsUserW%s", args)
        advapi32.CreateProcessAsUserW(*args)
    else:
        raise ValueError('invalid process creation type')

    return pi


class Popen(subprocess.Popen):
    def __init__(self, *args, **kwds):
        ci = self._creationinfo = kwds.pop('creationinfo', CREATIONINFO())
        if kwds.pop('suspended', False):
            ci.dwCreationFlags |= CREATE_SUSPENDED
        self._child_started = False
        super().__init__(*args, **kwds)

    def _execute_child(self, args, executable, preexec_fn, close_fds,
                       pass_fds, cwd, env,
                       startupinfo, creationflags, shell,
                       p2cread, p2cwrite,
                       c2pread, c2pwrite,
                       errread, errwrite,
                       *_extra_args):
        """Execute program (MS Windows version)"""
        assert not pass_fds, "pass_fds not supported on Windows."
        commandline = args if isinstance(args, str) else subprocess.list2cmdline(args)
        self._common_execute_child(executable, commandline, shell,
                                   close_fds, creationflags, env, cwd,
                                   startupinfo, p2cread, c2pwrite, errwrite)

    def _common_execute_child(self, executable, commandline, shell,
                              close_fds, creationflags, env, cwd,
                              startupinfo, p2cread, c2pwrite, errwrite):

        ci = self._creationinfo
        if executable is not None:
            ci.lpApplicationName = executable
        if commandline:
            ci.lpCommandLine = commandline
        if shell:
            ci.bUseShell = shell
        if not close_fds:
            ci.bInheritHandles = int(not close_fds)
        if creationflags:
            ci.dwCreationFlags |= creationflags
        if env is not None:
            ci.lpEnvironment = env
        if cwd is not None:
            ci.lpCurrentDirectory = cwd

        if startupinfo is None:
            startupinfo = STARTUPINFO()
        si = self._startupinfo = startupinfo

        default = -1
        if default not in (p2cread, c2pwrite, errwrite):
            si.dwFlags |= STARTF_USESTDHANDLES
            si.hStdInput = int(p2cread)
            si.hStdOutput = int(c2pwrite)
            si.hStdError = int(errwrite)

        try:
            pi = create_process(creationinfo=ci, startupinfo=si)
        finally:
            if p2cread != -1:
                p2cread.Close()
            if c2pwrite != -1:
                c2pwrite.Close()
            if errwrite != -1:
                errwrite.Close()
            if hasattr(self, '_devnull'):
                os.close(self._devnull)   # pylint: disable=no-member

        if not ci.dwCreationFlags & CREATE_SUSPENDED:
            self._child_started = True

        # Retain the process handle, but close the thread handle
        # if it's no longer needed.
        self._processinfo = pi
        self._handle = pi.hProcess.Detach()
        self.pid = pi.dwProcessId
        if self._child_started:
            pi.hThread.Close()

    def start(self) -> None:
        if self._child_started:
            raise RuntimeError("processes can only be started once")
        hThread = self._processinfo.hThread
        prev_count = kernel32.ResumeThread(hThread)
        if prev_count > 1:
            for _ in range(1, prev_count):
                if kernel32.ResumeThread(hThread) <= 1:
                    break
            else:
                raise RuntimeError('cannot start the main thread')
        # The thread's previous suspend count was 0 or 1,
        # so it should be running now.
        self._child_started = True
        hThread.Close()

    def __del__(self):
        if not self._child_started:
            try:
                if hasattr(self, '_processinfo'):
                    self._processinfo.hThread.Close()
            finally:
                if hasattr(self, '_handle'):
                    self.terminate()
        super().__del__()         # pylint: disable=no-member
