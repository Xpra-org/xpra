# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.base import ServerBase
from xpra.log import Logger

log = Logger("x11", "server")


class X11ServerCore(ServerBase):
    """
        Base class for X11 servers,
        adds X11 specific methods to ServerBase.
        (see XpraServer or XpraX11ShadowServer for actual implementations)
    """

    def get_ui_info(self, proto, wids=None, *args) -> dict[str, Any]:
        info = super().get_ui_info(proto, wids, *args)
        sinfo = info.setdefault("server", {})
        try:
            from xpra.x11.composite import CompositeHelper
            sinfo["XShm"] = CompositeHelper.XShmEnabled
        except (ImportError, ValueError) as e:
            log("no composite: %s", e)
        return info

    def get_window_info(self, window) -> dict[str, Any]:
        info = super().get_window_info(window)
        info["XShm"] = window.uses_xshm()
        info["geometry"] = window.get_geometry()
        return info
