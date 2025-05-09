# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


def get_server_base_classes() -> tuple[type, ...]:
    from xpra.server import features
    from xpra.server.core import ServerCore
    from xpra.server.glib_server import GLibServer
    classes: list[type] = [GLibServer, ServerCore]
    if features.dbus:
        from xpra.server.subsystem.dbus import DbusServer
        classes.append(DbusServer)
    if features.debug:
        from xpra.server.subsystem.debug import DebugServer
        classes.append(DebugServer)
    if features.http:
        from xpra.server.subsystem.http import HttpServer
        classes.append(HttpServer)
    if features.shell:
        from xpra.server.subsystem.shell import ShellServer
        classes.append(ShellServer)
    if features.display:
        from xpra.server.subsystem.display import DisplayManager
        classes.append(DisplayManager)
    if features.command:
        from xpra.server.subsystem.command import ChildCommandServer
        classes.append(ChildCommandServer)
    return tuple(classes)
