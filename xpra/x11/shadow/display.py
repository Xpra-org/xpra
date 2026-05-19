# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.net.packet_type import DISPLAY_SCREENSHOT
from xpra.net.compression import Compressed
from xpra.server.common import make_icon_packet
from xpra.server.shadow.display import ShadowDisplayMixin
from xpra.util.system import get_platform_icon_name
from xpra.x11.subsystem.display import X11DisplayManager


class X11ShadowDisplayManager(ShadowDisplayMixin, X11DisplayManager):
    """
    X11 display subsystem for shadow servers.
    """

    def do_make_screenshot_packet(self) -> tuple[str, int, int, str, int, Compressed]:
        from xpra.x11.shadow.backends import setup_gtk_capture
        capture = setup_gtk_capture()
        w, h, encoding, rowstride, data = capture.take_screenshot()
        assert encoding == "png"  # use fixed encoding for now
        return DISPLAY_SCREENSHOT, w, h, encoding, rowstride, Compressed(encoding, data)

    @staticmethod
    def do_make_icon_packet() -> tuple[str, int, int, str, int, Compressed]:
        return make_icon_packet(get_platform_icon_name(sys.platform), "shadow.png", "server.png", "xpra.png")
