# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.x11_server_base import X11ServerBase
from xpra.server.shadow_server_base import ShadowServerBase


class ShadowX11Server(ShadowServerBase, X11ServerBase):

    def init(self, sockets, opts):
        X11ServerBase.init(self, False, sockets, opts)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        #adjust pointer position for offset in client:
        x, y = pointer
        wx, wy = self.mapped_at[:2]
        pointer = x-wx, y-wy
        X11ServerBase._process_mouse_common(self, proto, wid, pointer, modifiers)

    def make_hello(self):
        capabilities = X11ServerBase.make_hello(self)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/gtk2/x11-shadow"
        return capabilities

    def get_info(self, proto):
        info = X11ServerBase.get_info(self, proto)
        info["shadow"] = True
        info["server_type"] = "Python/gtk2/x11-shadow"
        return info
