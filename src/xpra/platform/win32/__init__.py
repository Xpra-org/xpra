# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32.

import errno
import os.path
import sys
import ctypes

from xpra.util import envbool
from xpra.os_util import PYTHON2
from ctypes import WINFUNCTYPE, WinDLL, POINTER, byref, c_int
from ctypes.wintypes import BOOL, HANDLE, DWORD, LPWSTR, LPCWSTR, LPVOID, POINT, WORD, SMALL_RECT

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import SetConsoleTitleA, GetConsoleScreenBufferInfo, MessageBoxA, GetLastError, kernel32


GetStdHandle = WINFUNCTYPE(HANDLE, DWORD)(("GetStdHandle", kernel32))
STD_OUTPUT_HANDLE = DWORD(-11)
STD_ERROR_HANDLE = DWORD(-12)
GetFileType = WINFUNCTYPE(DWORD, DWORD)(("GetFileType", kernel32))
FILE_TYPE_CHAR = 0x0002
FILE_TYPE_REMOTE = 0x8000
GetConsoleMode = WINFUNCTYPE(BOOL, HANDLE, POINTER(DWORD))(("GetConsoleMode", kernel32))
INVALID_HANDLE_VALUE = DWORD(-1).value
STDOUT_FILENO = 1
STDERR_FILENO = 2
WriteConsoleW = WINFUNCTYPE(BOOL, HANDLE, LPWSTR, DWORD, POINTER(DWORD), LPVOID)(("WriteConsoleW", kernel32))

GetConsoleCP = kernel32.GetConsoleCP

#redirect output if we're not running from a console:
frozen = getattr(sys, 'frozen', False)
REDIRECT_OUTPUT = envbool("XPRA_REDIRECT_OUTPUT", frozen is True and GetConsoleCP()==0)
if frozen:
    #cx_freeze paths:
    PATH = os.environ.get("PATH", "").split(os.pathsep)
    edir = os.path.dirname(sys.executable)
    def jedir(*paths):
        return os.path.join(*([edir]+list(paths)))
    def addsyspath(*paths):
        v = jedir(*paths)
        if os.path.exists(v):
            if v not in sys.path:
                sys.path.append(v)
            if os.path.isdir(v) and v not in PATH:
                PATH.append(v)
    addsyspath('')
    addsyspath('lib')
    os.environ['GI_TYPELIB_PATH'] = jedir('lib', 'girepository-1.0')
    os.environ["PATH"] = os.pathsep.join(PATH)

#don't know why this breaks with Python 3 yet...
FIX_UNICODE_OUT = envbool("XPRA_FIX_UNICODE_OUT", not REDIRECT_OUTPUT and PYTHON2)


def is_wine():
    try:
        try:
            import _winreg as winreg
        except ImportError:
            import winreg   #@UnresolvedImport @Reimport
        hKey = winreg.OpenKey(win32con.HKEY_LOCAL_MACHINE, r"Software\\Wine")
        return hKey is not None
    except:
        #no wine key, assume not present and wait for input
        pass
    return False


prg_name = "Xpra"
def set_prgname(name):
    global prg_name
    prg_name = name
    try:
        SetConsoleTitleA(name)
        if PYTHON2:
            import glib     #@UnresolvedImport
            glib.set_prgname(name)
    except:
        pass


