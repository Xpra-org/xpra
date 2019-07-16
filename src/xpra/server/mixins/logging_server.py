# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
#pylint: disable-msg=E1101

from threading import Lock

from xpra.os_util import bytestostr
from xpra.util import repr_ellipsized
from xpra.scripts.config import FALSE_OPTIONS
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("server")


"""
Mixin for servers that can receive logging packets
"""
class LoggingServer(StubServerMixin):

    def __init__(self):
        self.remote_logging = False
        self.logging_lock = Lock()

    def init(self, opts):
        self.remote_logging = not (opts.remote_logging or "").lower() in FALSE_OPTIONS

    def get_server_features(self, _source=None):
        return {
            "remote-logging"            : self.remote_logging,
            "remote-logging.multi-line" : True,
            }

    def _process_logging(self, proto, packet):
        assert self.remote_logging
        ss = self.get_server_source(proto)
        if ss is None:
            return
        level, msg = packet[1:3]
        prefix = "client "
        counter = getattr(ss, "counter", 0)
        if counter>0:
            prefix += "%3i " % counter
        if len(packet)>=4:
            dtime = packet[3]
            prefix += "@%02i.%03i " % ((dtime//1000)%60, dtime%1000)
        def dec(x):
            try:
                return x.decode("utf8")
            except Exception:
                return bytestostr(x)
        try:
            if isinstance(msg, (tuple, list)):
                dmsg = " ".join(dec(x) for x in msg)
            else:
                dmsg = dec(msg)
            for l in dmsg.splitlines():
                self.do_log(level, prefix+l)
        except Exception as e:
            log("log message decoding error", exc_info=True)
            log.error("Error: failed to parse logging message:")
            log.error(" %s", repr_ellipsized(msg))
            log.error(" %s", e)

    def do_log(self, level, line):
        with self.logging_lock:
            log.log(level, line)

    def init_packet_handlers(self):
        if self.remote_logging:
            self.add_packet_handler("logging", self._process_logging, False)
