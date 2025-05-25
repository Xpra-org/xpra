# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_server_base_classes() -> tuple[type, ...]:
    from xpra.server import features
    from xpra.server.core import ServerCore
    classes: list[type] = [ServerCore]
    # `Ping`, `Bandwidth` and `ControlComands` don't have any dependencies:
    if features.ping:
        from xpra.server.subsystem.ping import PingServer
        classes.append(PingServer)
    if features.bandwidth:
        from xpra.server.subsystem.bandwidth import BandwidthServer
        classes.append(BandwidthServer)
    if features.control:
        from xpra.server.subsystem.controlcommands import ServerBaseControlCommands
        classes.append(ServerBaseControlCommands)
    if features.debug:
        from xpra.server.subsystem.debug import DebugServer
        classes.append(DebugServer)
    if features.fileprint:
        from xpra.server.subsystem.fileprint import FilePrintServer
        classes.append(FilePrintServer)
    if features.mmap:
        from xpra.server.subsystem.mmap import MMAP_Server
        classes.append(MMAP_Server)
    if features.logging:
        from xpra.server.subsystem.logging import LoggingServer
        classes.append(LoggingServer)
    if features.http:
        from xpra.server.subsystem.http import HttpServer
        classes.append(HttpServer)
    if features.shell:
        from xpra.server.subsystem.shell import ShellServer
        classes.append(ShellServer)
    if features.ssh:
        from xpra.server.subsystem.ssh_agent import SshAgent
        classes.append(SshAgent)
    if features.webcam:
        from xpra.server.subsystem.webcam import WebcamServer
        classes.append(WebcamServer)

    # `Dbus` must be placed before `Power`, `DisplayServer` and `NotificationForwarder`
    if features.dbus:
        from xpra.server.subsystem.dbus import DbusServer
        classes.append(DbusServer)
    if features.power:
        # this one is for server-side system power events:
        from xpra.server.subsystem.power import PowerEventServer
        classes.append(PowerEventServer)
    if features.suspend:
        # and this one for processing power event messages from the client:
        from xpra.server.subsystem.suspend import SuspendServer
        classes.append(SuspendServer)
    if features.display:
        from xpra.server.subsystem.display import DisplayManager
        classes.append(DisplayManager)
    if features.notification:
        from xpra.server.subsystem.notification import NotificationForwarder
        classes.append(NotificationForwarder)
    if features.clipboard:
        from xpra.server.subsystem.clipboard import ClipboardServer
        classes.append(ClipboardServer)
    if features.audio:
        from xpra.server.subsystem.audio import AudioServer
        classes.append(AudioServer)
    if features.keyboard:
        from xpra.server.subsystem.keyboard import KeyboardServer
        classes.append(KeyboardServer)
    if features.pointer:
        from xpra.server.subsystem.pointer import PointerServer
        classes.append(PointerServer)
    if features.encoding:
        from xpra.server.subsystem.encoding import EncodingServer
        classes.append(EncodingServer)
    if features.cursor:
        from xpra.server.subsystem.cursor import CursorManager
        classes.append(CursorManager)
    if features.window:
        from xpra.server.subsystem.window import WindowServer
        classes.append(WindowServer)
    # this should be last so that the environment is fully prepared:
    if features.command:
        from xpra.server.subsystem.command import ChildCommandServer
        classes.append(ChildCommandServer)
    return tuple(classes)
