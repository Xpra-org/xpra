# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

SYSTEM_TRAY_SUPPORTED = True
REINIT_WINDOWS = True

# we access the GUI when running as a server (tray, etc)
# and so we cannot daemonize
CAN_DAEMONIZE = False

CLIPBOARDS=["CLIPBOARD"]
CLIPBOARD_WANT_TARGETS = True
CLIPBOARD_GREEDY = True
CLIPBOARD_NATIVE_CLASS = "xpra.platform.darwin.osx_clipboard.OSXClipboardProtocolHelper"

OPEN_COMMAND = ["open"]
UI_THREAD_POLLING = 500    #poll every 500 ms

DEFAULT_SSH_COMMAND = "ssh"
