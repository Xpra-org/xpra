# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32.
#pylint: disable=bare-except
#pylint: disable=import-outside-toplevel

import sys
import errno
import os.path
import ctypes
from ctypes import WINFUNCTYPE, WinDLL, POINTER, byref, c_int, wintypes, create_unicode_buffer  # @UnresolvedImport
from ctypes.wintypes import BOOL, HANDLE, DWORD, LPWSTR, LPCWSTR, LPVOID, POINT, WORD, SMALL_RECT
from typing import Union

from xpra.util import envbool, noerr
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import (
    GetStdHandle,
    SetConsoleTitleA, GetConsoleScreenBufferInfo,
    MessageBoxA, GetLastError, kernel32,
    )


if not sys.platform.startswith("win"):
    raise ImportError("not to be used on %s" % sys.platform)

STD_INPUT_HANDLE = DWORD(-10)
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

GetConsoleCP = kernel32.GetConsoleCP  # @UndefinedVariable

#redirect output if we're not running from a console:
FIX_UNICODE_OUT = False
FROZEN = getattr(sys, "frozen", None) in ("windows_exe", "console_exe", True)
REDIRECT_OUTPUT = envbool("XPRA_REDIRECT_OUTPUT", FROZEN and GetConsoleCP()==0)
if not REDIRECT_OUTPUT:
    #don't know why this breaks with Python 3 yet...
    FIX_UNICODE_OUT = envbool("XPRA_FIX_UNICODE_OUT", False)


def is_wine():
    try:
        import winreg   #@UnresolvedImport @Reimport
        hKey = winreg.OpenKey(win32con.HKEY_LOCAL_MACHINE, r"Software\\Wine")   #@UndefinedVariable
        return bool(hKey)
    except Exception:
        #no wine key, assume not present and wait for input
        pass
    return False


def get_csidl_folder(csidl):
    try:
        buf = create_unicode_buffer(wintypes.MAX_PATH)
        shell32 = WinDLL("shell32", use_last_error=True)
        SHGetFolderPath = shell32.SHGetFolderPathW
        SHGetFolderPath(0, csidl, None, 0, buf)
        return os.path.normpath(buf.value)
    except Exception:
        return None

def get_common_startmenu_dir():
    CSIDL_COMMON_STARTMENU = 0x16
    return get_csidl_folder(CSIDL_COMMON_STARTMENU)

def get_startmenu_dir():
    CSIDL_STARTMENU = 0xb
    return get_csidl_folder(CSIDL_STARTMENU)

def get_commonappdata_dir():
    CSIDL_COMMON_APPDATA = 35
    return get_csidl_folder(CSIDL_COMMON_APPDATA)


prg_name = "Xpra"
def set_prgname(name):
    global prg_name
    prg_name = name
    try:
        SetConsoleTitleA(name.encode("latin1"))
    except Exception:
        pass

def not_a_console(handle):
    if handle == INVALID_HANDLE_VALUE or handle is None:
        return True
    return ((GetFileType(handle) & ~FILE_TYPE_REMOTE) != FILE_TYPE_CHAR
            or GetConsoleMode(handle, byref(DWORD())) == 0)

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

        old_stdout_fileno = None
        old_stderr_fileno = None
        if hasattr(sys.stdout, 'fileno'):
            old_stdout_fileno = sys.stdout.fileno()
        if hasattr(sys.stderr, 'fileno'):
            old_stderr_fileno = sys.stderr.fileno()

        real_stdout = (old_stdout_fileno == STDOUT_FILENO)
        real_stderr = (old_stderr_fileno == STDERR_FILENO)
        hStdout = hStderr = 0

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

                def write(self, value:Union[str,bytes]):
                    try:
                        if self._hConsole is None:
                            if isinstance(value, str):
                                self._stream.write(value.encode('utf-8'))
                            else:
                                self._stream.write(value)
                        else:
                            if isinstance(value, str):
                                text = str(value)
                            else:
                                text = value.decode('utf-8')
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

def get_console_position(handle):
    try:
        #handle.SetConsoleTextAttribute(FOREGROUND_BLUE)
        csbi = CONSOLE_SCREEN_BUFFER_INFO()
        GetConsoleScreenBufferInfo(handle, byref(csbi))
        cpos = csbi.dwCursorPosition
        #wait for input if this is a brand-new console:
        return cpos.X, cpos.Y
    except Exception:
        e = sys.exc_info()[1]
        code = -1
        try:
            code = e.winerror
        except AttributeError:
            pass
        if code==errno.ENXIO:
            #ignore "no device" errors silently
            #(ie: happens if you redirect the command to a file)
            #we could also re-use the code above from "not_a_console()"
            pass
        else:
            from xpra.log import Logger
            log = Logger("win32")
            try:
                log.error("Error accessing console %s: %s" % (
                    errno.errorcode.get(e.errno, e.errno), e))
            except Exception:
                log.error(f"Error accessing console: {e}")
        return -1, -1

_wait_for_input = False
def set_wait_for_input():
    global _wait_for_input
    _wait_for_input = should_wait_for_input()

def should_wait_for_input():
    wfi = os.environ.get("XPRA_WAIT_FOR_INPUT")
    if wfi is not None:
        return wfi!="0"
    if is_wine():
        # don't wait for input when running under wine
        # (which usually does not pop up a new shell window)
        return False
    if os.environ.get("TERM", "")=="xterm":
        # msys, cygwin and git bash environments don't pop up a new shell window,
        # and they all set TERM=xterm
        return False
    handle = GetStdHandle(STD_OUTPUT_HANDLE)
    if not_a_console(handle):
        return False
    #wait for input if this is a brand-new console:
    return get_console_position(handle)==(0, 0)


