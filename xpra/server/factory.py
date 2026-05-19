# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_server_base_classes() -> tuple[type, ...]:
    from xpra.server import features
    from xpra.server.core import ServerCore
    classes: list[type] = [ServerCore]
    if features.gtk:
        if features.x11:
            from xpra.x11.subsystem.gtk import GtkX11Server
            classes.append(GtkX11Server)
        else:
            from xpra.server.subsystem.gtk import GTKServer
            classes.append(GTKServer)
    elif features.x11:
        from xpra.x11.subsystem.x11init import X11Init
        classes.append(X11Init)
    # this should only be enabled for desktop and shadow servers:
    if features.rfb:
        from xpra.server.rfb.server import RFBServer
        classes.append(RFBServer)
    return tuple(classes)
