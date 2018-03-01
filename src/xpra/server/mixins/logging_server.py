# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("client")

from xpra.os_util import bytestostr
from xpra.scripts.config import FALSE_OPTIONS
from xpra.server.mixins.stub_server_mixin import StubServerMixin


"""
Mixin for servers that can receive logging packets
"""
class LoggingServer(StubServerMixin):

    def __init__(self):
        self.remote_logging = False

    def init(self, opts):
        self.remote_logging = not ((opts.remote_logging or "").lower() in FALSE_OPTIONS)

    def get_server_features(self, _source=None):
        return {
            "remote-logging"            : self.remote_logging,
            "remote-logging.multi-line" : True,
            }

    def _process_logging(self, proto, packet):
        assert self.remote_logging
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        level, msg = packet[1:3]
        prefix = "client "
        if len(self._server_sources)>1:
            prefix += "%3i " % ss.counter
        if len(packet)>=4:
            dtime = packet[3]
            prefix += "@%02i.%03i " % ((dtime//1000)%60, dtime%1000)
        def dec(x):
            try:
                return x.decode("utf8")
            except:
                return bytestostr(x)
        if isinstance(msg, (tuple, list)):
            msg = " ".join(dec(x) for x in msg)
        for x in dec(msg).splitlines():
            log.log(level, prefix+x)


    def init_packet_handlers(self):
        if self.remote_logging:
            self._authenticated_packet_handlers.update({
                "logging" : self._process_logging,
              })
