# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_client_subsystems() -> tuple[type, ...]:
    from xpra.client.base import features
    from xpra.client.base.network import NetworkClient
    from xpra.client.base.clientid import IDClient
    subsystems: list[type] = [NetworkClient, IDClient]
    if features.info:
        from xpra.client.base.clientinfo import InfoClient
        subsystems.append(InfoClient)
    if features.challenge:
        from xpra.client.base.challenge import ChallengeClient
        subsystems.append(ChallengeClient)
    if features.server_events:
        from xpra.client.base.events import EventsClient
        subsystems.append(EventsClient)
    if features.server_info:
        from xpra.client.base.serverinfo import ServerInfoMixin
        subsystems.append(ServerInfoMixin)
    if features.encryption:
        from xpra.client.base.aes import AESClient
        subsystems.append(AESClient)
    if features.progress:
        from xpra.client.base.progress import ProgressClient
        subsystems.append(ProgressClient)
    if features.debug:
        from xpra.client.base.debug import DebugClient
        subsystems.append(DebugClient)
    if features.file:
        from xpra.client.base.file import FileMixin
        subsystems.append(FileMixin)
    if features.printer:
        from xpra.client.base.printer import PrinterMixin
        subsystems.append(PrinterMixin)
    if features.control:
        from xpra.client.base.control import ControlClient
        subsystems.append(ControlClient)
    if features.ssl_upgrade:
        from xpra.client.base.ssl_upgrade import SSLUpgradeClient
        subsystems.append(SSLUpgradeClient)
    return tuple(subsystems) or (object, )
