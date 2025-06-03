# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_client_base_classes() -> tuple[type, ...]:
    from xpra.client.base import features
    from xpra.client.base.glib_adapter import GLibClient
    from xpra.client.base.serverinfo import ServerInfoMixin
    from xpra.client.base.network import NetworkClient
    from xpra.client.base.aes import AESClient
    from xpra.client.base.progress import ProgressClient
    from xpra.client.base.challenge import ChallengeClient
    CLIENT_BASES: list[type] = [GLibClient, NetworkClient, ServerInfoMixin, AESClient, ProgressClient, ChallengeClient]
    if features.debug:
        from xpra.client.base.debug import DebugClient
        CLIENT_BASES.append(DebugClient)
    if features.file:
        from xpra.client.base.file import FileMixin
        CLIENT_BASES.append(FileMixin)
    if features.printer:
        from xpra.client.base.printer import PrinterMixin
        CLIENT_BASES.append(PrinterMixin)
    if features.control:
        from xpra.client.base.control import ControlClient
        CLIENT_BASES.append(ControlClient)
    from xpra.net.common import SSL_UPGRADE
    if SSL_UPGRADE:
        from xpra.client.base.ssl_upgrade import SSLUpgradeClient
        CLIENT_BASES.append(SSLUpgradeClient)
    return tuple(CLIENT_BASES)
