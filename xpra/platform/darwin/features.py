# This file is part of Xpra.
# Copyright (C) 2011-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

REINIT_WINDOWS = True

# we access the GUI when running as a server (tray, etc)
# and so we cannot daemonize
CAN_DAEMONIZE = False

CLIPBOARDS=["CLIPBOARD"]
CLIPBOARD_WANT_TARGETS = True
CLIPBOARD_GREEDY = True

OPEN_COMMAND = ["open"]

#DEFAULT_SSH_COMMAND = "ssh"

COMMAND_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGKILL", "SIGUSR1", "SIGUSR2")
