# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
import tempfile
import platform
from ctypes import (
    WinDLL,  # @UnresolvedImport
    create_unicode_buffer
    )
from ctypes.wintypes import MAX_PATH
from typing import List

from xpra.os_util import get_util_logger

shell32 = WinDLL("shell32", use_last_error=True)
SHGetFolderPath = shell32.SHGetFolderPathW

CSIDL_APPDATA = 26
CSIDL_LOCAL_APPDATA = 28
CSIDL_COMMON_APPDATA = 35
CSIDL_PROFILE = 40


def sh_get_folder_path(v) -> str:
    try:
        buf = create_unicode_buffer(MAX_PATH)
        SHGetFolderPath(0, v, None, 0, buf)
        if not buf.value:
            return buf.value
        return os.path.normpath(buf.value)
    except Exception:
        return ""

def _get_data_dir(roaming=True) -> str:
    #if not running from a binary, return current directory:
    if not getattr(sys, 'frozen', ''):
        return os.getcwd()
    return get_appdata_dir(roaming)


def get_appdata_dir(roaming=True) -> str:
    appdata = sh_get_folder_path(CSIDL_APPDATA if roaming else CSIDL_LOCAL_APPDATA)
    if not appdata:
        # on win32 we must send stdout to a logfile to prevent an alert box on exit shown by `py2exe`
        # UAC in vista onwards will not allow us to write where the software is installed,
        # so we place the log file (etc) in "~/Application Data"
        appdata = os.environ.get("APPDATA" if roaming else "LOCALAPPDATA", "")
    if not appdata:
        #we need some kind of path..
        appdata = tempfile.gettempdir()
        assert appdata, "cannot find any usable directory for log files"
    if not os.path.exists(appdata):
        os.mkdir(appdata)
    data_dir = os.path.join(appdata, "Xpra")
    return data_dir


def do_get_resources_dir() -> str:
    from xpra.platform.paths import get_app_dir
    app_dir = get_app_dir()
    prefix = os.environ.get("MINGW_PREFIX")
    for d in (app_dir, prefix):
        if not d or not os.path.isdir(d):
            continue
        share_xpra = os.path.join(d, "share", "xpra")
        if os.path.exists(share_xpra):
            return share_xpra
    return app_dir

def do_get_icon_dir() -> str:
    from xpra.platform.paths import get_resources_dir
    return os.path.join(get_resources_dir(), "icons")

def do_get_default_log_dirs() -> List[str]:
    dd = _get_data_dir()
    temp = tempfile.gettempdir()
    if dd==temp:
        return [temp]
    return [dd, temp]


def get_program_data_dir() -> str:
    #ie: "C:\ProgramData"
    try:
        return sh_get_folder_path(CSIDL_COMMON_APPDATA) or "C:\\ProgramData"
    except Exception:
        get_util_logger().debug("get_program_data_dir()", exc_info=True)
    return "C:\\ProgramData"

def do_get_system_conf_dirs() -> List[str]:
    #ie: C:\ProgramData\Xpra
    return [os.path.join(get_program_data_dir(), "Xpra")]


def do_get_ssl_cert_dirs() -> List[str]:
    dirs = []
    for i in (CSIDL_PROFILE, CSIDL_COMMON_APPDATA, CSIDL_LOCAL_APPDATA, CSIDL_APPDATA):
        fpath = sh_get_folder_path(i)
        if not fpath:
            continue
        d = os.path.join(fpath, "Xpra")
        dirs.append(d)
        d = os.path.join(fpath, "Xpra", "ssl")
        dirs.append(d)
    dirs += do_get_default_conf_dirs()
    return dirs


def do_get_ssh_conf_dirs() -> List[str]:
    if platform.architecture()[0]=="32bit":
        system32 = "SysNative"
    else:
        system32 = "System32"
    windows_dir = os.environ.get("SystemRoot", os.environ.get("WINDIR", "C:\\Windows"))
    openssh_dir = os.path.join(windows_dir, system32, "OpenSSH")
    dirs = []
    for i in (CSIDL_PROFILE, CSIDL_COMMON_APPDATA, CSIDL_LOCAL_APPDATA, CSIDL_APPDATA):
        fpath = sh_get_folder_path(i)
        if not fpath:
            continue
        d = os.path.join(fpath, "SSH")
        dirs.append(d)
    dirs += do_get_default_conf_dirs()+[
        openssh_dir,        #ie: C:\Windows\system32\OpenSSH
        "~/.ssh",
        "~/ssh",
        ]
    return dirs

def do_get_ssh_known_hosts_files() -> List[str]:
    #reverse the order (avoid dotfiles on win32):
    return ["~/ssh/known_hosts", "~/.ssh/known_hosts"]


def do_get_sessions_dir() -> str:
    return "%APPDATA%\\Xpra"


def do_get_default_conf_dirs() -> List[str]:
    #ie: C:\Program Files\Xpra\
    from xpra.platform.paths import get_app_dir
    return [os.path.join(get_app_dir(), "etc", "xpra")]

def do_get_user_conf_dirs(_uid) -> List[str]:
    dd = _get_data_dir()
    #ie: "C:\Users\<user name>\AppData\Roaming"
    SYSTEMROOT = os.environ.get("SYSTEMROOT", "")
    #ie: when running as a system service, we may get:
    # "C:\Windows\System32\config\systemprofile\AppData\Roaming"
    # and we don't want to use that:
    if SYSTEMROOT and dd.startswith(SYSTEMROOT):
        return []
    if not os.path.exists(dd):
        os.mkdir(dd)
    return [dd]


