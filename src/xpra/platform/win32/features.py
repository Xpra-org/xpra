# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific settings for Win32.
CAN_DAEMONIZE = False
MMAP_SUPPORTED = True
SYSTEM_TRAY_SUPPORTED = True
REINIT_WINDOWS = True

CLIPBOARDS=["CLIPBOARD"]
CLIPBOARD_GREEDY = True
CLIPBOARD_NATIVE_CLASS = "xpra.clipboard.translated_clipboard.TranslatedClipboardProtocolHelper"

EXECUTABLE_EXTENSION = "exe"

#these don't make sense on win32:
DEFAULT_PULSEAUDIO_COMMAND = ""
DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS = []
PRINT_COMMAND = ""
DEFAULT_SSH_COMMAND="plink -ssh -agent"

OPEN_COMMAND = ["start", "''"]

#not implemented:
SYSTEM_PROXY_SOCKET = "xpra-proxy"
