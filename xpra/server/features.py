# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util.debug import CPUINFO, DETECT_MEMLEAKS, DETECT_FDLEAKS

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


def set_server_features(opts, mode: str) -> None:
    from xpra.os_util import POSIX, WIN32, OSX
    from xpra.util.env import envbool
    from xpra.util.parsing import FALSE_OPTIONS
    from xpra.net.common import BACKWARDS_COMPATIBLE

    def b(v) -> bool:
        return str(v).lower() not in FALSE_OPTIONS

    missing: set[str] = set()
    from importlib.util import find_spec

    def impcheck(*modules) -> bool:
        for mod in modules:
            if find_spec(f"xpra.{mod}"):
                continue
            missing.add(mod)
            return False
        return True

    # turn off some server subsystem:
    from xpra.server import features
    features.http = opts.http and impcheck("net.http")
    features.control = opts.control and impcheck("net.control")
    features.mmap = b(opts.mmap) and impcheck("net.mmap")
    features.ssl = b(opts.ssl)
    features.dbus = b(opts.dbus) and bool(find_spec("dbus")) and impcheck("dbus", "server.dbus")
    features.encoding = impcheck("codecs")
    features.shell = opts.shell
    features.watcher = envbool("XPRA_UI_THREAD_WATCHER", True)

    if mode in ("encoder", "runner"):
        # turn off all relevant features:
        opts.start_new_commands = mode == "runner"
        features.command = mode == "runner"
        features.notification = features.webcam = features.clipboard = False
        features.gstreamer = features.x11 = features.pulseaudio = features.audio = features.av_sync = False
        features.file = features.printer = features.mdns = False
        features.keyboard = features.pointer = False
        features.logging = features.display = features.window = False
        features.cursor = features.rfb = False
        features.power = features.suspend = features.idle = False
        features.ssh = features.gtk = features.tray = features.opengl = False
        features.bell = features.systray = False
    else:
        if opts.backend == "x11" or mode in ("desktop", "monitor", "expand"):
            x11 = True
        elif mode == "shadow":
            x11 = POSIX
        elif mode == "seamless":
            x11 = opts.backend == "auto"
        else:
            x11 = False
        features.debug = features.debug or b(opts.debug)
        features.command = opts.commands
        features.mdns = opts.mdns and impcheck("net.mdns")
        features.notification = (features.dbus or WIN32 or OSX) and opts.notifications and impcheck("notification")
        features.webcam = b(opts.webcam) and impcheck("codecs") and impcheck("webcam")
        features.clipboard = b(opts.clipboard) and impcheck("clipboard")
        features.gstreamer = b(opts.gstreamer) and impcheck("gstreamer")
        features.x11 = x11 and impcheck("x11")
        features.audio = features.gstreamer and b(opts.audio) and impcheck("audio")
        features.pulseaudio = features.audio and b(opts.pulseaudio) and impcheck("audio.pulseaudio")
        features.av_sync = features.audio and b(opts.av_sync)
        features.file = b(opts.file_transfer) or b(opts.printing)
        features.printer = b(opts.printing)
        features.keyboard = not opts.readonly and impcheck("keyboard")
        features.pointer = not opts.readonly
        features.logging = b(opts.remote_logging)
        features.window = opts.windows and impcheck("codecs")
        features.display = features.window or features.keyboard or features.pointer
        features.cursor = features.display and opts.cursors
        features.rfb = b(opts.rfb_upgrade) and impcheck("server.rfb") and mode in ("desktop", "shadow")
        features.ssh = b(opts.ssh) and impcheck("net.ssh", "server.ssh") and bool(find_spec("paramiko"))
        features.ping = BACKWARDS_COMPATIBLE or b(opts.pings)
        features.bandwidth = b(opts.bandwidth_detection) or b(opts.bandwidth_limit)
        features.power = envbool("XPRA_POWER_EVENTS", True)
        features.suspend = envbool("XPRA_SUSPEND_RESUME", True)
        features.idle = opts.server_idle_timeout > 0
        features.gtk = mode not in ("desktop", "monitor", "seamless") or opts.backend.lower() == "gtk"
        features.tray = features.gtk and b(opts.tray) and mode == "shadow"
        features.opengl = features.display and b(opts.opengl) and impcheck("opengl")
        features.bell = features.display and b(opts.bell)
        features.systray = b(opts.system_tray) and mode == "seamless"

    if missing:
        import sys
        from xpra.util.str_fn import csv
        from xpra.log import Logger
        log = Logger("util")
        log.warn("Warning: missing modules: %s", csv(missing))
        log.warn(f" for Python {sys.version}")

    if envbool("XPRA_ENFORCE_FEATURES", True):
        enforce_server_features()


