# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.common import FULL_INFO
from xpra.util.str_fn import csv
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
progress = True
encryption = True
server_info = True
server_events = True
challenge = True
info = True


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
    features.webcam = bo(opts.webcam) and icheck("xpra.codecs") and icheck("xpra.webcam")
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
    features.progress = b(opts.splash)
    features.encryption = bool(opts.encryption) and b(opts.encryption)
    features.server_info = envbool("XPRA_SERVER_INFO", True)
    features.server_events = envbool("XPRA_SERVER_EVENTS", True)
    features.challenge = b(opts.challenge_handlers) and csv(opts.challenge_handlers) != "none"
    features.info = FULL_INFO > 0

    if impwarn:
        import sys
        from xpra.log import Logger
        log = Logger("util", "subsystems")
        log.warn("Warning missing modules: %s", csv(impwarn))
        log.warn(f" for Python {sys.version}")

    if envbool("XPRA_ENFORCE_FEATURES", True):
        enforce_client_features()


def enforce_client_features() -> None:
    from xpra.util.pysystem import enforce_features, may_block_numpy
    from xpra.client.base import features
    enforce_features(features, {
        "debug": "xpra.client.base.debug",
        "control": "xpra.control,xpra.client.base.control",
        "file": "xpra.net.file_transfer,xpra.client.base.file",
        "printer": "xpra.client.base.printer",
        "display": "xpra.client.subsystem.display",
        "window": "xpra.client.subsystem.window",
        "cursor": "xpra.client.subsystem.cursor",
        "gstreamer": "gi.repository.Gst,xpra.gstreamer,xpra.codecs.gstreamer",
        "x11": "xpra.x11,gi.repository.GdkX11",
        "webcam": "xpra.webcam,xpra.client.subsystem.webcam",
        "audio": "xpra.audio,xpra.client.subsystem.audio",
        "clipboard": "xpra.clipboard,xpra.client.subsystem.clipboard",
        "keyboard": "xpra.keyboard,xpra.client.subsystem.keyboard",
        "pointer": "xpra.client.subsystem.pointer",
        "notification": "xpra.notification,xpra.client.subsystem.notification",
        "dbus": "dbus,xpra.dbus",
        "mmap": "mmap,xpra.net.mmap,xpra.client.subsystem.mmap",
        "ssl": "ssl,xpra.net.tls",
        "ssh": "paramiko,xpra.net.ssh",
        "logging": "xpra.client.subsystem.logging",
        "tray": "xpra.client.subsystem.tray",
        "ping": "xpra.client.subsystem.ping",
        "bandwidth": "xpra.client.subsystem.bandwidth",
        "socket": "xpra.client.subsystem.socket",
        "ssh_agent": "xpra.client.subssytem.ssh_agent",
        "encoding": "xpra.client.subsystem.encodings",
        "native": "xpra.platform.client",
        "power": "xpra.client.subsystem.power",
        "progress": "xpra.client.base.progress",
        "encryption": "xpra.client.base.aes",
        "server_info": "xpra.client.base.server_info",
        "server_events": "xpra.client.base.events",
    })
    may_block_numpy()
