# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.x11.desktop.base import DesktopServerBase
from xpra.x11.bindings.randr import RandRBindings
from xpra.server.common import get_sources_by_type
from xpra.server import features
from xpra.x11.error import xlog
from xpra.log import Logger

GLib = gi_import("GLib")
GObject = gi_import("GObject")

log = Logger("server")
geomlog = Logger("server", "window", "geometry")
screenlog = Logger("screen")


class XpraDesktopServer(DesktopServerBase):
    """
        A server class for RFB / VNC-like desktop displays,
        used with the `desktop` subcommand.
    """
    __gsignals__ = DesktopServerBase.__common_gsignals__

    def __init__(self):
        super().__init__()
        self.session_type = "X11 desktop"
        self.gsettings_modified = {}
        self.root_prop_watcher = None
        self.resize_value = -1, -1

    def init_randr(self) -> None:
        super().init_randr()
        from xpra.x11.vfb_util import set_initial_resolution
        screenlog(f"init_randr() randr={self.randr}, initial-resolutions={self.initial_resolutions}")
        if not RandRBindings().has_randr() or not self.initial_resolutions or not features.display:
            return
        res = self.initial_resolutions
        if len(res) > 1:
            log.warn(f"Warning: cannot set desktop resolution to {res}")
            log.warn(" multi monitor mode is not enabled")
            res = (res[0],)
            log.warn(f" using {res!r}")
        with xlog:
            set_initial_resolution(res, self.dpi or self.default_dpi)

    def configure_best_screen_size(self) -> tuple[int, int]:
        """ for the first client, honour desktop_mode_size if set """
        from xpra.x11.subsystem.display import get_root_size
        root_w, root_h = get_root_size()
        if not self.randr:
            screenlog("configure_best_screen_size() no randr")
            return root_w, root_h
        from xpra.server.source.display import DisplayConnection
        sss = get_sources_by_type(self, DisplayConnection)
        if len(sss) != 1:
            screenlog.info(f"screen used by {len(sss)} clients:")
            return root_w, root_h
        ss = sss[0]
        requested_size = ss.desktop_mode_size
        if not requested_size:
            screenlog("configure_best_screen_size() client did not request a specific desktop mode size")
            return root_w, root_h
        w, h = requested_size
        screenlog("client requested desktop mode resolution is %sx%s (current server resolution is %sx%s)",
                  w, h, root_w, root_h)
        if w <= 0 or h <= 0 or w >= 32768 or h >= 32768:
            screenlog("configure_best_screen_size() client requested an invalid desktop mode size: %s", requested_size)
            return root_w, root_h
        return self.set_screen_size(w, h)

    def resize(self, w: int, h: int) -> None:
        geomlog("resize(%i, %i)", w, h)
        if not RandRBindings().has_randr():
            geomlog.error("Error: cannot honour resize request,")
            geomlog.error(" no RandR support on this display")
            return
        # find the model:
        from xpra.x11.desktop.desktop_model import ScreenDesktopModel
        desktop_models = [w for w in self.subsystems["window"].models() if isinstance(w, ScreenDesktopModel)]
        if len(desktop_models) != 1:
            raise RuntimeError(f"found {desktop_models}, expected 1")
        geomlog(f"will resize {desktop_models}")
        desktop_models[0].resize(w, h)

    def get_server_features(self, source=None) -> dict[str, Any]:
        caps = super().get_server_features(source)
        caps["desktop"] = True
        return caps


GObject.type_register(XpraDesktopServer)
