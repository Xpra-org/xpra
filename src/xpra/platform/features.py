#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
from xpra.util import envbool
from xpra.os_util import PYTHON2

#defaults which may be overriden by platform_import:
LOCAL_SERVERS_SUPPORTED = PYTHON2
SHADOW_SUPPORTED = True
CAN_DAEMONIZE = True
MMAP_SUPPORTED = True
SYSTEM_TRAY_SUPPORTED = False
REINIT_WINDOWS = False

INPUT_DEVICES = ["auto"]

SYSTEM_PROXY_SOCKET = os.environ.get("XPRA_SYSTEM_PROXY_SOCKET", "/run/xpra/system")

CLIPBOARDS = []
CLIPBOARD_WANT_TARGETS = envbool("XPRA_CLIPBOARD_WANT_TARGETS")
CLIPBOARD_GREEDY = envbool("XPRA_CLIPBOARD_GREEDY")
CLIPBOARD_NATIVE_CLASS = None

EXECUTABLE_EXTENSION = ""

UI_THREAD_POLLING = 0
OPEN_COMMAND = []

COMMAND_SIGNALS = ()

DEFAULT_ENV = []

DEFAULT_SSH_COMMAND = "ssh -x"
DEFAULT_PULSEAUDIO_COMMAND = ["pulseaudio", "--start", "-n", "--daemonize=false", "--system=false",
                                    "--exit-idle-time=-1", "--load=module-suspend-on-idle",
                                    "'--load=module-null-sink sink_name=\"Xpra-Speaker\" sink_properties=device.description=\"Xpra\\ Speaker\"'",
                                    "'--load=module-null-sink sink_name=\"Xpra-Microphone\" sink_properties=device.description=\"Xpra\\ Microphone\"'",
                                    "--load=module-native-protocol-unix",
                                    "--load=module-dbus-protocol",
                                    "--log-level=2", "--log-target=stderr"]
DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS = [
                                         ["pactl", "set-default-sink", "Xpra-Speaker"],
                                         ["pactl", "set-default-source", "Xpra-Microphone.monitor"],
                                         ]


if sys.version<'3':
    CLIENT_MODULES = ["xpra.client.gtk2.client"]
else:
    CLIENT_MODULES = ["xpra.client.gtk3.client"]


SOCKET_OPTIONS = (
    "SO_BROADCAST", "SO_RCVLOWAT",
    "SO_DONTROUTE", "SO_ERROR", "SO_EXCLUSIVEADDRUSE",
    "SO_KEEPALIVE", "SO_LINGER", "SO_OOBINLINE", "SO_RCVBUF",
    "SO_RCVTIMEO", "SO_REUSEADDR", "SO_REUSEPORT",
    "SO_SNDBUF", "SO_SNDTIMEO", "SO_TIMEOUT", "SO_TYPE",
    )
IP_OPTIONS = (
    "IP_MULTICAST_IF", "IP_MULTICAST_LOOP", "IP_MULTICAST_TTL",
    "IP_DONTFRAG", "IP_OPTIONS", "IP_RECVLCLIFADDR",
    "IP_RECVPKTINFO", "IP_TOS", "IP_TTL",
    )
TCP_OPTIONS = ("TCP_NODELAY", "TCP_MAXSEG", "TCP_KEEPALIVE")


_features_list_ = [
                   "LOCAL_SERVERS_SUPPORTED",
                   "SHADOW_SUPPORTED",
                   "CAN_DAEMONIZE",
                   "MMAP_SUPPORTED",
                   "SYSTEM_TRAY_SUPPORTED",
                   "REINIT_WINDOWS",
                   "COMMAND_SIGNALS",
                   "DEFAULT_ENV",
                   "DEFAULT_SSH_COMMAND",
                   "DEFAULT_PULSEAUDIO_COMMAND",
                   "DEFAULT_PULSEAUDIO_CONFIGURE_COMMANDS",
                   "CLIPBOARDS",
                   "CLIPBOARD_WANT_TARGETS",
                   "CLIPBOARD_GREEDY",
                   "CLIPBOARD_NATIVE_CLASS",
                   "EXECUTABLE_EXTENSION",
                   "UI_THREAD_POLLING",
                   "CLIENT_MODULES",
                   "INPUT_DEVICES",
                   "SYSTEM_PROXY_SOCKET",
                   "OPEN_COMMAND",
                   "SOCKET_OPTIONS",
                   "IP_OPTIONS",
                   "TCP_OPTONS",
                   ]
from xpra.platform import platform_import
platform_import(globals(), "features", False,
                *_features_list_)


def main():
    from xpra.util import print_nested_dict
    from xpra.platform import program_context
    with program_context("Features-Info", "Features Info"):
        d = {}
        for k in _features_list_:
            d[k] = globals()[k]
        print_nested_dict(d)


if __name__ == "__main__":
    main()
