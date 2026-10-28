#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Support for "balloon" notifications on MS Windows
# Based on code from winswitch, itself based on "win32gui_taskbar demo"
from ctypes import sizeof, byref
from ctypes.wintypes import HICON

from xpra.platform.win32.constants import SM_CXSMICON, SM_CYSMICON
from xpra.platform.win32.common import GetSystemMetrics
from xpra.platform.win32.NotifyIcon import Shell_NotifyIcon, NOTIFYICONDATA, truncate_wchars, image_to_ICONINFO
from xpra.log import Logger

log = Logger("notify", "win32")

NIIF_USER = 4
NIF_INFO = 16
NIIF_INFO = 1
NIM_MODIFY = 1


def chop_string(text: str, max_len: int, no_nl: bool = True) -> str:
    """
    `max_len` is the number of WCHARs available, not counting the null terminator
    """
    if not text:
        return ""
    if no_nl:
        text = text.replace("\n", "").replace("\r", "")
    if truncate_wchars(text, max_len) == text:
        return text
    return truncate_wchars(text, max_len - 1) + "\u2026"


def notify(hwnd, app_id: int, title: str, message: str, timeout: int = 5000, icon=None):
    log("notify%s", (hwnd, app_id, title, message, timeout, icon))
    if timeout <= 0:
        timeout = 5000
    # `szInfo` and `szInfoTitle` are WCHAR buffers of 256 and 64:
    szInfo = chop_string(message, 255, False)
    szInfoTitle = chop_string(title, 63)
    hicon: HICON = HICON(0)
    if icon:
        try:
            from PIL import Image
            from xpra.codecs.pillow.decoder import open_only
            w, h, data = icon[1:4]
            img = open_only(data)
            iw =GetSystemMetrics(SM_CXSMICON)
            ih = GetSystemMetrics(SM_CYSMICON)
            if w != iw or h != ih:
                try:
                    LANCZOS = Image.Resampling.LANCZOS
                except AttributeError:
                    LANCZOS = Image.LANCZOS
                img = img.resize((iw, ih), LANCZOS)
                log("notification icon resized to %s", img.size)
            hicon = image_to_ICONINFO(img)
            log("notify: image_to_ICONINFO(%s)=%#x", img, hicon)
        except Exception as e:
            log("notify%s", (hwnd, app_id, title, message, timeout, icon), exc_info=True)
            log.error("Error: failed to set notification icon:")
            log.estr(e)

    nid = NOTIFYICONDATA()
    nid.cbSize = sizeof(NOTIFYICONDATA)
    nid.hWnd = hwnd
    nid.uID = app_id
    nid.uFlags = NIF_INFO
    nid.szInfo = szInfo
    nid.szInfoTitle = szInfoTitle
    nid.uVersion = timeout
    nid.dwInfoFlags = NIIF_INFO
    if hicon:
        nid.hIcon = nid.hBalloonIcon = hicon
        nid.dwInfoFlags = NIIF_USER
    r = Shell_NotifyIcon(NIM_MODIFY, byref(nid))
    log("notify using %s: %s", Shell_NotifyIcon, bool(r))


def main() -> None:
    import sys
    from xpra.platform.win32.NotifyIcon import main as notifyicon_main
    notifyicon_main(sys.argv)


if __name__ == '__main__':
    main()