def enforce_server_features() -> None:
    """
    Prevent the modules from being imported later
    """
    from xpra.os_util import OSX
    from xpra.util.pysystem import enforce_features, may_block_numpy
    from xpra.server import features
    enforce_features(features, {
        "debug": "xpra.server.subsystem.debug",
        "power": "xpra.server.subsystem.power",
        "suspend": "xpra.server.subsystem.suspend",
        "idle": "xpra.server.subsystem.idle",
        "control": "xpra.net.control,xpra.server.subsystem.controlcommands",
        "mdns": "xpra.net.mdns,xpra.xpra.server.subsystem.mdns",
        "command": "xpra.server.subsystem.child_command",
        "notification": "xpra.notification,xpra.server.subsystem.notification,xpra.server.source.notification",
        "webcam": "xpra.webcam,xpra.server.subsystem.webcam,xpra.server.source.webcam",
        "clipboard": "xpra.clipboard,xpra.server.subsystem.clipboard,xpra.server.source.clipboard",
        "audio": "xpra.audio,xpra.server.subsystem.audio,xpra.server.source.audio",
        "pulseaudio": "xpra.server.subsystem.pulseaudio",
        # "av_sync": "??",
        "file": "xpra.server.subsystem.file,xpra.server.source.file",
        "printer": "xpra.server.subsystem.printer,xpra.server.source.printer",
        "mmap": "xpra.net.mmap,xpra.server.subsystem.mmap,xpra.server.source.mmap",
        "ssl": "ssl,xpra.net.tls",
        "ssh": "paramiko,xpra.net.ssh,xpra.server.subsystem.ssh_agent",
        "keyboard": "xpra.server.subsystem.keyboard,xpra.server.source.keyboard",
        "pointer": "xpra.server.subsystem.pointer,xpra.server.source.pointer",
        "gstreamer": "gi.repository.Gst,xpra.gstreamer,xpra.codecs.gstreamer",
        "x11": "xpra.x11,gi.repository.GdkX11",
        "dbus": "xpra.dbus,xpra.server.dbus,xpra.server.source.dbus",
        "encoding": "xpra.server.subsystem.encoding,xpra.server.source.encodings",
        "logging": "xpra.server.subsystem.logging",
        "ping": "xpra.server.subsystem.ping,xpra.server.source.ping",
        "bandwidth": "xpra.server.subsystem.bandwidth,xpra.server.source.bandwidth",
        "shell": "xpra.server.subsystem.shell,xpra.server.source.shell",
        "display": "xpra.server.subsystem.display,xpra.server.source.display",
        "window": "xpra.server.subsystem.window,xpra.server.source.window",
        "cursor": "xpra.server.subsystem.cursor,xpra.server.source.cursor",
        "rfb": "xpra.net.rfb,xpra.server.rfb",
        "http": "xpra.net.http,xpra.server.subsystem.http",
        "tray": "xpra.server.subsystem.tray",
        "gtk": "xpra.gtk" if not OSX else "",
        "systray": "xpra.x11.subsystem.systray",
    })
    if not features.gtk:
        from xpra.scripts.main import no_gi_gtk_modules
        no_gi_gtk_modules()
    may_block_numpy()