def fix_unicode_out():
    #code found here:
    #http://stackoverflow.com/a/3259271/428751
    import codecs
    original_stderr = sys.stderr

    # If any exception occurs in this code, we'll probably try to print it on stderr,
    # which makes for frustrating debugging if stderr is directed to our wrapper.
    # So be paranoid about catching errors and reporting them to original_stderr,
    # so that we can at least see them.
    def _complain(message):
        if not isinstance(message, str):
            message = repr(message)
        original_stderr.write("%s\n" % message)

    # Work around <http://bugs.python.org/issue6058>.
    codecs.register(lambda name: codecs.lookup('utf-8') if name == 'cp65001' else None)

    # Make Unicode console output work independently of the current code page.
    # This also fixes <http://bugs.python.org/issue1602>.
    # Credit to Michael Kaplan <http://blogs.msdn.com/b/michkap/archive/2010/04/07/9989346.aspx>
    # and TZOmegaTZIOY
    # <http://stackoverflow.com/questions/878972/windows-cmd-encoding-change-causes-python-crash/1432462#1432462>.
    try:
        # <http://msdn.microsoft.com/en-us/library/ms683231(VS.85).aspx>
        # HANDLE WINAPI GetStdHandle(DWORD nStdHandle);
        # returns INVALID_HANDLE_VALUE, NULL, or a valid handle
        #
        # <http://msdn.microsoft.com/en-us/library/aa364960(VS.85).aspx>
        # DWORD WINAPI GetFileType(DWORD hFile);
        #
        # <http://msdn.microsoft.com/en-us/library/ms683167(VS.85).aspx>
        # BOOL WINAPI GetConsoleMode(HANDLE hConsole, LPDWORD lpMode);

        def not_a_console(handle):
            if handle == INVALID_HANDLE_VALUE or handle is None:
                return True
            return ((GetFileType(handle) & ~FILE_TYPE_REMOTE) != FILE_TYPE_CHAR
                    or GetConsoleMode(handle, byref(DWORD())) == 0)

        old_stdout_fileno = None
        old_stderr_fileno = None
        if hasattr(sys.stdout, 'fileno'):
            old_stdout_fileno = sys.stdout.fileno()
        if hasattr(sys.stderr, 'fileno'):
            old_stderr_fileno = sys.stderr.fileno()

        real_stdout = (old_stdout_fileno == STDOUT_FILENO)
        real_stderr = (old_stderr_fileno == STDERR_FILENO)

        if real_stdout:
            hStdout = GetStdHandle(STD_OUTPUT_HANDLE)
            if not_a_console(hStdout):
                real_stdout = False

        if real_stderr:
            hStderr = GetStdHandle(STD_ERROR_HANDLE)
            if not_a_console(hStderr):
                real_stderr = False

        if real_stdout or real_stderr:
            # BOOL WINAPI WriteConsoleW(HANDLE hOutput, LPWSTR lpBuffer, DWORD nChars,
            #                           LPDWORD lpCharsWritten, LPVOID lpReserved);

            class UnicodeOutput:
                def __init__(self, hConsole, stream, fileno, name):
                    self._hConsole = hConsole
                    self._stream = stream
                    self._fileno = fileno
                    self.closed = False
                    self.softspace = False
                    self.mode = 'w'
                    self.encoding = 'utf-8'
                    self.name = name
                    self.flush()

                def isatty(self):
                    return False

                def close(self):
                    # don't really close the handle, that would only cause problems
                    self.closed = True

                def fileno(self):
                    return self._fileno

                def flush(self):
                    if self._hConsole is None:
                        try:
                            self._stream.flush()
                        except Exception as e:
                            if not self.closed:
                                _complain("%s.flush: %r from %r" % (self.name, e, self._stream))
                                raise

                def write(self, text):
                    try:
                        if self._hConsole is None:
                            if isinstance(text, unicode):
                                text = text.encode('utf-8')
                            self._stream.write(text)
                        else:
                            if not isinstance(text, unicode):
                                text = str(text).decode('utf-8')
                            remaining = len(text)
                            while remaining:
                                n = DWORD(0)
                                # There is a shorter-than-documented limitation on the
                                # length of the string passed to WriteConsoleW (see
                                # <http://tahoe-lafs.org/trac/tahoe-lafs/ticket/1232>.
                                retval = WriteConsoleW(self._hConsole, text, min(remaining, 10000), byref(n), None)
                                if retval == 0 or n.value == 0:
                                    raise IOError("WriteConsoleW returned %r, n.value = %r" % (retval, n.value))
                                remaining -= n.value
                                if not remaining:
                                    break
                                text = text[n.value:]
                    except Exception as e:
                        if not self.closed:
                            _complain("%s.write: %r" % (self.name, e))
                            raise

                def writelines(self, lines):
                    try:
                        for line in lines:
                            self.write(line)
                    except Exception as e:
                        if not self.closed:
                            _complain("%s.writelines: %r" % (self.name, e))
                            raise

            if real_stdout:
                sys.stdout = UnicodeOutput(hStdout, None, STDOUT_FILENO, '<Unicode console stdout>')
            else:
                sys.stdout = UnicodeOutput(None, sys.stdout, old_stdout_fileno, '<Unicode redirected stdout>')

            if real_stderr:
                sys.stderr = UnicodeOutput(hStderr, None, STDERR_FILENO, '<Unicode console stderr>')
            else:
                sys.stderr = UnicodeOutput(None, sys.stderr, old_stderr_fileno, '<Unicode redirected stderr>')
    except Exception as e:
        _complain("exception %r while fixing up sys.stdout and sys.stderr" % (e,))

