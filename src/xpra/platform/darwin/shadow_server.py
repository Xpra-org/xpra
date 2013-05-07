# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()

from xpra.server.server_base import ServerBase
from xpra.server.shadow_server_base import ShadowServerBase


class ShadowServer(ShadowServerBase, ServerBase):

    def __init__(self):
        ShadowServerBase.__init__(self)
        ServerBase.__init__(self)

    def init(self, sockets, opts):
        ServerBase.init(self, sockets, opts)
        self.keycodes = {}

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        pass

    def fake_key(self, keycode, press):
        pass

    def _process_button_action(self, proto, packet):
        pass

    def make_hello(self):
        capabilities = ServerBase.make_hello(self)
        capabilities["shadow"] = True
        capabilities["server_type"] = "Python/gtk2/osx-shadow"
        return capabilities

    def get_info(self, proto):
        info = ServerBase.get_info(self, proto)
        info["shadow"] = True
        info["server_type"] = "Python/gtk2/osx-shadow"
        return info
