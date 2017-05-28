#!/usr/bin/env python
# This file is part of Xpra.
# This code is released under the terms of the CC-BY-SA license:
# https://creativecommons.org/licenses/by-sa/2.0/legalcode
# This subprocess.Popen code was found here:
# https://stackoverflow.com/questions/29566330/

import os
import sys
import types
import ctypes
import subprocess

from ctypes import wintypes

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)

ERROR_INVALID_HANDLE = 0x0006
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
INVALID_DWORD_VALUE = wintypes.DWORD(-1).value

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
SW_SHOWDEFAULT     = 10 # ~STARTUPINFO
SW_FORCEMINIMIZE   = 11

LOGON_WITH_PROFILE        = 0x00000001
LOGON_NETCREDENTIALS_ONLY = 0x00000002

STD_INPUT_HANDLE  = wintypes.DWORD(-10).value
STD_OUTPUT_HANDLE = wintypes.DWORD(-11).value
STD_ERROR_HANDLE  = wintypes.DWORD(-12).value

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

class PROCESS_INFORMATION(ctypes.Structure):
    """https://msdn.microsoft.com/en-us/library/ms684873"""
    __slots__ = '_cached_hProcess', '_cached_hThread'

    _fields_ = (('_hProcess',   HANDLE),
                ('_hThread',    HANDLE),
                ('dwProcessId', wintypes.DWORD),
                ('dwThreadId',  wintypes.DWORD))

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

LPPROCESS_INFORMATION = ctypes.POINTER(PROCESS_INFORMATION)

LPBYTE = ctypes.POINTER(wintypes.BYTE)

class STARTUPINFO(ctypes.Structure):
    """https://msdn.microsoft.com/en-us/library/ms686331"""
    _fields_ = (('cb',              wintypes.DWORD),
                ('lpReserved',      wintypes.LPWSTR),
                ('lpDesktop',       wintypes.LPWSTR),
                ('lpTitle',         wintypes.LPWSTR),
                ('dwX',             wintypes.DWORD),
                ('dwY',             wintypes.DWORD),
                ('dwXSize',         wintypes.DWORD),
                ('dwYSize',         wintypes.DWORD),
                ('dwXCountChars',   wintypes.DWORD),
                ('dwYCountChars',   wintypes.DWORD),
                ('dwFillAttribute', wintypes.DWORD),
                ('dwFlags',         wintypes.DWORD),
                ('wShowWindow',     wintypes.WORD),
                ('cbReserved2',     wintypes.WORD),
                ('lpReserved2',     LPBYTE),
                ('hStdInput',       wintypes.HANDLE),
                ('hStdOutput',      wintypes.HANDLE),
                ('hStdError',       wintypes.HANDLE))

    def __init__(self, **kwds):
        self.cb = ctypes.sizeof(self)
        super(STARTUPINFO, self).__init__(**kwds)

class PROC_THREAD_ATTRIBUTE_LIST(ctypes.Structure):
    pass

PPROC_THREAD_ATTRIBUTE_LIST = ctypes.POINTER(PROC_THREAD_ATTRIBUTE_LIST)

class STARTUPINFOEX(STARTUPINFO):
    _fields_ = (('lpAttributeList', PPROC_THREAD_ATTRIBUTE_LIST),)

LPSTARTUPINFO = ctypes.POINTER(STARTUPINFO)
LPSTARTUPINFOEX = ctypes.POINTER(STARTUPINFOEX)

class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = (('nLength',              wintypes.DWORD),
                ('lpSecurityDescriptor', wintypes.LPVOID),
                ('bInheritHandle',       wintypes.BOOL))
    def __init__(self, **kwds):
        self.nLength = ctypes.sizeof(self)
        super(SECURITY_ATTRIBUTES, self).__init__(**kwds)

LPSECURITY_ATTRIBUTES = ctypes.POINTER(SECURITY_ATTRIBUTES)

