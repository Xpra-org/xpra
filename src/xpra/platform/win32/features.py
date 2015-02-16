# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Win32.
import os

def get_registry_value(key, reg_path, entry):
    import win32api             #@UnresolvedImport
    hKey = win32api.RegOpenKey(key, reg_path)
    value, _ = win32api.RegQueryValueEx(hKey, entry)
    win32api.RegCloseKey(hKey)
    return    value


SYSTEM_TRAY_SUPPORTED = True
SHADOW_SUPPORTED = True
os.environ["PLINK_PROTOCOL"] = "ssh"
DEFAULT_SSH_CMD = "plink"
PRINT_COMMAND = ""
#TODO: use "FOLDERID_Downloads":
# FOLDERID_Downloads = "{374DE290-123F-4565-9164-39C4925E467B}"
# maybe like here:
# https://gist.github.com/mkropat/7550097
#from win32com.shell import shell, shellcon
#shell.SHGetFolderPath(0, shellcon.CSIDL_MYDOCUMENTS, None, 0)
try:
    #use the internet explorer registry key:
    #HKEY_CURRENT_USER\Software\Microsoft\Internet Explorer
    import win32con             #@UnresolvedImport
    DOWNLOAD_PATH = get_registry_value(win32con.HKEY_CURRENT_USER, "Software\\Microsoft\\Internet Explorer", "Download Directory")
except:
    #fallback to what the documentation says is the default:
    DOWNLOAD_PATH = os.path.join(os.environ.get("USERPROFILE", "~"), "My Documents", "Downloads")
    if not os.path.exists(DOWNLOAD_PATH):
        DOWNLOAD_PATH = os.path.join(os.environ.get("USERPROFILE", "~"), "Downloads")
GOT_PASSWORD_PROMPT_SUGGESTION = \
   'Perhaps you need to set up Pageant, or (less secure) use --ssh="plink -pw YOUR-PASSWORD"?\n'
CLIPBOARDS=["CLIPBOARD"]
CLIPBOARD_GREEDY = True
CLIPBOARD_NATIVE_CLASS = ("xpra.clipboard.translated_clipboard", "TranslatedClipboardProtocolHelper", {})

#these don't make sense on win32:
DEFAULT_PULSEAUDIO_COMMAND = ""
DEFAULT_XVFB_COMMAND = ""
