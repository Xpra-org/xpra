# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#don't bother trying to forward system tray with Ubuntu's "unity":
from xpra.os_util import is_unity, is_Wayland

SYSTEM_TRAY_SUPPORTED = not is_unity()

LOCAL_SERVERS_SUPPORTED = True
SHADOW_SUPPORTED = True

DEFAULT_ENV = [
             "#avoid Ubuntu's global menu, which is a mess and cannot be forwarded:",
             "UBUNTU_MENUPROXY=",
             "QT_X11_NO_NATIVE_MENUBAR=1",
             "#fix for MainSoft's MainWin buggy window management:",
             "MWNOCAPTURE=true",
             "MWNO_RIT=true",
             "MWWM=allwm",
             "#force GTK3 applications to use X11 so we can intercept them:",
             "GDK_BACKEND=x11",
             "#force Qt applications to use X11 so we can intercept them:",
             "QT_QPA_PLATFORM=xcb",
             "#disable Qt scaling:"
             "QT_AUTO_SCREEN_SET_FACTOR=0",
             "QT_SCALE_FACTOR=1",
             "#overlay scrollbars complicate things:"
             "GTK_OVERLAY_SCROLLING=0",
             "#some versions of GTK3 honour this option, sadly not all:",
             "GTK_CSD=0",
             "#silence some AT-SPI and atk-bridge warnings:",
             "NO_AT_BRIDGE=1",
             ]

DEFAULT_SSH_CMD = "ssh"

CLIPBOARDS=["CLIPBOARD", "PRIMARY"]
if not is_Wayland():
    CLIPBOARDS.append("SECONDARY")
    CLIPBOARD_GREEDY = False
else:
    CLIPBOARD_GREEDY = True
CLIPBOARD_PREFERRED_TARGETS = ("UTF8_STRING", "TEXT", "STRING", "text/plain", "image/png")

OPEN_COMMAND = ["/usr/bin/xdg-open"]

INPUT_DEVICES = ["auto", "xi", "uinput"]

COMMAND_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGKILL", "SIGUSR1", "SIGUSR2")
