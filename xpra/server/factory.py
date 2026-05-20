# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_server_base_classes() -> tuple[type, ...]:
    from xpra.server import features
    from xpra.server.core import ServerCore
    classes: list[type] = [ServerCore]
    # this should only be enabled for desktop and shadow servers:
    if features.rfb:
        from xpra.server.rfb.server import RFBServer
        classes.append(RFBServer)
    return tuple(classes)
