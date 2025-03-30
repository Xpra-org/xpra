# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_client_base_classes() -> tuple[type, ...]:
    from xpra.client.base.client import XpraClientBase
    from xpra.client.base import features

    CLIENT_BASES: list[type] = [XpraClientBase]
    if features.display:
        from xpra.client.mixins.display import DisplayClient
        CLIENT_BASES.append(DisplayClient)
    if features.windows:
        from xpra.client.mixins.windows import WindowClient
        CLIENT_BASES.append(WindowClient)
        if features.cursors:
            from xpra.client.mixins.cursors import CursorClient
            CLIENT_BASES.append(CursorClient)
    if features.webcam:
        from xpra.client.mixins.webcam import WebcamForwarder
        CLIENT_BASES.append(WebcamForwarder)
    if features.audio:
        from xpra.client.mixins.audio import AudioClient
        CLIENT_BASES.append(AudioClient)
    if features.clipboard:
        from xpra.client.mixins.clipboard import ClipboardClient
        CLIENT_BASES.append(ClipboardClient)
    if features.notifications:
        from xpra.client.mixins.notification import NotificationClient
        CLIENT_BASES.append(NotificationClient)
    if features.mmap:
        from xpra.client.mixins.mmap import MmapClient
        CLIENT_BASES.append(MmapClient)
    if features.logging:
        from xpra.client.mixins.logging import RemoteLogging
        CLIENT_BASES.append(RemoteLogging)
    if features.network_state:
        from xpra.client.mixins.network_state import NetworkState
        CLIENT_BASES.append(NetworkState)
    if features.network_listener:
        from xpra.client.mixins.network_listener import NetworkListener
        CLIENT_BASES.append(NetworkListener)
    if features.encoding:
        from xpra.client.mixins.encodings import Encodings
        CLIENT_BASES.append(Encodings)
    if features.tray:
        from xpra.client.mixins.tray import TrayClient
        CLIENT_BASES.append(TrayClient)

    return tuple(CLIENT_BASES)
