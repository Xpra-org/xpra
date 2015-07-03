# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

#don't bother trying to forward system tray with Ubuntu's "unity":
from xpra.os_util import is_unity, is_Ubuntu, is_Fedora
SYSTEM_TRAY_SUPPORTED = not is_unity()
#this is only our best guess
#there is more logic in setup.py, but it requires more effort too:
XDUMMY = not is_Ubuntu()
#displayfd requires Xdummy, and we don't support servers with py3k:
DISPLAYFD = XDUMMY and sys.version_info[0]<3
XDUMMY_WRAPPER = is_Fedora()

DEFAULT_ENV = [
             ("#avoid Ubuntu's global menu, which is a mess and cannot be forwarded:", ),
             ("UBUNTU_MENUPROXY",           ""),
             ("QT_X11_NO_NATIVE_MENUBAR",   "1"),
             ("#fix for MainSoft's MainWin buggy window management:", ),
             ("MWNOCAPTURE",                "true"),
             ("MWNO_RIT",                   "true"),
             ("MWWM",                       "allwm"),
             ]

DEFAULT_SSH_CMD = "ssh"
GOT_PASSWORD_PROMPT_SUGGESTION = "Perhaps you need to set up your ssh agent?\n"
CLIPBOARDS=["CLIPBOARD", "PRIMARY", "SECONDARY"]
