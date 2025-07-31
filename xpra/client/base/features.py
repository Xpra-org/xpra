# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.env import envbool

DETECT_LEAKS = envbool("XPRA_DETECT_LEAKS", False)

debug = DETECT_LEAKS
command = True
control = True
file = True
printer = True
display = True
window = True
cursor = True
gstreamer = True
x11 = True
webcam = True
audio = True
clipboard = True
keyboard = True
pointer = True
notification = True
dbus = True
mmap = True
ssl = True
ssh = True
logging = True
tray = True
ping = True
bandwidth = True
socket = True
ssh_agent = True
encoding = True
native = True
power = True
