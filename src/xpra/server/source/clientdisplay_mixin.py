# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import strtobytes
from xpra.util import get_screen_info, envint, first_time, iround
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("av-sync")


"""
Store information and manage events related to the client's display
"""
class ClientDisplayMixin(StubSourceMixin):

    def cleanup(self):
        self.init_state()

    def init_state(self):
        self.icc = {}
        self.display_icc = {}
        self.randr_notify = False
        self.desktop_size = None
        self.desktop_mode_size = None
        self.desktop_size_unscaled = None
        self.desktop_size_server = None
        self.screen_sizes = ()
        self.screen_resize_bigger = True
        self.desktops = 1
        self.desktop_names = ()
        self.show_desktop_allowed = False

    def get_info(self):
        info = {
            "desktop_size"  : self.desktop_size or "",
            "desktops"      : self.desktops,
            "desktop_names" : self.desktop_names,
            "randr_notify"  : self.randr_notify,
            }
        info.update(get_screen_info(self.screen_sizes))
        if self.desktop_mode_size:
            info["desktop_mode_size"] = self.desktop_mode_size
        if self.desktop_size_unscaled:
            info["desktop_size"] = {"unscaled" : self.desktop_size_unscaled}
        return info

    def parse_client_caps(self, c):
        self.randr_notify = c.boolget("randr_notify")
        self.desktop_size = c.intpair("desktop_size")
        if self.desktop_size is not None:
            w, h = self.desktop_size
            if w<=0 or h<=0 or w>=32768 or h>=32768:
                log.warn("ignoring invalid desktop dimensions: %sx%s", w, h)
                self.desktop_size = None
        self.desktop_mode_size = c.intpair("desktop_mode_size")
        self.desktop_size_unscaled = c.intpair("desktop_size.unscaled")
        self.screen_resize_bigger = c.boolget("screen-resize-bigger", True)
        self.set_screen_sizes(c.listget("screen_sizes"))
        self.set_desktops(c.intget("desktops", 1), c.strlistget("desktop.names"))
        self.show_desktop_allowed = c.boolget("show-desktop")
        self.icc = c.dictget("icc", {})
        self.display_icc = c.dictget("display-icc", {})


    def set_screen_sizes(self, screen_sizes):
        log("set_screen_sizes(%s)", screen_sizes)
        self.screen_sizes = screen_sizes or []
        #validate dpi / screen size in mm
        #(ticket 2480: GTK3 on macos can return bogus values)
        MIN_DPI = envint("XPRA_MIN_DPI", 10)
        MAX_DPI = envint("XPRA_MIN_DPI", 500)
        def dpi(size_pixels, size_mm):
            if size_mm==0:
                return 0
            return int(size_pixels * 254 / size_mm / 10)
        for i,screen in enumerate(screen_sizes):
            if len(screen)<10:
                continue
            sw, sh, wmm, hmm, monitors = screen[1:6]
            xdpi = dpi(sw, wmm)
            ydpi = dpi(sh, hmm)
            if xdpi<MIN_DPI or xdpi>MAX_DPI or ydpi<MIN_DPI or ydpi>MAX_DPI:
                warn = first_time("invalid-screen-size-%ix%i" % (wmm, hmm))
                if warn:
                    log.warn("Warning: sanitizing invalid screen size %ix%i mm", wmm, hmm)
                if monitors:
                    #[plug_name, xs(geom.x), ys(geom.y), xs(geom.width), ys(geom.height), wmm, hmm]
                    wmm = sum(monitor[5] for monitor in monitors)
                    hmm = sum(monitor[6] for monitor in monitors)
                    xdpi = dpi(sw, wmm)
                    ydpi = dpi(sh, hmm)
                if xdpi<MIN_DPI or xdpi>MAX_DPI or ydpi<MIN_DPI or ydpi>MAX_DPI:
                    #still invalid, generate one from DPI=96
                    wmm = iround(sw*254/10/96.0)
                    hmm = iround(sh*254/10/96.0)
                if warn:
                    log.warn(" using %ix%i mm", wmm, hmm)
                screen = list(screen)
                screen[3] = wmm
                screen[4] = hmm
                screen_sizes[i] = tuple(screen)
        log("client validated screen sizes: %s", screen_sizes)

    def set_desktops(self, desktops, desktop_names):
        self.desktops = desktops or 1
        #older clients send strings,
        #newer clients send bytes...
        def b(v):
            try :
                return strtobytes(v).decode("utf8")
            except UnicodeDecodeError:
                return v
        if desktop_names:
            self.desktop_names = [b(d) for d in desktop_names]
        else:
            self.desktop_names = []

    def updated_desktop_size(self, root_w, root_h, max_w, max_h):
        log("updated_desktop_size%s randr_notify=%s, desktop_size=%s",
            (root_w, root_h, max_w, max_h), self.randr_notify, self.desktop_size)
        if not self.hello_sent:
            return False
        if self.randr_notify and (not self.desktop_size_server or tuple(self.desktop_size_server)!=(root_w, root_h)):
            self.desktop_size_server = root_w, root_h
            self.send("desktop_size", root_w, root_h, max_w, max_h)
            return True
        return False

    def show_desktop(self, show):
        if self.show_desktop_allowed and self.hello_sent:
            self.send_async("show-desktop", show)
