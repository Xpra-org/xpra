# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_server_base_classes() -> tuple[type, ...]:
    from xpra.server import features
    from xpra.server.core import ServerCore
    classes: list[type] = [ServerCore]
    if features.dbus:
        from xpra.server.mixins.dbus import DbusServer
        classes.append(DbusServer)
    if features.control:
        from xpra.server.mixins.controlcommands import ServerBaseControlCommands
        classes.append(ServerBaseControlCommands)
    if features.notifications:
        from xpra.server.mixins.notification import NotificationForwarder
        classes.append(NotificationForwarder)
    if features.webcam:
        from xpra.server.mixins.webcam import WebcamServer
        classes.append(WebcamServer)
    if features.clipboard:
        from xpra.server.mixins.clipboard import ClipboardServer
        classes.append(ClipboardServer)
    if features.audio:
        from xpra.server.mixins.audio import AudioServer
        classes.append(AudioServer)
    if features.fileprint:
        from xpra.server.mixins.fileprint import FilePrintServer
        classes.append(FilePrintServer)
    if features.mmap:
        from xpra.server.mixins.mmap import MMAP_Server
        classes.append(MMAP_Server)
    if features.input_devices:
        from xpra.server.mixins.input import InputServer
        classes.append(InputServer)
    if features.encoding:
        from xpra.server.mixins.encoding import EncodingServer
        classes.append(EncodingServer)
    if features.logging:
        from xpra.server.mixins.logging import LoggingServer
        classes.append(LoggingServer)
    if features.network_state:
        from xpra.server.mixins.networkstate import NetworkStateServer
        classes.append(NetworkStateServer)
    if features.ssh:
        from xpra.server.mixins.ssh_agent import SshAgent
        classes.append(SshAgent)
    if features.http:
        from xpra.server.mixins.http import HttpServer
        classes.append(HttpServer)
    if features.shell:
        from xpra.server.mixins.shell import ShellServer
        classes.append(ShellServer)
    if features.display:
        from xpra.server.mixins.display import DisplayManager
        classes.append(DisplayManager)
    if features.cursors:
        from xpra.server.mixins.cursors import CursorManager
        classes.append(CursorManager)
    if features.windows:
        from xpra.server.mixins.window import WindowServer
        classes.append(WindowServer)
    if features.commands:
        from xpra.server.mixins.child_command import ChildCommandServer
        classes.append(ChildCommandServer)
    return tuple(classes)