class HANDLE_IHV(HANDLE):
    pass

class DWORD_IDV(wintypes.DWORD):
    pass

def _check_ihv(result, func, args):
    if result.value == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return result.value

def _check_idv(result, func, args):
    if result.value == INVALID_DWORD_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return result.value

def _check_bool(result, func, args):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return args

def WIN(func, restype, *argtypes):
    func.restype = restype
    func.argtypes = argtypes
    if issubclass(restype, HANDLE_IHV):
        func.errcheck = _check_ihv
    elif issubclass(restype, DWORD_IDV):
        func.errcheck = _check_idv
    else:
        func.errcheck = _check_bool

# https://msdn.microsoft.com/en-us/library/ms724211
WIN(kernel32.CloseHandle, wintypes.BOOL,
    wintypes.HANDLE,) # _In_ HANDLE hObject

# https://msdn.microsoft.com/en-us/library/ms685086
WIN(kernel32.ResumeThread, DWORD_IDV,
    wintypes.HANDLE,) # _In_ hThread

# https://msdn.microsoft.com/en-us/library/ms682425
WIN(kernel32.CreateProcessW, wintypes.BOOL,
    wintypes.LPCWSTR,       # _In_opt_    lpApplicationName
    wintypes.LPWSTR,        # _Inout_opt_ lpCommandLine
    LPSECURITY_ATTRIBUTES,  # _In_opt_    lpProcessAttributes
    LPSECURITY_ATTRIBUTES,  # _In_opt_    lpThreadAttributes
    wintypes.BOOL,          # _In_        bInheritHandles
    wintypes.DWORD,         # _In_        dwCreationFlags
    wintypes.LPCWSTR,       # _In_opt_    lpEnvironment
    wintypes.LPCWSTR,       # _In_opt_    lpCurrentDirectory
    LPSTARTUPINFO,          # _In_        lpStartupInfo
    LPPROCESS_INFORMATION)  # _Out_       lpProcessInformation

# https://msdn.microsoft.com/en-us/library/ms682429
WIN(advapi32.CreateProcessAsUserW, wintypes.BOOL,
    wintypes.HANDLE,        # _In_opt_    hToken
    wintypes.LPCWSTR,       # _In_opt_    lpApplicationName
    wintypes.LPWSTR,        # _Inout_opt_ lpCommandLine
    LPSECURITY_ATTRIBUTES,  # _In_opt_    lpProcessAttributes
    LPSECURITY_ATTRIBUTES,  # _In_opt_    lpThreadAttributes
    wintypes.BOOL,          # _In_        bInheritHandles
    wintypes.DWORD,         # _In_        dwCreationFlags
    wintypes.LPCWSTR,       # _In_opt_    lpEnvironment
    wintypes.LPCWSTR,       # _In_opt_    lpCurrentDirectory
    LPSTARTUPINFO,          # _In_        lpStartupInfo
    LPPROCESS_INFORMATION)  # _Out_       lpProcessInformation

# https://msdn.microsoft.com/en-us/library/ms682434
WIN(advapi32.CreateProcessWithTokenW, wintypes.BOOL,
    wintypes.HANDLE,        # _In_        hToken
    wintypes.DWORD,         # _In_        dwLogonFlags
    wintypes.LPCWSTR,       # _In_opt_    lpApplicationName
    wintypes.LPWSTR,        # _Inout_opt_ lpCommandLine
    wintypes.DWORD,         # _In_        dwCreationFlags
    wintypes.LPCWSTR,       # _In_opt_    lpEnvironment
    wintypes.LPCWSTR,       # _In_opt_    lpCurrentDirectory
    LPSTARTUPINFO,          # _In_        lpStartupInfo
    LPPROCESS_INFORMATION)  # _Out_       lpProcessInformation

