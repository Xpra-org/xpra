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

SOCKET_OPTIONS = (
    #not supported on win32:
    #"SO_BROADCAST", "SO_RCVLOWAT",
    "SO_DONTROUTE", "SO_ERROR", "SO_EXCLUSIVEADDRUSE",
    "SO_KEEPALIVE", "SO_LINGER", "SO_OOBINLINE", "SO_RCVBUF",
    "SO_RCVTIMEO", "SO_REUSEADDR", "SO_REUSEPORT",
    "SO_SNDBUF", "SO_SNDTIMEO", "SO_TIMEOUT", "SO_TYPE",
    )
IP_OPTIONS = (
    #not supported on win32:
    #"IP_MULTICAST_IF", "IP_MULTICAST_LOOP", "IP_MULTICAST_TTL",
    "IP_DONTFRAG", "IP_OPTIONS", "IP_RECVLCLIFADDR",
    "IP_RECVPKTINFO", "IP_TOS", "IP_TTL",
    )
