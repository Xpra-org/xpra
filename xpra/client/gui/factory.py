# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_client_subsystems() -> tuple[type, ...]:
    from xpra.client.base import features

    from xpra.client.subsystem.server_info import ServerInfoClient
    subsystems: list[type] = [ServerInfoClient]
    if features.display:
        from xpra.client.subsystem.display import DisplayClient
        subsystems.append(DisplayClient)
    if features.opengl:
        from xpra.client.subsystem.opengl import OpenGLClient
        subsystems.append(OpenGLClient)
    if features.window:
        from xpra.client.subsystem.window import WindowClient
        subsystems.append(WindowClient)
        if features.cursor:
            from xpra.client.subsystem.cursor import CursorClient
            subsystems.append(CursorClient)
        if features.pointer:
            from xpra.os_util import POSIX, OSX
            if POSIX and not OSX:
                from xpra.client.subsystem.xi2 import XI2Client
                subsystems.append(XI2Client)
    if features.webcam:
        from xpra.client.subsystem.webcam import WebcamForwarder
        subsystems.append(WebcamForwarder)
    if features.audio:
        from xpra.client.subsystem.audio import AudioClient
        subsystems.append(AudioClient)
    if features.clipboard:
        from xpra.client.subsystem.clipboard import ClipboardClient
        subsystems.append(ClipboardClient)
    if features.keyboard:
        from xpra.client.subsystem.keyboard import KeyboardClient
        subsystems.append(KeyboardClient)
    if features.pointer:
        from xpra.client.subsystem.pointer import PointerClient
        subsystems.append(PointerClient)
    if features.notification:
        from xpra.client.subsystem.notification import NotificationClient
        subsystems.append(NotificationClient)
    if features.mmap:
        from xpra.client.subsystem.mmap import MmapClient
        subsystems.append(MmapClient)
    if features.logging:
        from xpra.client.subsystem.logging import LoggingClient
        subsystems.append(LoggingClient)
    if features.ssh:
        from xpra.client.subsystem.ssh_agent import SSHAgentClient
        subsystems.append(SSHAgentClient)
    if features.socket:
        from xpra.client.subsystem.socket import NetworkListener
        subsystems.append(NetworkListener)
    if features.ping:
        from xpra.client.subsystem.ping import PingClient
        subsystems.append(PingClient)
    if features.gsettings:
        from xpra.client.subsystem.gsettings import GSettingsClient
        subsystems.append(GSettingsClient)
    if features.bandwidth:
        from xpra.client.subsystem.bandwidth import BandwidthClient
        subsystems.append(BandwidthClient)
    if features.command:
        from xpra.client.subsystem.command import CommandClient
        subsystems.append(CommandClient)
    if features.encoding:
        from xpra.client.subsystem.encoding import Encodings
        subsystems.append(Encodings)
    if features.tray:
        from xpra.client.subsystem.tray import TrayClient
        subsystems.append(TrayClient)
    if features.power:
        from xpra.client.subsystem.power import PowerEventClient
        subsystems.append(PowerEventClient)

    return tuple(subsystems)
