# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.compression import Compressed
from xpra.server.common import make_icon_packet
from xpra.x11.shadow.display import X11ShadowDisplayManager


class ExpandDisplayManager(X11ShadowDisplayManager):
    """
    Display subsystem for expand servers.
    """

    def do_make_screenshot_packet(self):
        raise NotImplementedError()

    @staticmethod
    def do_make_icon_packet() -> tuple[str, int, int, str, int, Compressed]:
        return make_icon_packet("scaling.png", "shadow.png", "server.png", "xpra.png")
