# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2016-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Dict, Any, Tuple
from gi.repository import GObject  # @UnresolvedImport

from xpra.x11.desktop.desktop_server_base import DesktopServerBase
from xpra.x11.desktop.desktop_model import ScreenDesktopModel
from xpra.x11.bindings.randr import RandRBindings #@UnresolvedImport
from xpra.server import server_features
from xpra.gtk_common.error import xsync, xlog
from xpra.log import Logger

RandR = RandRBindings()

log = Logger("server")
geomlog = Logger("server", "window", "geometry")
screenlog = Logger("screen")


class XpraDesktopServer(DesktopServerBase):
    """
        A server class for RFB / VNC-like desktop displays,
        used with the "start-desktop" subcommand.
    """
    __gsignals__ = DesktopServerBase.__common_gsignals__

    def __init__(self):
        super().__init__()
        self.session_type = "desktop"
        self.resize_timer = 0
        self.gsettings_modified = {}
        self.root_prop_watcher = None

    def server_init(self) -> None:
        super().server_init()
        from xpra.x11.vfb_util import set_initial_resolution, get_desktop_vfb_resolutions
        screenlog(f"server_init() randr={self.randr}, initial-resolutions={self.initial_resolutions}")
        if not self.randr or self.initial_resolutions==() or not server_features.display:
            return
        res = self.initial_resolutions or get_desktop_vfb_resolutions(default_refresh_rate=self.refresh_rate)
        if len(res)>1:
            log.warn(f"Warning: cannot set desktop resolution to {res}")
            log.warn(" multi monitor mode is not enabled")
            res = (res[0], )
            log.warn(f" using {res!r}")
        with xlog:
            set_initial_resolution(res, self.dpi or self.default_dpi)


    def configure_best_screen_size(self) -> Tuple[int,int]:
        """ for the first client, honour desktop_mode_size if set """
        root_w, root_h = self.root_window.get_geometry()[2:4]
        if not self.randr:
            screenlog("configure_best_screen_size() no randr")
            return root_w, root_h
        sss = tuple(x for x in self._server_sources.values() if x.ui_client)
        if len(sss)!=1:
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
        if w<=0 or h<=0 or w>=32768 or h>=32768:
            screenlog("configure_best_screen_size() client requested an invalid desktop mode size: %s", requested_size)
            return root_w, root_h
        return self.set_screen_size(w, h, ss.screen_resize_bigger)

    def resize(self, w:int, h:int) -> None:
        geomlog("resize(%i, %i)", w, h)
        if not RandR.has_randr():
            geomlog.error("Error: cannot honour resize request,")
            geomlog.error(" no RandR support on this display")
            return
        #FIXME: small race if the user resizes with randr,
        #at the same time as he resizes the window..
        self.resize_value = (w, h)
        if not self.resize_timer:
            self.resize_timer = self.timeout_add(250, self.do_resize)

    def do_resize(self) -> None:
        self.resize_timer = 0
        rw, rh = self.resize_value
        try:
            with xsync:
                ow, oh = RandR.get_screen_size()
            w, h = self.set_screen_size(rw, rh, False)
            if (ow, oh) == (w, h):
                #this is already the resolution we have,
                #but the client has other ideas,
                #so tell the client we ain't budging:
                for win in self._window_to_id.keys():
                    win.emit("resized")
        except Exception as e:
            geomlog("do_resize() %ix%i", rw, rh, exc_info=True)
            geomlog.error(f"Error: failed to resize desktop display to {rw}x{rh}")
            geomlog.estr(e)


    def get_server_mode(self) -> str:
        return "X11 desktop"

    def make_hello(self, source) -> Dict[str,Any]:
        capabilities = super().make_hello(source)
        if "features" in source.wants:
            capabilities["desktop"] =True
        return capabilities


    def load_existing_windows(self) -> None:
        with xsync:
            model = ScreenDesktopModel(self.randr_exact_size)
            model.setup()
            screenlog("adding root window model %s", model)
            super().do_add_new_window_common(1, model)
            model.managed_connect("client-contents-changed", self._contents_changed)
            model.managed_connect("resized", self.send_updated_screen_size)
            model.managed_connect("motion", self._motion_signaled)

    def send_updated_screen_size(self, model) -> None:
        #the vfb has been resized
        wid = self._window_to_id[model]
        x, y, w, h = model.get_geometry()
        geomlog("send_updated_screen_size(%s) geometry=%s", model, (x, y, w, h))
        for ss in self.window_sources():
            ss.resize_window(wid, model, w, h)
            ss.damage(wid, model, 0, 0, w, h)


GObject.type_register(XpraDesktopServer)
