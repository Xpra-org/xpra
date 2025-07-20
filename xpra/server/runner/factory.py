# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_server_base_class() -> type:
    from xpra.server import features
    # disable a bunch of things we're not using:
    features.power = features.suspend = features.idle = False
    # features.ping = auto
    features.bandwidth = features.control = False
    # features.debug = auto
    features.file = features.printer = False
    # features.mmap = auto
    features.logging = features.http = features.shell = features.ssh = features.webcam = False
    # features.dbus = auto
    features.display = False
    features.notification = features.clipboard = features.keyboard = features.pointer = False
    features.audio = features.pulseaudio = False
    features.encoding = features.cursor = features.window = False
    features.command = True

    from xpra.server.base import ServerBase
    return ServerBase
