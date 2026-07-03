# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_client_subsystems() -> tuple[type, ...]:
    from xpra.client.base import features
    from xpra.client.base.network import Network
    from xpra.client.base.clientid import ClientID
    subsystems: list[type] = [Network, ClientID]
    if features.info:
        from xpra.client.base.clientinfo import ClientInfo
        subsystems.append(ClientInfo)
    if features.challenge:
        from xpra.client.base.challenge import Challenge
        subsystems.append(Challenge)
    if features.server_events:
        from xpra.client.base.events import Events
        subsystems.append(Events)
    if features.server_info:
        from xpra.client.base.remoteinfo import RemoteInfo
        subsystems.append(RemoteInfo)
    if features.encryption:
        from xpra.client.base.aes import AES
        subsystems.append(AES)
    if features.progress:
        from xpra.client.base.progress import Progress
        subsystems.append(Progress)
    if features.debug:
        from xpra.client.base.debug import Debug
        subsystems.append(Debug)
    if features.file:
        from xpra.client.base.file import File
        subsystems.append(File)
    if features.printer:
        from xpra.client.base.printer import Printer
        subsystems.append(Printer)
    if features.control:
        from xpra.client.base.control import Control
        subsystems.append(Control)
    if features.ssl_upgrade:
        from xpra.client.base.ssl_upgrade import SSLUpgrade
        subsystems.append(SSLUpgrade)
    return tuple(subsystems) or (object, )
