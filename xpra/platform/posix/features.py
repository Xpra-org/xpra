# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.util.system import is_Wayland

AUTOSTART = True

DEFAULT_ENV = (
    "#silence some AT-SPI and atk-bridge warnings:",
    "NO_AT_BRIDGE=1",
)

DEFAULT_START_ENV = (
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
)

DEFAULT_SSH_CMD = "ssh"

CLIPBOARDS: Sequence[str] = ("CLIPBOARD", "PRIMARY", "SECONDARY")
CLIPBOARD_GREEDY = False
if is_Wayland():
    CLIPBOARDS = ("CLIPBOARD", "PRIMARY")
    CLIPBOARD_GREEDY = True
CLIPBOARD_PREFERRED_TARGETS: Sequence[str] = ("UTF8_STRING", "TEXT", "STRING", "text/plain", "image/png")

OPEN_COMMAND = ("/usr/bin/xdg-open",)

INPUT_DEVICES: Sequence[str] = ("auto", "xi", "uinput")

SOURCE: Sequence[str] = ("/etc/profile", )

COMMAND_SIGNALS: Sequence[str] = ("SIGINT", "SIGTERM", "SIGHUP", "SIGKILL", "SIGUSR1", "SIGUSR2")
