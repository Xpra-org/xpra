# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32.
# pylint: disable=bare-except
# pylint: disable=import-outside-toplevel

import sys
import errno
import os.path
import ctypes
from ctypes import WINFUNCTYPE, WinDLL, POINTER, byref, wintypes, create_unicode_buffer  # @UnresolvedImport
from ctypes.wintypes import BOOL, HANDLE, DWORD, LPWSTR, LPVOID, WORD, SMALL_RECT

from xpra.util.env import envbool
from xpra.common import noerr
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

CSIDL_COMMON_STARTMENU = 0x16
CSIDL_STARTMENU = 0xb
CSIDL_COMMON_APPDATA = 35

GetConsoleCP = kernel32.GetConsoleCP  # @UndefinedVariable

# redirect output if we're not running from a console:
FROZEN: bool = getattr(sys, "frozen", None) in ("windows_exe", "console_exe", True)
REDIRECT_OUTPUT: bool = envbool("XPRA_REDIRECT_OUTPUT", FROZEN and GetConsoleCP() == 0)


def is_wine() -> bool:
    try:
        import winreg
        h_key = winreg.OpenKey(win32con.HKEY_LOCAL_MACHINE, r"Software\\Wine")
        return bool(h_key)
    except OSError:
        # no wine key, assume not present and wait for input
        pass
    return False


def get_csidl_folder(csidl: int) -> str:
    try:
        buf = create_unicode_buffer(wintypes.MAX_PATH)
        shell32 = WinDLL("shell32", use_last_error=True)
        get_folder_path = shell32.SHGetFolderPathW
        get_folder_path(0, csidl, None, 0, buf)
        return os.path.normpath(buf.value)
    except OSError:
        return ""


def get_common_startmenu_dir() -> str:
    return get_csidl_folder(CSIDL_COMMON_STARTMENU)


def get_startmenu_dir() -> str:
    return get_csidl_folder(CSIDL_STARTMENU)


def get_commonappdata_dir() -> str:
    return get_csidl_folder(CSIDL_COMMON_APPDATA)


prg_name = "Xpra"


def set_prgname(name: str) -> None:
    global prg_name
    prg_name = name
    try:
        SetConsoleTitleA(name.encode("latin1"))
    except OSError:
        pass


def not_a_console(handle: int) -> bool:
    if handle == INVALID_HANDLE_VALUE or handle is None:
        return True
    if (GetFileType(handle) & ~FILE_TYPE_REMOTE) != FILE_TYPE_CHAR:
        return True
    return GetConsoleMode(handle, byref(DWORD())) == 0


