# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
import ctypes

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


def do_get_icon_dir():
    from xpra.platform.paths import get_app_dir
    return os.path.join(get_app_dir(), "icons")


def do_get_system_conf_dirs():
    #ie: "C:\Documents and Settings\All Users\Application Data\Xpra" with XP
    #or: "C:\ProgramData\Xpra" with Vista onwards
    try:
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        SHGetFolderPath(0, CSIDL_COMMON_APPDATA, None, 0, buf)
        if buf.value:
            return [os.path.join(buf.value, "Xpra")]
    except:
        pass
    return []

def do_get_default_conf_dirs():
    #ie: C:\Program Files\Xpra\
    from xpra.platform.paths import get_app_dir
    return [os.path.join(get_app_dir(), "etc", "xpra")]

def do_get_user_conf_dirs(_uid):
    #ie: "C:\Documents and Settings\<user name>\Application Data\Xpra" with XP
    #or: "C:\Users\<user name>\AppData\Roaming" with Visa onwards
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
    #ie: C:\Documents and Settings\Username\Application Data\Xpra
    return [_get_data_dir()]


APP_DIR = None
if getattr(sys, 'frozen', False) in (True, "windows_exe", "console_exe"):    #@UndefinedVariable
    #cx_freeze = sys.frozen == True
    #py2exe =  sys.frozen in ("windows_exe", "console_exe")
    if sys.version_info >= (3,0):
        APP_DIR = os.path.dirname(sys.executable)
    else:
        APP_DIR = os.path.dirname(unicode(sys.executable, sys.getfilesystemencoding()))
    sys.path.insert(0, APP_DIR)
    os.chdir(APP_DIR)
    #so we can easily load DLLs with ctypes:
    if sys.version_info >= (3,0):
        os.environ['PATH'] = APP_DIR + os.pathsep + os.environ['PATH']
    else:
        os.environ['PATH'] = APP_DIR.encode('utf8') + os.pathsep + os.environ['PATH']

def do_get_resources_dir():
    from xpra.platform.paths import get_app_dir
    return get_app_dir()

def do_get_app_dir():
    global APP_DIR
    if APP_DIR is not None:
        return APP_DIR
    from xpra.platform.paths import default_get_app_dir   #imported here to prevent import loop
    return default_get_app_dir()

def do_get_sound_command():
    from xpra.platform.paths import get_app_dir
    app_dir = get_app_dir()
    #is there a python3 bundled sound subdirectory
    sound_exe = os.path.join(app_dir, "Audio", "Xpra_Audio.exe")
    #same directory, but with a nicer name:
    if not os.path.exists(sound_exe):
        sound_exe = os.path.join(app_dir, "Xpra_Audio.exe")
    #fallback for older build method:
    if not os.path.exists(sound_exe):
        sound_exe = os.path.join(app_dir, "xpra_cmd.exe")
    return [sound_exe]
