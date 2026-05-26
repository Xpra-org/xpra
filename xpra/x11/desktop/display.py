# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.net.common import Packet
from xpra.net.compression import Compressed
from xpra.server.common import make_icon_packet
from xpra.util.system import get_platform_icon_name
from xpra.x11.error import xsync
from xpra.x11.subsystem.display import X11DisplayManager
from xpra.log import Logger

log = Logger("server")


class XpraDesktopDisplayManager(X11DisplayManager):
    """
    X11 display subsystem for desktop and monitor servers.
    """

    def __init__(self, server=None):
        super().__init__(server)
        # Desktop variants expose a fixed virtual monitor meant to match a real
        # display, not the giant seamless canvas used as the X11 default.
        self.default_resolution = "1920x1080"
        self.mirror_client_layout = False

    def parse_screen_info(self, ss):
        return self.do_parse_screen_info(ss, ss.desktop_mode_size)

    def notify_dpi_warning(self, body) -> None:
        """ ignore DPI warnings in desktop mode """

    def do_make_screenshot_packet(self) -> Packet:
        log("grabbing screenshot")
        regions = []
        offset_x, offset_y = 0, 0
        for window in sorted(self.get_subsystem("window").models(), key=lambda w: w.get_xid(), reverse=True):
            wid = window.get_xid()
            log("screenshot: window(%s)=%s", wid, window)
            if not window.is_managed():
                log("screenshot: window %s is not/no longer managed", wid)
                continue
            x, y, w, h = window.get_geometry()
            log("screenshot: geometry(%s)=%s", window, (x, y, w, h))
            try:
                with xsync:
                    img = window.get_image(0, 0, w, h)
            except Exception:
                log.warn("screenshot: window %s could not be captured", wid)
                continue
            if img is None:
                log.warn("screenshot: no pixels for window %s", wid)
                continue
            log("screenshot: image=%s, size=%s", img, img.get_size())
            if img.get_pixel_format() not in ("RGB", "RGBA", "XRGB", "BGRX", "ARGB", "BGRA"):
                log.warn("window pixels for window %s using an unexpected rgb format: %s", wid, img.get_pixel_format())
                continue
            regions.append((wid, offset_x + x, offset_y + y, img))
            # tile them horizontally:
            offset_x += w
        from xpra.codecs.screenshot import make_screenshot_packet_from_regions
        return Packet(*make_screenshot_packet_from_regions(regions))

    @staticmethod
    def do_make_icon_packet() -> tuple[str, int, int, str, int, Compressed]:
        return make_icon_packet(get_platform_icon_name(sys.platform), "display.png", "server.png", "xpra.png")