# https://msdn.microsoft.com/en-us/library/ms682431
WIN(advapi32.CreateProcessWithLogonW, wintypes.BOOL,
    wintypes.LPCWSTR,       # _In_        lpUsername
    wintypes.LPCWSTR,       # _In_opt_    lpDomain
    wintypes.LPCWSTR,       # _In_        lpPassword
    wintypes.DWORD,         # _In_        dwLogonFlags
    wintypes.LPCWSTR,       # _In_opt_    lpApplicationName
    wintypes.LPWSTR,        # _Inout_opt_ lpCommandLine
    wintypes.DWORD,         # _In_        dwCreationFlags
    wintypes.LPCWSTR,       # _In_opt_    lpEnvironment
    wintypes.LPCWSTR,       # _In_opt_    lpCurrentDirectory
    LPSTARTUPINFO,          # _In_        lpStartupInfo
    LPPROCESS_INFORMATION)  # _Out_       lpProcessInformation


CREATION_TYPE_NORMAL = 0
CREATION_TYPE_LOGON  = 1
CREATION_TYPE_TOKEN  = 2
CREATION_TYPE_USER   = 3

class CREATIONINFO(object):
    __slots__ = ('dwCreationType',
        'lpApplicationName', 'lpCommandLine', 'bUseShell',
        'lpProcessAttributes', 'lpThreadAttributes', 'bInheritHandles',
        'dwCreationFlags', 'lpEnvironment', 'lpCurrentDirectory',
        'hToken', 'lpUsername', 'lpDomain', 'lpPassword', 'dwLogonFlags')

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

def create_environment(environ):
    if environ is not None:
        items = ['%s=%s' % (k, environ[k]) for k in sorted(environ)]
        buf = '\x00'.join(items)
        length = len(buf) + 2 if buf else 1
        return ctypes.create_unicode_buffer(buf, length)

def create_process(commandline=None, creationinfo=None, startupinfo=None):
    if creationinfo is None:
        creationinfo = CREATIONINFO()

    if startupinfo is None:
        startupinfo = STARTUPINFO()
    elif isinstance(startupinfo, subprocess.STARTUPINFO):
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
            comspec = os.environ.get("ComSpec", os.path.join(
                        os.environ["SystemRoot"], "System32", "cmd.exe"))
            commandline = '"{}" /c "{}"'.format(comspec, commandline)
        commandline = ctypes.create_unicode_buffer(commandline)

    dwCreationFlags = ci.dwCreationFlags | CREATE_UNICODE_ENVIRONMENT
    lpEnvironment = create_environment(ci.lpEnvironment)

    if (dwCreationFlags & DETACHED_PROCESS and
       ((dwCreationFlags & CREATE_NEW_CONSOLE) or
        (ci.dwCreationType == CREATION_TYPE_LOGON) or
        (ci.dwCreationType == CREATION_TYPE_TOKEN))):
        raise RuntimeError('DETACHED_PROCESS is incompatible with '
                           'CREATE_NEW_CONSOLE, which is implied for '
                           'the logon and token creation types')

    if ci.dwCreationType == CREATION_TYPE_NORMAL:

        kernel32.CreateProcessW(
            ci.lpApplicationName, commandline,
            ci.lpProcessAttributes, ci.lpThreadAttributes, ci.bInheritHandles,
            dwCreationFlags, lpEnvironment, ci.lpCurrentDirectory,
            ctypes.byref(si), ctypes.byref(pi))

    elif ci.dwCreationType == CREATION_TYPE_LOGON:

        advapi32.CreateProcessWithLogonW(
            ci.lpUsername, ci.lpDomain, ci.lpPassword, ci.dwLogonFlags,
            ci.lpApplicationName, commandline,
            dwCreationFlags, lpEnvironment, ci.lpCurrentDirectory,
            ctypes.byref(si), ctypes.byref(pi))

    elif ci.dwCreationType == CREATION_TYPE_TOKEN:

        advapi32.CreateProcessWithTokenW(
            ci.hToken, ci.dwLogonFlags,
            ci.lpApplicationName, commandline,
            dwCreationFlags, lpEnvironment, ci.lpCurrentDirectory,
            ctypes.byref(si), ctypes.byref(pi))

    elif ci.dwCreationType == CREATION_TYPE_USER:

        advapi32.CreateProcessAsUserW(
            ci.hToken,
            ci.lpApplicationName, commandline,
            ci.lpProcessAttributes, ci.lpThreadAttributes, ci.bInheritHandles,
            dwCreationFlags, lpEnvironment, ci.lpCurrentDirectory,
            ctypes.byref(si), ctypes.byref(pi))

    else:
        raise ValueError('invalid process creation type')

    return pi


