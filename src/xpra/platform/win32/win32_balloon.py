#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Support for "balloon" notifications on MS Windows
# Based on code from winswitch, itself based on "win32gui_taskbar demo"

from xpra.os_util import BytesIOClass
from xpra.platform.win32.constants import SM_CXSMICON, SM_CYSMICON
from xpra.platform.win32.common import GetSystemMetrics
from xpra.log import Logger
log = Logger("notify", "win32")

import struct
from ctypes import windll

NIIF_USER = 4
NIF_INFO = 16
NIIF_INFO = 1
NIM_MODIFY = 1


def visible_command(command, max_len=100, no_nl=True):
    assert max_len>3
    if not command:
        return ""
    if no_nl:
        command = command.replace("\n", "").replace("\r", "")
    if len(command) < max_len:
        return command
    return command[:max_len-3] + "..."


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
    szTip = ''
    dwState = 0
    dwStateMask = 0
    szInfo = ''
    uTimeoutOrVersion = 0
    szInfoTitle = ''
    dwInfoFlags = 0
    guidItem = ''
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


def notify(hwnd, title, message, timeout=5000, icon=None):
    nid = PyNOTIFYICONDATA()
    nid.hWnd = hwnd
    nid.uFlags = NIF_INFO
    nid.szInfo = "%s" % visible_command(message, 255, False)        #prevent overflow
    nid.szInfoTitle = "%s" % visible_command(title, 63)
    if timeout<=0:
        timeout = 5000
    nid.uTimeoutOrVersion = timeout
    #if no icon is supplied, we can use:
    # NIIF_INFO, NIIF_WARNING or NIIF_ERROR
    nid.dwInfoFlags = NIIF_INFO
    if icon:
        try:
            w, h, data = icon[1:4]
            buf = BytesIOClass(data)
            from PIL import Image       #@UnresolvedImport
            from xpra.platform.win32.win32_NotifyIcon import image_to_ICONINFO
            img = Image.open(buf)
            iw = GetSystemMetrics(SM_CXSMICON)
            ih = GetSystemMetrics(SM_CYSMICON)
            if w!=iw or h!=ih:
                img = img.resize((iw, ih), Image.ANTIALIAS)
                log("notification icon resized to %s", img.size)
            hicon = image_to_ICONINFO(img)
            log("notify: image_to_ICONINFO(%s)=%#x", img, hicon)
            nid.hIcon = hicon
            nid.hBalloonIcon = hicon
        except Exception as e:
            log.error("Error: failed to set notification icon:")
            log.error(" %s", e)
        else:
            nid.dwInfoFlags = NIIF_USER
    Shell_NotifyIcon = windll.shell32.Shell_NotifyIcon
    Shell_NotifyIcon(NIM_MODIFY, nid.pack())


def main():
    from xpra.platform.win32.win32_NotifyIcon import main
    main()

if __name__=='__main__':
    main()
