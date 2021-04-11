# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("rpc")
dbuslog = Logger("dbus", "rpc")


"""
Mixin for servers that handle DBUS and RPC requests.
"""
class DBUS_RPC_Server(StubServerMixin):

    def __init__(self):
        self.rpc_handlers = {}
        self.supports_dbus_proxy = False
        self.dbus_helper = None

    def init(self, opts):
        self.supports_dbus_proxy = opts.dbus_proxy

    def setup(self):
        self.init_dbus_helper()


    def get_server_features(self, _source=None):
        return {
            "dbus_proxy"    : self.supports_dbus_proxy,
            "rpc-types"     : tuple(self.rpc_handlers.keys()),
            }


    def get_info(self, _proto):
        return {}


    def init_dbus_helper(self):
        if not self.supports_dbus_proxy:
            return
        try:
            from xpra.dbus.helper import DBusHelper
            self.dbus_helper = DBusHelper()
            self.rpc_handlers["dbus"] = self._handle_dbus_rpc
        except Exception as e:
            log("init_dbus_helper()", exc_info=True)
            log.warn("Warning: cannot load dbus helper:")
            for msg in str(e).split(": "):
                log.warn(" %s", msg)
            self.dbus_helper = None
            self.supports_dbus_proxy = False


    def make_dbus_server(self):
        from xpra.server.dbus.dbus_server import DBUS_Server
        return DBUS_Server(self, os.environ.get("DISPLAY", "").lstrip(":"))

    def _handle_dbus_rpc(self, ss, rpcid, _, bus_name, path, interface, function, args, *_extra):
        assert self.supports_dbus_proxy, "server does not support dbus proxy calls"
        def native(args):
            return [self.dbus_helper.dbus_to_native(x) for x in (args or [])]
        def ok_back(*args):
            log("rpc: ok_back%s", args)
            ss.rpc_reply("dbus", rpcid, True, native(args))
        def err_back(*args):
            log("rpc: err_back%s", args)
            ss.rpc_reply("dbus", rpcid, False, native(args))
        self.dbus_helper.call_function(bus_name, path, interface, function, args, ok_back, err_back)


    def _process_rpc(self, proto, packet):
        if self.readonly:
            return
        ss = self.get_server_source(proto)
        assert ss is not None
        rpc_type = packet[1]
        rpcid = packet[2]
        handler = self.rpc_handlers.get(rpc_type)
        if not handler:
            log.error("Error: invalid rpc request of type '%s'", rpc_type)
            return
        log("rpc handler for %s: %s", rpc_type, handler)
        try:
            handler(ss, *packet[2:])
        except Exception as e:
            log.error("Error: cannot call %s handler %s:", rpc_type, handler, exc_info=True)
            ss.rpc_reply(rpc_type, rpcid, False, str(e))


    def init_packet_handlers(self):
        if self.supports_dbus_proxy:
            self.add_packet_handler("rpc", self._process_rpc)