class Popen(subprocess.Popen):
    def __init__(self, *args, **kwds):
        ci = self._creationinfo = kwds.pop('creationinfo', CREATIONINFO())
        if kwds.pop('suspended', False):
            ci.dwCreationFlags |= CREATE_SUSPENDED
        self._child_started = False
        super(Popen, self).__init__(*args, **kwds)

    if sys.version_info[0] == 2:

        def _execute_child(self, args, executable, preexec_fn, close_fds,
                           cwd, env, universal_newlines, startupinfo,
                           creationflags, shell, to_close, p2cread, p2cwrite,
                           c2pread, c2pwrite, errread, errwrite):
            """Execute program (MS Windows version)"""
            commandline = (args if isinstance(args, types.StringTypes) else
                           subprocess.list2cmdline(args))
            self._common_execute_child(executable, commandline, shell, 
                    close_fds, creationflags, env, cwd,
                    startupinfo, p2cread, c2pwrite, errwrite, to_close)
    else:

        def _execute_child(self, args, executable, preexec_fn, close_fds,
                           pass_fds, cwd, env, startupinfo, creationflags,
                           shell, p2cread, p2cwrite, c2pread, c2pwrite, errread,
                           errwrite, restore_signals, start_new_session):
            """Execute program (MS Windows version)"""
            assert not pass_fds, "pass_fds not supported on Windows."
            commandline = (args if isinstance(args, str) else
                           subprocess.list2cmdline(args))
            self._common_execute_child(executable, commandline, shell, 
                    close_fds, creationflags, env, cwd,
                    startupinfo, p2cread, c2pwrite, errwrite)

    def _common_execute_child(self, executable, commandline, shell,
                              close_fds, creationflags, env, cwd,
                              startupinfo, p2cread, c2pwrite, errwrite,
                              to_close=()):

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

        default = None if sys.version_info[0] == 2 else -1
        if default not in (p2cread, c2pwrite, errwrite):
            si.dwFlags |= STARTF_USESTDHANDLES
            si.hStdInput  = int( p2cread)
            si.hStdOutput = int(c2pwrite)
            si.hStdError  = int(errwrite)

        try:
            pi = create_process(creationinfo=ci, startupinfo=si)
        finally:
            if sys.version_info[0] == 2:
                if p2cread is not None:
                    p2cread.Close()
                    to_close.remove(p2cread)
                if c2pwrite is not None:
                    c2pwrite.Close()
                    to_close.remove(c2pwrite)
                if errwrite is not None:
                    errwrite.Close()
                    to_close.remove(errwrite)
            else:
                if p2cread != -1:
                    p2cread.Close()
                if c2pwrite != -1:
                    c2pwrite.Close()
                if errwrite != -1:
                    errwrite.Close()
                if hasattr(self, '_devnull'):
                    os.close(self._devnull)

        if not ci.dwCreationFlags & CREATE_SUSPENDED:
            self._child_started = True

        # Retain the process handle, but close the thread handle
        # if it's no longer needed.
        self._processinfo = pi
        self._handle = pi.hProcess.Detach()
        self.pid = pi.dwProcessId
        if self._child_started:
            pi.hThread.Close()

    def start(self):
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
        super(Popen, self).__del__()
