# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.net.packet_type import DISPLAY_SCREENSHOT
from xpra.net.compression import Compressed
from xpra.server.common import make_icon_packet, find_session_icon_filename
from xpra.server.subsystem.display import DisplayManager
from xpra.util.system import get_platform_icon_name
from xpra.log import Logger

log = Logger("shadow")


class ShadowDisplayMixin:
    def parse_screen_info(self, ss):
        try:
            log.info(" client root window size is %sx%s", *ss.desktop_size)
        except Exception:
            log.info(" unknown client desktop size")
        self.apply_refresh_rate(ss)
        return self.get_display_size()

    def apply_refresh_rate(self, ss) -> int:
        rrate = super().apply_refresh_rate(ss)
        if rrate > 0:
            self.server.set_refresh_delay(max(10, 1000 // rrate))
        return rrate

    def do_make_screenshot_packet(self) -> tuple[str, int, int, str, int, Compressed]:
        models = self.get_subsystem("window").models()
        assert len(models) == 1, "multi root window screenshot not implemented yet"
        rwm = models[0]
        w, h, encoding, rowstride, data = rwm.take_screenshot()
        assert encoding == "png"  # use fixed encoding for now
        return DISPLAY_SCREENSHOT, w, h, encoding, rowstride, Compressed(encoding, data)

    def do_make_icon_packet(self) -> tuple[str, int, int, str, int, Compressed]:
        return make_icon_packet(
            find_session_icon_filename(self.server),
            get_platform_icon_name(sys.platform), "shadow.png", "server.png", "xpra.png",
        )


class ShadowDisplayManager(ShadowDisplayMixin, DisplayManager):
    """
    Display subsystem for shadow servers.
    """
