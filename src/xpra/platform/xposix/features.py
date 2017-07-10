# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#don't bother trying to forward system tray with Ubuntu's "unity":
from xpra.os_util import is_unity, PYTHON2
SYSTEM_TRAY_SUPPORTED = not is_unity()

SHADOW_SUPPORTED = PYTHON2

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
             ]

DEFAULT_SSH_CMD = "ssh"
CLIPBOARDS=["CLIPBOARD", "PRIMARY", "SECONDARY"]

INPUT_DEVICES = ["auto", "xi"]
