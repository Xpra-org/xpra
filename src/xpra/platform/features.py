# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#defaults which may be overriden by platform_import:
LOCAL_SERVERS_SUPPORTED = False
SHADOW_SUPPORTED = False
MMAP_SUPPORTED = False
SYSTEM_TRAY_SUPPORTED = False
DEFAULT_SSH_CMD = False
GOT_PASSWORD_PROMPT_SUGGESTION = ""
CLIPBOARDS = []
CLIPBOARD_WANT_TARGETS = False
CLIPBOARD_GREEDY = False
CLIPBOARD_NATIVE_CLASS = None
CAN_DAEMONIZE = False

from xpra.platform import platform_import
platform_import(globals(), "features", False,
                "LOCAL_SERVERS_SUPPORTED",
                "SHADOW_SUPPORTED",
                "CAN_DAEMONIZE",
                "MMAP_SUPPORTED",
                "SYSTEM_TRAY_SUPPORTED",
                "DEFAULT_SSH_CMD",
                "GOT_PASSWORD_PROMPT_SUGGESTION",
                "CLIPBOARDS",
                "CLIPBOARD_WANT_TARGETS",
                "CLIPBOARD_GREEDY",
                "CLIPBOARD_NATIVE_CLASS")
