#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Support for "balloon" notifications on MS Windows
# Based on code from winswitch, itself based on "win32gui_taskbar demo"

import struct
from ctypes import windll

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
        self.dwInfoFlags)

    def __setattr__(self, name, value):
        # avoid wrong field names
        if not hasattr(self, name):
            raise NameError(name)
        self.__dict__[name] = value


def notify(hwnd, title, message, timeout=5000):
    # For this message I can't use the win32gui structure because
    # it doesn't declare the new, required fields
    nid = PyNOTIFYICONDATA()
    nid.hWnd = hwnd
    nid.uFlags = NIF_INFO
    # type of balloon and text are random
    nid.dwInfoFlags = NIIF_INFO    #choice([NIIF_INFO, NIIF_WARNING, NIIF_ERROR])
    nid.szInfo = "%s" % visible_command(message, 255, False)        #prevent overflow
    nid.szInfoTitle = "%s" % visible_command(title, 63)
    if timeout<=0:
        timeout = 5000
    nid.uTimeoutOrVersion = timeout
    #WM_TRAYICON = win32con.WM_USER + 20
    #nid.uCallbackMessage = WM_TRAYICON
    # Call the Windows function, not the wrapped one
    Shell_NotifyIcon = windll.shell32.Shell_NotifyIconA
    Shell_NotifyIcon(NIM_MODIFY, nid.pack())


def main():
    notify(0, "title", "message")
    import time
    time.sleep(10)

if __name__=='__main__':
    main()
