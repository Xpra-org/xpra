# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("av-sync")

from xpra.util import get_screen_info
from xpra.server.source.stub_source_mixin import StubSourceMixin


"""
Store information and manage events related to the client's display
"""
class ClientDisplayMixin(StubSourceMixin):

    def __init__(self):
        self.icc = {}
        self.display_icc = {}
        self.randr_notify = False
        self.desktop_size = None
        self.desktop_mode_size = None
        self.desktop_size_unscaled = None
        self.desktop_size_server = None
        self.screen_sizes = ()
        self.desktops = 1
        self.desktop_names = ()
        self.show_desktop_allowed = False

    def cleanup(self):
        pass

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
        if self.client_connection_data:
            info["connection-data"] = self.client_connection_data
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
        self.set_screen_sizes(c.listget("screen_sizes"))
        self.set_desktops(c.intget("desktops", 1), c.strlistget("desktop.names"))
        self.show_desktop_allowed = c.boolget("show-desktop")
        self.icc = c.dictget("icc")
        self.display_icc = c.dictget("display-icc")


    def set_screen_sizes(self, screen_sizes):
        self.screen_sizes = screen_sizes or []
        log("client screen sizes: %s", screen_sizes)

    def set_desktops(self, desktops, desktop_names):
        self.desktops = desktops or 1
        self.desktop_names = desktop_names or []

    def updated_desktop_size(self, root_w, root_h, max_w, max_h):
        log("updated_desktop_size%s randr_notify=%s, desktop_size=%s", (root_w, root_h, max_w, max_h), self.randr_notify, self.desktop_size)
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
