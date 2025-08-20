# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.common import DETECT_MEMLEAKS, DETECT_FDLEAKS, CPUINFO


debug = DETECT_MEMLEAKS or DETECT_FDLEAKS or CPUINFO
watcher = True
power = True
suspend = True
idle = True
control = True
mdns = True
notification = True
webcam = True
clipboard = True
audio = True
pulseaudio = True
av_sync = True
file = True
printer = True
mmap = True
ssl = True
ssh = True
keyboard = True
pointer = True
command = True
gstreamer = True
x11 = True
dbus = True
encoding = True
logging = True
ping = True
bandwidth = True
shell = False
display = True
window = True
cursor = True
rfb = True
http = True
gtk = True
tray = True
opengl = True
bell = True
systray = True
