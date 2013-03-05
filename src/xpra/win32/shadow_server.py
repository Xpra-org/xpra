# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.log import Logger
log = Logger()

from xpra.server_base import ServerBase
from xpra.shadow_server_base import ShadowServerBase


class XpraWin32ShadowServer(ShadowServerBase, ServerBase):

    def __init__(self, sockets, opts):
        ShadowServerBase.__init__(self)
        ServerBase.__init__(self, True, sockets, opts)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        #TODO: implement!
        pass

    def fake_key(self, keycode, press):
        #TODO: implement!
        pass

    def _process_button_action(self, proto, packet):
        #TODO: implement!
        pass

    def make_hello(self):
        capabilities = ServerBase.make_hello(self)
        capabilities["shadow"] = True
        capabilities["server_type"] = "gtk-shadow"
        return capabilities

    def get_info(self, proto):
        info = ServerBase.get_info(self, proto)
        info["shadow"] = True
        info["server_type"] = "gtk-shadow"
        return info
