# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import traceback
import logging

from xpra.log import Logger, set_global_logging_handler
log = Logger("client")


from xpra.scripts.config import parse_bool
from xpra.os_util import monotonic_time, strtobytes
from xpra.client.mixins.stub_client_mixin import StubClientMixin


"""
Mixin for remote logging support
"""
class RemoteLogging(StubClientMixin):

    def __init__(self):
        StubClientMixin.__init__(self)
        self.client_supports_remote_logging = False
        self.in_remote_logging = False
        self.local_logging = None
        self.log_both = False

    def init(self, opts):
        self.log_both = (opts.remote_logging or "").lower()=="both"
        self.client_supports_remote_logging = self.log_both or parse_bool("remote-logging", opts.remote_logging)


    def cleanup(self):
        ll = self.local_logging
        if ll:
            set_global_logging_handler(ll)


    def parse_server_capabilities(self):
        c = self.server_capabilities
        if self.client_supports_remote_logging and c.boolget("remote-logging"):
            #check for debug:
            from xpra.log import is_debug_enabled
            for x in ("network", "crypto", "udp"):
                if is_debug_enabled(x):
                    log.warn("Warning: cannot enable remote logging")
                    log.warn(" because '%s' debug logging is enabled", x)
                    return True
            log.info("enabled remote logging")
            if not self.log_both:
                log.info(" see server log file for further output")
            self.local_logging = set_global_logging_handler(self.remote_logging_handler)
        return True


    def remote_logging_handler(self, log, level, msg, *args, **kwargs):
        #prevent loops (if our send call ends up firing another logging call):
        if self.in_remote_logging:
            return
        self.in_remote_logging = True
        def enc(x):
            try:
                return x.encode("utf8")
            except:
                return strtobytes(x)
        try:
            dtime = int(1000*(monotonic_time() - self.start_time))
            data = self.compressed_wrapper("text", enc(msg % args), level=1)
            self.send("logging", level, data, dtime)
            exc_info = kwargs.get("exc_info")
            if exc_info is True:
                exc_info = sys.exc_info()
            if exc_info:
                for x in traceback.format_tb(exc_info[2]):
                    self.send("logging", level, enc(x), dtime)
                try:
                    etypeinfo = exc_info[0].__name__
                except:
                    etypeinfo = str(exc_info[0])
                self.send("logging", level, enc("%s: %s" % (etypeinfo, exc_info[1])), dtime)
            if self.log_both:
                self.local_logging(log, level, msg, *args, **kwargs)
        except Exception as e:
            if self.exit_code is not None:
                #errors can happen during exit, don't care
                return
            self.local_logging(log, logging.WARNING, "Warning: failed to send logging packet:")
            self.local_logging(log, logging.WARNING, " %s" % e)
            self.local_logging(log, logging.WARNING, " original unformatted message: %s", msg)
            try:
                self.local_logging(log, level, msg, *args, **kwargs)
            except:
                pass
            try:
                exc_info = sys.exc_info()
                for x in traceback.format_tb(exc_info[2]):
                    for v in x.splitlines():
                        self.local_logging(log, logging.WARNING, v)
            except:
                pass
        finally:
            self.in_remote_logging = False
