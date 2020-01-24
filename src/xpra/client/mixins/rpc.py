# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

from xpra.util import envint, AtomicInteger
from xpra.os_util import monotonic_time
from xpra.util import typedict
from xpra.client.mixins.stub_client_mixin import StubClientMixin
from xpra.log import Logger

log = Logger("client", "rpc")

RPC_TIMEOUT = envint("XPRA_RPC_TIMEOUT", 5000)


"""
Utility superclass for client classes that handle RPC calls
"""
class RPCClient(StubClientMixin):

    def __init__(self):
        StubClientMixin.__init__(self)
        #rpc / dbus:
        self.rpc_counter = AtomicInteger()
        self.rpc_pending_requests = {}
        self.server_dbus_proxy = False
        self.server_rpc_types = []
        self.rpc_filter_timers = {}

    def cleanup(self):
        timers = tuple(self.rpc_filter_timers.values())
        self.rpc_filter_timers = {}
        for t in timers:
            self.source_remove(t)


    def run(self):
        pass


    def parse_server_capabilities(self, c : typedict) -> bool:
        self.server_dbus_proxy = c.boolget("dbus_proxy")
        #default for pre-0.16 servers:
        if self.server_dbus_proxy:
            default_rpc_types = ["dbus"]
        else:
            default_rpc_types = []
        self.server_rpc_types = c.strtupleget("rpc-types", default_rpc_types)
        return True

    def process_ui_capabilities(self, caps : typedict):
        pass


    def rpc_call(self, rpc_type, rpc_args, reply_handler=None, error_handler=None):
        assert rpc_type in self.server_rpc_types, "server does not support %s rpc" % rpc_type
        rpcid = self.rpc_counter.increase()
        self.rpc_filter_pending(rpcid)
        #keep track of this request (for timeout / error and reply callbacks):
        req = monotonic_time(), rpc_type, rpc_args, reply_handler, error_handler
        self.rpc_pending_requests[rpcid] = req
        log("sending %s rpc request %s to server: %s", rpc_type, rpcid, req)
        packet = ["rpc", rpc_type, rpcid] + rpc_args
        self.send(*packet)
        self.rpc_filter_timers[rpcid] = self.timeout_add(RPC_TIMEOUT, self.rpc_filter_pending, rpcid)

    def rpc_filter_pending(self, rpcid):
        """ removes timed out dbus requests """
        del self.rpc_filter_timers[rpcid]
        for k in tuple(self.rpc_pending_requests.keys()):
            v = self.rpc_pending_requests.get(k)
            if v is None:
                continue
            t, rpc_type, _rpc_args, _reply_handler, ecb = v
            if 1000*(monotonic_time()-t)>=RPC_TIMEOUT:
                log.warn("%s rpc request: %s has timed out", rpc_type, _rpc_args)
                try:
                    del self.rpc_pending_requests[k]
                    if ecb is not None:
                        ecb("timeout")
                except Exception as e:
                    log.error("Error during timeout handler for %s rpc callback:", rpc_type)
                    log.error(" %s", e)
                    del e


    ######################################################################
    #packet handlers
    def _process_rpc_reply(self, packet):
        rpc_type, rpcid, success, args = packet[1:5]
        log("rpc_reply: %s", (rpc_type, rpcid, success, args))
        v = self.rpc_pending_requests.get(rpcid)
        assert v is not None, "pending dbus handler not found for id %s" % rpcid
        assert rpc_type==v[1], "rpc reply type does not match: expected %s got %s" % (v[1], rpc_type)
        del self.rpc_pending_requests[rpcid]
        if success:
            ctype = "ok"
            rh = v[-2]      #ok callback
        else:
            ctype = "error"
            rh = v[-1]      #error callback
        if rh is None:
            log("no %s rpc callback defined, return values=%s", ctype, args)
            return
        log("calling %s callback %s(%s)", ctype, rh, args)
        try:
            rh(*args)
        except Exception as e:
            log.error("Error processing rpc reply handler %s(%s) :", rh, args)
            log.error(" %s", e)


    def init_authenticated_packet_handlers(self):
        log("init_authenticated_packet_handlers()")
        self.add_packet_handler("rpc-reply", self._process_rpc_reply)
