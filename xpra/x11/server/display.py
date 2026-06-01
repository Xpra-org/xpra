# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from PIL import Image

from xpra.net.common import Packet
from xpra.net.compression import Compressed
from xpra.net.packet_type import DISPLAY_ICON
from xpra.server.common import make_icon_packet, find_session_icon_filename
from xpra.util.str_fn import memoryview_to_bytes
from xpra.x11.error import xsync, XError
from xpra.x11.subsystem.display import X11DisplayManager
from xpra.log import Logger

log = Logger("server")


class X11SeamlessDisplayManager(X11DisplayManager):
    """
    X11 display subsystem for seamless servers.
    """

    def do_make_screenshot_packet(self) -> Packet:
        log("grabbing screenshot")
        regions = []
        OR_regions = []
        window_sub = self.get_subsystem("window")
        for window in window_sub.models():
            wid = window_sub.get_wid(window)
            log("screenshot: window(%s)=%s", wid, window)
            if not window.is_managed():
                log("screenshot: window %s is not/no longer managed", wid)
                continue
            x, y, w, h = window.get_property("geometry")[:4]
            log("screenshot: geometry(%s)=%s", window, (x, y, w, h))
            try:
                with xsync:
                    img = window.get_image(0, 0, w, h)
            except XError:
                log("%s.get_image%s", window, (0, 0, w, h), exc_info=True)
                log.warn("screenshot: window %s could not be captured", wid)
                continue
            if img is None:
                log.warn("screenshot: no pixels for window %s", wid)
                continue
            log("screenshot: image=%s, size=%s", img, img.get_size())
            if img.get_pixel_format() not in ("RGB", "RGBA", "XRGB", "BGRX", "ARGB", "BGRA"):
                log.warn("window pixels for window %s using an unexpected rgb format: %s", wid, img.get_pixel_format())
                continue
            item = (wid, x, y, img)
            if window.is_OR() or window.is_tray():
                OR_regions.append(item)
            elif window_sub._has_focus == wid:
                # window with focus first (drawn last)
                regions.insert(0, item)
            else:
                regions.append(item)
        log("screenshot: found regions=%s, OR_regions=%s", len(regions), len(OR_regions))
        from xpra.codecs.screenshot import make_screenshot_packet_from_regions
        return Packet(*make_screenshot_packet_from_regions(OR_regions + regions))

    def do_make_icon_packet(self) -> tuple[str, int, int, str, int, Compressed]:
        windows = self.get_subsystem("window").models()
        log.enable_debug()
        log("do_make_icon_packet() windows=%s", windows)
        size = 128
        pil_icons: list[Image.Image] = []
        for window in windows:
            icons = window.get_property("icons")
            if not icons:
                continue
            w, h, fmt, data = max(icons, key=lambda i: i[0] * i[1])
            log("got %s icon %ix%i for %s", fmt, w, h, window)
            if fmt != "BGRA":
                continue
            img = Image.frombytes("RGBA", (w, h), memoryview_to_bytes(data), "raw", "BGRA", w * 4, 1)
            pil_icons.append(img)

        if not pil_icons:
            return make_icon_packet(
                find_session_icon_filename(self.server),
                "server.png", "xpra.png",
            )

        def fit(img: Image.Image, box: int) -> Image.Image:
            iw, ih = img.size
            scale = min(box / iw, box / ih)
            nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
            return img.resize((nw, nh), Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        n = len(pil_icons)
        if n == 1:
            img = fit(pil_icons[0], size)
            iw, ih = img.size
            box = (size - iw) // 2, (size - ih) // 2
            canvas.paste(img, box, img)
        else:
            offset = min(16, size // (2 * n))
            tile = size - offset * (n - 1)
            # paste back-to-front so the first icon ends up on top
            for draw_idx, img in enumerate(reversed(pil_icons)):
                stack_pos = (n - 1) - draw_idx
                fitted = fit(img, tile)
                fw, fh = fitted.size
                x = offset * stack_pos + (tile - fw) // 2
                y = offset * stack_pos + (tile - fh) // 2
                canvas.paste(fitted, (x, y), fitted)

        from xpra.codecs.image import to_png
        data = to_png(canvas)
        return DISPLAY_ICON, size, size, "png", size * 4, Compressed("png", data)
