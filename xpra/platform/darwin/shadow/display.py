# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import Quartz.CoreGraphics as CG

from xpra.util.env import envbool
from xpra.server.shadow.display import ShadowDisplayManager

HIGHDPI = envbool("XPRA_AVFOUNDATION_HIGHDPI", False)


class DarwinShadowDisplayManager(ShadowDisplayManager):
    """
    macOS display subsystem for shadow servers.
    """

    def get_display_size(self) -> tuple[int, int]:
        bounds = CG.CGDisplayBounds(CG.CGMainDisplayID())
        w, h = int(bounds.size.width), int(bounds.size.height)
        # high-dpi: the AVFoundation streaming capture delivers native pixels,
        # so report the size in pixels to match (see ShadowServer.get_shadow_monitors):
        if HIGHDPI and getattr(self.server, "_streaming", False):
            from xpra.platform.darwin.avfoundation_screen import get_display_scale
            sf = get_display_scale(CG.CGMainDisplayID())
            return round(w * sf), round(h * sf)
        return w, h