def do_get_desktop_background_paths() -> List[str]:
    try:
        from winreg import OpenKey, HKEY_CURRENT_USER, KEY_READ, QueryValueEx    #@UnresolvedImport @Reimport
        key_path = "Control Panel\\Desktop"
        key = OpenKey(HKEY_CURRENT_USER, key_path, 0, KEY_READ)    #@UndefinedVariable
        wallpaper = QueryValueEx(key, 'WallPaper')[0]    #@UndefinedVariable
        return [wallpaper,]
    except Exception:
        log = get_util_logger()
        log("do_get_desktop_background_paths()", exc_info=True)
    return []


def do_get_download_dir() -> str:
    try:
        #values found here: https://stackoverflow.com/a/48706260
        from winreg import OpenKey, HKEY_CURRENT_USER, QueryValueEx    #@UnresolvedImport @Reimport
        sub_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
        downloads_guid = '{374DE290-123F-4565-9164-39C4925E467B}'
        with OpenKey(HKEY_CURRENT_USER, sub_key) as key:
            DOWNLOAD_PATH = QueryValueEx(key, downloads_guid)[0]
    except Exception:
        get_util_logger()("do_get_download_dir()", exc_info=True)
        #fallback to what the documentation says is the default:
        DOWNLOAD_PATH = os.path.join(os.environ.get("USERPROFILE", "~"), "My Documents", "Downloads")
        if not os.path.exists(DOWNLOAD_PATH):
            DOWNLOAD_PATH = os.path.join(os.environ.get("USERPROFILE", "~"), "Downloads")
    return DOWNLOAD_PATH

def do_get_script_bin_dirs() -> List[str]:
    #we don't save the "run-xpra" script anywhere on win32
    return []

def do_get_socket_dirs() -> List[str]:
    return []


APP_DIR : str = ""
if getattr(sys, 'frozen', False) is True:
    #cx_freeze = sys.frozen == True
    APP_DIR = os.path.dirname(sys.executable)
    if len(APP_DIR)>3 and APP_DIR[1]==":" and APP_DIR[2]=="/":
        #it seems that mingw builds can get confused about the correct value for os.pathsep:
        APP_DIR = APP_DIR.replace("/", "\\")
    try:
        sys.path.remove(APP_DIR)
    except ValueError:
        pass
    sys.path.insert(0, APP_DIR)
    os.chdir(APP_DIR)
    #so we can easily load DLLs with ctypes:
    os.environ['PATH'] = APP_DIR + os.pathsep + os.environ['PATH']


def do_get_app_dir() -> str:
    global APP_DIR
    if APP_DIR:
        return APP_DIR
    from xpra.platform.paths import default_get_app_dir   #imported here to prevent import loop
    return default_get_app_dir()

def do_get_nodock_command() -> List[str]:
    return _get_xpra_exe_command(
        "Xpra",             #executable without a shell
        "Xpra_cmd",         #we should never end up using this one
        )

def do_get_audio_command() -> List[str]:
    return _get_xpra_exe_command(
        "Xpra_Audio",       #executable without a shell, and with a nicer name
        "Xpra",             #executable without a shell
        "Xpra_cmd",         #we should never end up using this one
        )

def _get_xpra_exe_command(*cmd_options) -> List[str]:
    from xpra.platform.paths import get_app_dir
    exe_dir = get_app_dir()
    mingw = os.environ.get("MINGW_PREFIX")
    for cmd in cmd_options:
        exe_name = "%s.exe" % cmd
        if sys.executable.lower().endswith(exe_name):
            #prefer the same executable we were launched from:
            return [sys.executable]
        #try to find it in exe dir:
        exe = os.path.join(exe_dir, exe_name)
        if os.path.exists(exe) and os.path.isfile(exe):
            return [exe]
        #without ".exe" extension:
        script = os.path.join(exe_dir, cmd)
        if os.path.exists(script) and os.path.isfile(script):
            return [script]
        if mingw:
            #the python interpreter to use with the scripts:
            py = os.path.join(mingw, "bin", "python3.exe")
            if os.path.exists(py):
                if cmd.lower() in ("python", "python3"):
                    return [py]
                #ie: /e/Xpra/trunk/src/dist/xpra
                script = os.path.join(os.getcwd(), "scripts", cmd.lower())
                if os.path.exists(script) and os.path.isfile(script):
                    return [py, script]
                #ie: /mingw64/bin/xpra
                script = os.path.join(mingw, "bin", cmd.lower())
                if os.path.exists(script) and os.path.isfile(script):
                    return [py, script]
    from xpra.platform.paths import default_do_get_xpra_command
    d = default_do_get_xpra_command()
    if len(d) == 1:
        #ie: d="xpra"
        if not d[0].lower().endswith(".exe"):
            return [sys.executable, d[0]]
    return d

def do_get_xpra_command() -> List[str]:
    sl = sys.executable.lower()
    #keep the exact same command used to launch if we can:
    if sl.endswith("xpra_cmd.exe") or sl.endswith("xpra.exe"):
        return [sys.executable]
    return _get_xpra_exe_command("Xpra", "Xpra_cmd")


def do_get_python_exec_command() -> List[str]:
    return _get_xpra_exe_command("Python_exec_gui", "Python")

def do_get_python_execfile_command() -> List[str]:
    return _get_xpra_exe_command("Python_execfile_gui", "Python")
