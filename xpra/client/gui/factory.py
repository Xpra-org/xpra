# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_client_base_classes() -> tuple[type, ...]:
    from xpra.client.base.client import XpraClientBase
    from xpra.client.base import features

    CLIENT_BASES: list[type] = [XpraClientBase]
    if features.display:
        from xpra.client.subsystem.display import DisplayClient
        CLIENT_BASES.append(DisplayClient)
    if features.windows:
        from xpra.client.subsystem.windows import WindowClient
        CLIENT_BASES.append(WindowClient)
        if features.cursors:
            from xpra.client.subsystem.cursors import CursorClient
            CLIENT_BASES.append(CursorClient)
    if features.webcam:
        from xpra.client.subsystem.webcam import WebcamForwarder
        CLIENT_BASES.append(WebcamForwarder)
    if features.audio:
        from xpra.client.subsystem.audio import AudioClient
        CLIENT_BASES.append(AudioClient)
    if features.clipboard:
        from xpra.client.subsystem.clipboard import ClipboardClient
        CLIENT_BASES.append(ClipboardClient)
    if features.keyboard:
        from xpra.client.subsystem.keyboard import KeyboardClient
        CLIENT_BASES.append(KeyboardClient)
    if features.pointer:
        from xpra.client.subsystem.pointer import PointerClient
        CLIENT_BASES.append(PointerClient)
    if features.notifications:
        from xpra.client.subsystem.notification import NotificationClient
        CLIENT_BASES.append(NotificationClient)
    if features.mmap:
        from xpra.client.subsystem.mmap import MmapClient
        CLIENT_BASES.append(MmapClient)
    if features.logging:
        from xpra.client.subsystem.logging import RemoteLogging
        CLIENT_BASES.append(RemoteLogging)
    if features.network_state:
        from xpra.client.subsystem.network_state import NetworkState
        CLIENT_BASES.append(NetworkState)
    if features.network_listener:
        from xpra.client.subsystem.network_listener import NetworkListener
        CLIENT_BASES.append(NetworkListener)
    if features.commands:
        from xpra.client.subsystem.child_command import CommandClient
        CLIENT_BASES.append(CommandClient)
    if features.encoding:
        from xpra.client.subsystem.encodings import Encodings
        CLIENT_BASES.append(Encodings)
    if features.tray:
        from xpra.client.subsystem.tray import TrayClient
        CLIENT_BASES.append(TrayClient)

    if features.native:
        try:
            from xpra.platform.client import PlatformClient
            CLIENT_BASES.append(PlatformClient)
        except ImportError:
            pass

    return tuple(CLIENT_BASES)