def setup_console_event_listener(handler, enable):
    from xpra.log import Logger
    log = Logger("win32")
    try:
        from xpra.platform.win32.common import SetConsoleCtrlHandler, ConsoleCtrlHandler
        log("calling SetConsoleCtrlHandler(%s, %s)", handler, enable)
        ctypes_handler = ConsoleCtrlHandler(handler)
        result = SetConsoleCtrlHandler(ctypes_handler, enable)
        log("SetConsoleCtrlHandler(%s, %s)=%s", handler, enable, result)
        if result==0:
            log.error("Error: could not %s console control handler:", "set" if enable else "unset")
            log.error(" SetConsoleCtrlHandler: %r", ctypes.GetLastError())  # @UndefinedVariable
            return False
        return True
    except Exception as e:
        log.error("SetConsoleCtrlHandler error: %s", e)
        return False

def do_init():
    if FIX_UNICODE_OUT:
        fix_unicode_out()

    if not REDIRECT_OUTPUT:
        #figure out if we want to wait for input at the end:
        set_wait_for_input()

    def datadir() -> str:
        from xpra.platform.win32.paths import get_appdata_dir
        appdatadir = get_appdata_dir(False)
        if not os.path.exists(appdatadir):
            os.mkdir(appdatadir)
        return appdatadir

    if FROZEN:
        if envbool("PYTHONDONTWRITEBYTECODE", False):
            sys.dont_write_bytecode = True
        if not os.environ.get("PYTHONPYCACHEPREFIX"):
            sys.pycache_prefix = os.path.join(datadir(), "pycache-%i.%i" % (sys.version_info[:2]))

    if envbool("XPRA_LOG_TO_FILE", True):
        log_filename = os.environ.get("XPRA_LOG_FILENAME")
        if not log_filename:
            from xpra.platform import get_prgname
            log_filename = os.path.join(datadir(), (get_prgname() or "Xpra")+".log")
        sys.stdout = open(log_filename, "a", encoding="utf8")
        sys.stderr = sys.stdout
        os.environ["XPRA_LOG_FILENAME"] = log_filename


def do_init_env():
    from xpra.platform import init_env_common
    init_env_common()
    if os.environ.get("CRYPTOGRAPHY_OPENSSL_NO_LEGACY") is None:
        os.environ["CRYPTOGRAPHY_OPENSSL_NO_LEGACY"] = "1"
    if os.environ.get("GDK_WIN32_DISABLE_HIDPI") is None:
        os.environ["GDK_WIN32_DISABLE_HIDPI"] = "1"
    if FROZEN:
        #cx_freeze paths:
        PATH = os.environ.get("PATH", "").split(os.pathsep)
        edir = os.path.abspath(os.path.dirname(sys.executable))
        libdir = os.path.join(edir, "lib")
        for d in (libdir, edir):
            if not os.path.exists(d) or not os.path.isdir(d):
                continue
            try:
                sys.path.remove(d)
            except ValueError:
                pass
            sys.path.insert(0, d)
            try:
                PATH.remove(d)
            except ValueError:
                pass
            PATH.insert(0, d)
        #CUDA:
        if not os.environ.get("CUDA_PATH"):
            os.environ["CUDA_PATH"] = edir
        #Gtk and gi:
        os.environ['GI_TYPELIB_PATH'] = os.path.join(libdir, "girepository-1.0")
        os.environ["PATH"] = os.pathsep.join(PATH)
        if not os.environ.get("GTK_THEME") and not os.environ.get("GTK_DEBUG"):
            for theme in ("Windows-10", "win32"):
                tdir = os.path.join(edir, "share", "themes", theme)
                if os.path.exists(tdir):
                    os.environ["GTK_THEME"] = theme
                    break
        #GStreamer's plugins:
        gst_dir = os.path.join(libdir, "gstreamer-1.0")   #ie: C:\Program Files\Xpra\lib\gstreamer-1.0
        os.environ["GST_PLUGIN_PATH"] = gst_dir


MB_ICONEXCLAMATION  = 0x00000030
MB_ICONINFORMATION  = 0x00000040
MB_SYSTEMMODAL      = 0x00001000
def _show_message(message, uType):
    #TODO: detect cx_freeze equivallent
    SHOW_MESSAGEBOX = envbool("XPRA_MESSAGEBOX", REDIRECT_OUTPUT)
    from xpra.log import Logger
    log = Logger("win32")
    if SHOW_MESSAGEBOX:
        #try to use an alert box since no console output will be shown:
        try:
            MessageBoxA(0, message.encode(), prg_name.encode(), uType)
            return
        except Exception as e:
            log.error(f"Error: cannot show alert box: {e}")
    log.info(message)

def command_info(message):
    _show_message(message, MB_ICONINFORMATION | MB_SYSTEMMODAL)

def command_error(message):
    _show_message(message, MB_ICONEXCLAMATION | MB_SYSTEMMODAL)


def do_clean():
    if _wait_for_input:
        print("\nPress Enter to close")
        try:
            sys.stdout.flush()
        except IOError:
            pass
        try:
            sys.stderr.flush()
        except IOError:
            pass
        sys.stdin.readline()
        return
    # undo the redirect to file:
    if REDIRECT_OUTPUT and envbool("XPRA_LOG_TO_FILE", True):
        log_filename = os.environ.get("XPRA_LOG_FILENAME")
        if log_filename and os.path.exists(log_filename):
            noerr(sys.stdout.close)
            sys.stdout = sys.stderr = None

