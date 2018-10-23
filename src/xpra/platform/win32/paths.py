# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
import ctypes
from xpra.os_util import get_util_logger

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
SHGetFolderPath = shell32.SHGetFolderPathW

CSIDL_APPDATA = 26
CSIDL_COMMON_APPDATA = 35


def _get_data_dir():
    #if not running from a binary, return current directory:
    if not getattr(sys, 'frozen', ''):
        return os.getcwd()
    try:
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        SHGetFolderPath(0, CSIDL_APPDATA, None, 0, buf)
        appdata = buf.value
    except:
        #on win32 we must send stdout to a logfile to prevent an alert box on exit shown by py2exe
        #UAC in vista onwards will not allow us to write where the software is installed,
        #so we place the log file (etc) in "~/Application Data"
        appdata = os.environ.get("APPDATA")
    if not appdata:
        #we need some kind of path..
        appdata = os.environ.get("TEMP", "C:\\TEMP\\")
        assert appdata, "cannot find any usable directory for log files"
    if not os.path.exists(appdata):
        os.mkdir(appdata)
    data_dir = os.path.join(appdata, "Xpra")
    if not os.path.exists(data_dir):
        os.mkdir(data_dir)
    return data_dir


def do_get_resources_dir():
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

def do_get_icon_dir():
    from xpra.platform.paths import get_resources_dir
    return os.path.join(get_resources_dir(), "icons")


def get_program_data_dir():
    #ie: "C:\ProgramData"
    try:
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        SHGetFolderPath(0, CSIDL_COMMON_APPDATA, None, 0, buf)
        if buf.value:
            return buf.value
    except:
        get_util_logger().debug("get_program_data_dir()", exc_info=True)
    return u"C:\\ProgramData"

def do_get_system_conf_dirs():
    #ie: C:\ProgramData\Xpra
    return [os.path.join(get_program_data_dir(), u"Xpra")]

def do_get_ssh_conf_dirs():
    from xpra.scripts.config import python_platform
    if python_platform.architecture()[0]=="32bit":
        system32 = "SysNative"
    else:
        system32 = "System32"
    windows_dir = os.environ.get("SystemRoot", os.environ.get("WINDIR", "C:\\Windows"))
    openssh_dir = os.path.join(windows_dir, system32, "OpenSSH")
    return [
        os.path.join(get_program_data_dir(), "ssh"),    #ie: C:\ProgramData\ssh
        "%APPDATA%\\ssh",   #ie: C:\Users\Username\AppData\Roaming\ssh
        openssh_dir,        #ie: C:\Windows\system32\OpenSSH
        "~/.ssh",
        "~/ssh",
        ]

def do_get_ssh_known_hosts_files():
    #reverse the order (avoid dotfiles on win32):
    return ("~/ssh/known_hosts", "~/.ssh/known_hosts")


def do_get_default_conf_dirs():
    #ie: C:\Program Files\Xpra\
    from xpra.platform.paths import get_app_dir
    return [os.path.join(get_app_dir(), "etc", "xpra")]

def do_get_user_conf_dirs(_uid):
    #ie: "C:\Users\<user name>\AppData\Roaming"
    return [_get_data_dir()]


def do_get_download_dir():
    #TODO: use "FOLDERID_Downloads":
    # FOLDERID_Downloads = "{374DE290-123F-4565-9164-39C4925E467B}"
    # maybe like here:
    # https://gist.github.com/mkropat/7550097
    #from win32com.shell import shell, shellcon
    #shell.SHGetFolderPath(0, shellcon.CSIDL_MYDOCUMENTS, None, 0)
    try:
        try:
            import _winreg as winreg
        except ImportError:
            import winreg   #@UnresolvedImport @Reimport
        #use the internet explorer registry key:
        #HKEY_CURRENT_USER\Software\Microsoft\Internet Explorer
        key_path = 'Software\\Microsoft\\Internet Explorer'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        DOWNLOAD_PATH = winreg.QueryValueEx(key, 'Download Directory')[0]
    except:
        #fallback to what the documentation says is the default:
        DOWNLOAD_PATH = os.path.join(os.environ.get("USERPROFILE", "~"), "My Documents", "Downloads")
        if not os.path.exists(DOWNLOAD_PATH):
            DOWNLOAD_PATH = os.path.join(os.environ.get("USERPROFILE", "~"), "Downloads")
    return DOWNLOAD_PATH

def do_get_script_bin_dirs():
    #we don't save the "run-xpra" script anywhere on win32
    return []

def do_get_socket_dirs():
    return []


APP_DIR = None
if getattr(sys, 'frozen', False) is True:
    #cx_freeze = sys.frozen == True
    if sys.version_info >= (3,0):
        APP_DIR = os.path.dirname(sys.executable)
    else:
        APP_DIR = os.path.dirname(unicode(sys.executable, sys.getfilesystemencoding()))
    if len(APP_DIR)>3 and APP_DIR[1]==":" and APP_DIR[2]=="/":
        #it seems that mingw builds can get confused about the correct value for os.pathsep:
        APP_DIR = APP_DIR.replace("/", "\\")
    sys.path.insert(0, APP_DIR)
    os.chdir(APP_DIR)
    #so we can easily load DLLs with ctypes:
    if sys.version_info >= (3,0):
        os.environ['PATH'] = APP_DIR + os.pathsep + os.environ['PATH']
    else:
        os.environ['PATH'] = APP_DIR.encode('utf8') + os.pathsep + os.environ['PATH']


def do_get_app_dir():
    global APP_DIR
    if APP_DIR is not None:
        return APP_DIR
    from xpra.platform.paths import default_get_app_dir   #imported here to prevent import loop
    return default_get_app_dir()

def do_get_sound_command():
    from xpra.platform.paths import get_app_dir
    app_dir = get_app_dir()
    for apaths in (
        ("Audio", "Xpra_Audio.exe"),    #python3 bundled sound subdirectory
        ("Xpra_Audio.exe",),            #same directory, but with a nicer name:
        ("xpra_cmd.exe",),              #fallback for older build method
        ):
        sound_exe = os.path.join(app_dir, *apaths)
        if os.path.exists(sound_exe):
            return [sound_exe]
    return do_get_xpra_command()

def do_get_xpra_command():
    mingw = os.environ.get("MINGW_PREFIX")
    if mingw:
        xpra_script = os.path.join(mingw, "bin", "xpra")
        py = os.path.join(mingw, "bin", "python%i.exe" % sys.version_info[0])
        if os.path.exists(xpra_script) and os.path.exists(py):
            return [py, xpra_script]
    from xpra.platform.paths import default_do_get_xpra_command
    return default_do_get_xpra_command()
