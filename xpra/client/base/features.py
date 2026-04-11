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
ssl_upgrade = True
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


def set_client_features(opts) -> None:
    from xpra.os_util import WIN32, OSX
    from importlib.util import find_spec
    from xpra.util.parsing import FALSE_OPTIONS, OFF_OPTIONS

    def b(v) -> bool:
        return str(v).lower() not in FALSE_OPTIONS

    def bo(v) -> bool:
        return str(v).lower() not in FALSE_OPTIONS or str(v).lower() in OFF_OPTIONS

    impwarn: set[str] = set()

    def icheck(mod: str, warn=True) -> bool:
        if find_spec(mod):
            return True
        if (mod not in impwarn) and warn:
            impwarn.add(mod)
        return False

    from xpra.client.base import features
    features.debug = features.debug or b(opts.debug)
    features.command = opts.commands
    features.control = opts.control
    features.file = b(opts.file_transfer) and icheck("xpra.net.file_transfer")
    features.printer = features.file and b(opts.printing)
    features.display = opts.windows
    features.window = opts.windows
    features.cursor = opts.windows and opts.cursors
    features.gstreamer = opts.gstreamer
    features.x11 = opts.backend in ("x11", "auto") and icheck("xpra.x11", not (WIN32 or OSX))
    features.audio = features.gstreamer and b(opts.audio) and (bo(opts.speaker) or bo(opts.microphone)) and icheck("xpra.audio")
    features.webcam = bo(opts.webcam) and icheck("xpra.codecs")
    features.clipboard = b(opts.clipboard) and icheck("xpra.clipboard")
    features.keyboard = icheck("xpra.keyboard")
    features.pointer = b(opts.pointer)
    features.notification = opts.notifications and icheck("xpra.notification")
    features.dbus = b(opts.dbus) and icheck("dbus") and icheck("xpra.dbus")
    features.mmap = b(opts.mmap) and icheck("xpra.net.mmap")
    features.ssl = b(opts.ssl) and icheck("ssl")
    features.ssl_upgrade = features.ssl and opts.ssl_upgrade is not None and b(opts.ssl_upgrade)
    features.ssh = b(opts.ssh)
    features.logging = b(opts.remote_logging)
    features.tray = b(opts.tray)
    from xpra.net.common import BACKWARDS_COMPATIBLE
    features.ping = BACKWARDS_COMPATIBLE or b(opts.pings)
    features.bandwidth = b(opts.bandwidth_detection) or b(opts.bandwidth_limit)
    features.ssh_agent = envbool("XPRA_SSH_AGENT", True)
    features.socket = envbool("XPRA_CLIENT_BIND_SOCKETS", True) and opts.bind != "none"
    features.encoding = opts.windows
    features.native = envbool("XPRA_CLIENT_NATIVE_BINDINGS", True)
    features.power = envbool("XPRA_POWER_EVENTS", True)

    if impwarn:
        import sys
        from xpra.util.str_fn import csv
        from xpra.log import Logger
        log = Logger("util")
        log.warn("Warning missing modules: %s", csv(impwarn))
        log.warn(f" for Python {sys.version}")