class COORD(ctypes.Structure):
    _fields_ = [
        ('X', ctypes.c_short),
        ('Y', ctypes.c_short)
    ]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", WORD),
        ("srWindow", SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


def get_console_position() -> tuple[int, int]:
    try:
        handle = GetStdHandle(STD_OUTPUT_HANDLE)
        if not_a_console(handle):
            return -1, -1
        # handle.SetConsoleTextAttribute(FOREGROUND_BLUE)
        csbi = CONSOLE_SCREEN_BUFFER_INFO()
        GetConsoleScreenBufferInfo(handle, byref(csbi))
        cpos = csbi.dwCursorPosition
        # wait for input if this is a brand-new console:
        return cpos.X, cpos.Y
    except Exception:
        e = sys.exc_info()[1]
        code = -1
        try:
            code = e.winerror
        except AttributeError:
            pass
        if code == errno.ENXIO:
            # ignore "no device" errors silently
            # (ie: happens if you redirect the command to a file)
            # we could also re-use the code above from "not_a_console()"
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


initial_console_position = get_console_position()
_wait_for_input = False


def should_wait_for_input() -> bool:
    wfi = os.environ.get("XPRA_WAIT_FOR_INPUT", "")
    if wfi:
        return wfi != "0"
    if is_wine():
        # don't wait for input when running under wine
        # (which usually does not pop up a new shell window)
        return False
    if os.environ.get("TERM", "") == "xterm":
        # msys, cygwin and git bash environments don't pop up a new shell window,
        # and they all set TERM=xterm
        return False
    handle = GetStdHandle(STD_OUTPUT_HANDLE)
    if not_a_console(handle):
        return False
    # wait for input if this is a brand-new console:
    return initial_console_position == (0, 0)


def is_terminal() -> bool:
    if os.environ.get("TERM", "") == "xterm":
        return True
    handle = GetStdHandle(STD_OUTPUT_HANDLE)
    if not_a_console(handle):
        return False
    # wait for input if this is a brand-new console:
    return initial_console_position != (-1, -1)


def setup_console_event_listener(handler, enable: bool) -> bool:
    from xpra.log import Logger
    log = Logger("win32")
    try:
        from xpra.platform.win32.common import SetConsoleCtrlHandler, ConsoleCtrlHandler
        log("calling SetConsoleCtrlHandler(%s, %s)", handler, enable)
        ctypes_handler = ConsoleCtrlHandler(handler)
        result = SetConsoleCtrlHandler(ctypes_handler, enable)
        log("SetConsoleCtrlHandler(%s, %s)=%s", handler, enable, result)
        if result == 0:
            log.error("Error: could not %s console control handler:", "set" if enable else "unset")
            log.error(" SetConsoleCtrlHandler: %r", GetLastError())
            return False
        return True
    except Exception as e:
        log.error("SetConsoleCtrlHandler error: %s", e)
        return False


def do_init() -> None:
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
            sys.pycache_prefix = os.path.join(datadir(), "pycache-%i.%i" % (sys.version_info[0], sys.version_info[1]))

    global _wait_for_input

    if not REDIRECT_OUTPUT or is_terminal():
        # figure out if we want to wait for input at the end:
        _wait_for_input = should_wait_for_input()
        return

    if envbool("XPRA_LOG_TO_FILE", True):
        log_filename = os.environ.get("XPRA_LOG_FILENAME", "")
        if not log_filename:
            from xpra.platform import get_prgname
            log_filename = (get_prgname() or "Xpra") + ".log"
        if not os.path.isabs(log_filename):
            log_filename = os.path.join(datadir(), log_filename)
        sys.stdout = open(log_filename, "a", encoding="utf8")
        sys.stderr = sys.stdout
        os.environ["XPRA_LOG_FILENAME"] = log_filename
        _wait_for_input = False


def do_init_env() -> None:
    from xpra.platform import init_env_common
    init_env_common()
    if os.environ.get("CRYPTOGRAPHY_OPENSSL_NO_LEGACY") is None:
        os.environ["CRYPTOGRAPHY_OPENSSL_NO_LEGACY"] = "1"
    # if os.environ.get("GDK_WIN32_DISABLE_HIDPI") is None:
    #    os.environ["GDK_WIN32_DISABLE_HIDPI"] = "1"
    #    os.environ["GDK_WIN32_PER_MONITOR_HIDPI"] = "1"
    if FROZEN:
        # cx_freeze paths:
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
        # CUDA:
        if not os.environ.get("CUDA_PATH"):
            os.environ["CUDA_PATH"] = edir
        # Gtk and gi:
        os.environ['GI_TYPELIB_PATH'] = os.path.join(libdir, "girepository-1.0")
        os.environ["PATH"] = os.pathsep.join(PATH)
        if not os.environ.get("GTK_THEME") and not os.environ.get("GTK_DEBUG"):
            for theme in ("Windows-10", "win32"):
                tdir = os.path.join(edir, "share", "themes", theme)
                if os.path.exists(tdir):
                    os.environ["GTK_THEME"] = theme
                    break
        # GStreamer's plugins:
        gst_dir = os.path.join(libdir, "gstreamer-1.0")   # ie: C:\Program Files\Xpra\lib\gstreamer-1.0
        os.environ["GST_PLUGIN_PATH"] = gst_dir


MB_ICONEXCLAMATION = 0x00000030
MB_ICONINFORMATION = 0x00000040
MB_SYSTEMMODAL = 0x00001000


def _show_message(message: str, utype) -> None:
    # TODO: detect cx_freeze equivalent
    show_messagebox = envbool("XPRA_MESSAGEBOX", REDIRECT_OUTPUT)
    from xpra.log import Logger
    log = Logger("win32")
    if show_messagebox:
        # try to use an alert box since no console output will be shown:
        try:
            MessageBoxA(0, message.encode(), prg_name.encode(), utype)
            return
        except Exception as e:
            log.error(f"Error: cannot show alert box: {e}")
    log.info(message)


def command_info(message) -> None:
    _show_message(message, MB_ICONINFORMATION | MB_SYSTEMMODAL)


def command_error(message) -> None:
    _show_message(message, MB_ICONEXCLAMATION | MB_SYSTEMMODAL)


os_name = ""


def threaded_server_init() -> None:
    from xpra.log import Logger
    log = Logger("win32")
    try:
        import wmi
    except ImportError:
        log("threaded_server_init()", exc_info=True)
        return
    try:
        computer = wmi.WMI()
        os_info = computer.Win32_OperatingSystem()[0]
        global os_name
        os_name = os_info.Name.split('|')[0]
    except Exception as e:
        log.debug("wmi query", exc_info=True)
        log.warn("Warning: failed to query OS using wmi")
        log.warn(f" {e}")


def do_clean() -> None:
    if _wait_for_input:
        print("\nPress Enter to close")
        noerr(sys.stdout.flush)
        noerr(sys.stderr.flush)
        sys.stdin.readline()
        return

    # undo the redirect to file:
    if envbool("XPRA_LOG_TO_FILE", True):
        log_filename = os.environ.get("XPRA_LOG_FILENAME", "")
        if log_filename and os.path.exists(log_filename):
            noerr(sys.stdout.close)
            sys.stdout = sys.stderr = None