class COORD(ctypes.Structure):
    _fields_ = [
        ('X', ctypes.c_short),
        ('Y', ctypes.c_short)
        ]

class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize",              COORD),
        ("dwCursorPosition",    COORD),
        ("wAttributes",         WORD),
        ("srWindow",            SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
        ]

_wait_for_input = False
def set_wait_for_input():
    global _wait_for_input
    wfi = os.environ.get("XPRA_WAIT_FOR_INPUT")
    if wfi is not None:
        _wait_for_input = wfi!="0"
        return
    if is_wine():
        #don't wait for input when running under wine
        #(which usually does not popup a new shell window)
        _wait_for_input = False
        return
    if os.environ.get("MSYSCON"):
        #msys environment doesn't popup a new shell window
        _wait_for_input = False
        return
    try:
        handle = GetStdHandle(STD_OUTPUT_HANDLE)
        #handle.SetConsoleTextAttribute(FOREGROUND_BLUE)
        csbi = CONSOLE_SCREEN_BUFFER_INFO()
        GetConsoleScreenBufferInfo(handle, byref(csbi))
        cpos = csbi.dwCursorPosition
        #wait for input if this is a brand new console:
        _wait_for_input = cpos.X==0 and cpos.Y==0
    except:
        e = sys.exc_info()[1]
        code = -1
        try:
            code = e.winerror
        except:
            pass
        if code==errno.ENXIO:
            #ignore "no device" errors silently
            #(ie: happens if you redirect the command to a file)
            #we could also re-use the code above from "not_a_console()"
            pass
        else:
            try:
                print("error accessing console %s: %s" % (errno.errorcode.get(e.errno, e.errno), e))
            except:
                print("error accessing console: %s" % e)

def do_init():
    if FIX_UNICODE_OUT:
        fix_unicode_out()
    if not REDIRECT_OUTPUT:
        #figure out if we want to wait for input at the end:
        set_wait_for_input()
        return
    from xpra.platform import get_prgname
    LOG_FILENAME = (get_prgname() or "Xpra")+".log"
    from xpra.platform.win32.paths import _get_data_dir
    d = _get_data_dir()
    log_file = os.path.join(d, LOG_FILENAME)
    sys.stdout = open(log_file, "a")
    sys.stderr = sys.stdout


MB_ICONEXCLAMATION  = 0x00000030
MB_ICONINFORMATION  = 0x00000040
MB_SYSTEMMODAL      = 0x00001000
def _show_message(message, uType):
    global prg_name
    #TODO: detect cx_freeze equivallent
    SHOW_MESSAGEBOX = envbool("XPRA_MESSAGEBOX", True)
    if SHOW_MESSAGEBOX and REDIRECT_OUTPUT:
        #try to use an alert box since no console output will be shown:
        try:
            MessageBoxA(0, message, prg_name, uType)
            return
        except:
            pass
    print(message)

def command_info(message):
    _show_message(message, MB_ICONINFORMATION | MB_SYSTEMMODAL)

def command_error(message):
    _show_message(message, MB_ICONEXCLAMATION | MB_SYSTEMMODAL)


def get_main_fallback(cmd):
    set_wait_for_input()
    global _wait_for_input
    if _wait_for_input:
        #something will be shown in a console,
        #so don't bother showing anything else
        return None
    if cmd.find("Xpra_Audio.exe")>=0:
        #don't show the launcher when trying to use this command
        return None
    #try the launcher (better than nothing!)
    try:
        from xpra.client.gtk_base.client_launcher import main
        return main
    except:
        return None


def do_clean():
    global _wait_for_input
    if _wait_for_input:
        print("\nPress Enter to close")
        try:
            sys.stdout.flush()
        except:
            pass
        try:
            sys.stderr.flush()
        except:
            pass
        sys.stdin.readline()
