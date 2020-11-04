#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Support for "balloon" notifications on MS Windows
# Based on code from winswitch, itself based on "win32gui_taskbar demo"
import struct
from ctypes import windll, c_void_p, sizeof, byref, addressof
from ctypes.wintypes import BOOL, DWORD

from xpra.os_util import strtobytes
from xpra.util import XPRA_GUID_BYTES
from xpra.platform.win32.constants import SM_CXSMICON, SM_CYSMICON
from xpra.platform.win32.common import GetSystemMetrics
from xpra.log import Logger

log = Logger("notify", "win32")

NIIF_USER = 4
NIF_INFO = 16
NIIF_INFO = 1
NIM_MODIFY = 1


def chop_string(command, max_len=100, no_nl=True):
    assert max_len>3
    if not command:
        return b""
    command = strtobytes(command)
    if no_nl:
        command = command.replace(b"\n", b"").replace(b"\r", b"")
    if len(command) <= max_len:
        return command
    return command[:max_len-3] + b"..."


class PyNOTIFYICONDATA:
    _struct_format = (
        "I" # DWORD cbSize;
        "I" # HWND hWnd;
        "I" # UINT uID;
        "I" # UINT uFlags;
        "I" # UINT uCallbackMessage;
        "I" # HICON hIcon;
        "128s" # TCHAR szTip[128];
        "I" # DWORD dwState;
        "I" # DWORD dwStateMask;
        "256s" # TCHAR szInfo[256];
        "I" # union {
        # UINT uTimeout;
        # UINT uVersion;
        #} DUMMYUNIONNAME;
        "64s" # TCHAR szInfoTitle[64];
        "I" # DWORD dwInfoFlags;
        # GUID guidItem;
        "16s"# GUID guidItem;
        "I" # HICON hBalloonIcon
    )
    _struct = struct.Struct(_struct_format)

    hWnd = 0
    uID = 0
    uFlags = 0
    uCallbackMessage = 0
    hIcon = 0
    szTip = b''
    dwState = 0
    dwStateMask = 0
    szInfo = b''
    uTimeoutOrVersion = 0
    szInfoTitle = b''
    dwInfoFlags = 0
    guidItem = b''
    hBalloonIcon = 0

    def pack(self):
        return self._struct.pack(
        self._struct.size,
        self.hWnd,
        self.uID,
        self.uFlags,
        self.uCallbackMessage,
        self.hIcon,
        self.szTip,
        self.dwState,
        self.dwStateMask,
        self.szInfo,
        self.uTimeoutOrVersion,
        self.szInfoTitle,
        self.dwInfoFlags,
        self.guidItem,
        self.hBalloonIcon,
        )

    def __setattr__(self, name, value):
        # avoid wrong field names
        if not hasattr(self, name):
            raise NameError(name)
        self.__dict__[name] = value

    def __repr__(self):
        return "PyNOTIFYICONDATA(%s)" % self.__dict__


Shell_NotifyIcon = windll.shell32.Shell_NotifyIconA
Shell_NotifyIcon.restype = BOOL
Shell_NotifyIcon.argtypes = [DWORD, c_void_p]


def notify(hwnd, app_id, title, message, timeout=5000, icon=None):
    log("notify%s", (hwnd, app_id, title, message, timeout, icon))
    if timeout<=0:
        timeout = 5000
    szInfo = chop_string(message, 255, False)    #prevent overflow
    szInfoTitle = chop_string(title, 63)
    hicon = 0
    if icon:
        try:
            from PIL import Image
            from xpra.codecs.pillow.decoder import open_only
            w, h, data = icon[1:4]
            img = open_only(data)
            from xpra.platform.win32.win32_NotifyIcon import image_to_ICONINFO
            iw = GetSystemMetrics(SM_CXSMICON)
            ih = GetSystemMetrics(SM_CYSMICON)
            if w!=iw or h!=ih:
                img = img.resize((iw, ih), Image.ANTIALIAS)
                log("notification icon resized to %s", img.size)
            hicon = image_to_ICONINFO(img)
            log("notify: image_to_ICONINFO(%s)=%#x", img, hicon)
        except Exception as e:
            log("notify%s", (hwnd, app_id, title, message, timeout, icon), exc_info=True)
            log.error("Error: failed to set notification icon:")
            log.error(" %s", e)

    from xpra.platform.win32.win32_NotifyIcon import Shell_NotifyIconA, XPRA_GUID, getNOTIFYICONDATAClass

    nc = getNOTIFYICONDATAClass(tip_size=128)
    nid = nc()
    nid.cbSize = sizeof(nc)
    nid.hWnd = hwnd
    nid.uID = app_id
    nid.uFlags = NIF_INFO
    nid.guidItem = XPRA_GUID
    try:
        nid.szInfo = szInfo
    except:
        nid.szInfo = szInfo.decode()
    v = chop_string(title, 63)
    try:
        nid.szInfoTitle = szInfoTitle
    except:
        nid.szInfoTitle = szInfoTitle.decode()
    nid.uVersion = timeout
    nid.dwInfoFlags = NIIF_INFO
    if hicon:
        nid.hIcon = nid.hBalloonIcon = hicon
        nid.dwInfoFlags = NIIF_USER
    Shell_NotifyIconA(NIM_MODIFY, byref(nid))
    log("notify using %s", Shell_NotifyIconA)

def main():
    from xpra.platform.win32.win32_NotifyIcon import main
    main()

if __name__=='__main__':
    main()
