# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import logging
import traceback
from time import monotonic
from threading import Lock

from xpra.util.objects import typedict
from xpra.util.str_fn import csv, repr_ellipsized
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.log import Logger, set_global_logging_handler
from xpra.net.common import PacketType, LOG_PACKET_TYPE
from xpra.net.compression import Compressed

log = Logger("client")


class RemoteLogging(StubClientMixin):
    """
    Mixin for remote logging support,
    either sending local logging events to the server,
    or receiving logging events from the server.
    """
    PREFIX = "logging"

    def __init__(self):
        self.remote_logging = "no"
        self.in_remote_logging = False
        self.local_logging = None
        self.logging_lock = Lock()
        self.log_both = False
        self.request_server_log = False
        self.monotonic_start_time = monotonic()

    def init(self, opts) -> None:
        self.remote_logging = opts.remote_logging
        self.log_both = (opts.remote_logging or "").lower() == "both"

    def cleanup(self) -> None:
        ll = self.local_logging
        log("cleanup() local_logging=%s", ll)
        if ll:
            self.local_logging = None
            set_global_logging_handler(ll)

    def parse_server_capabilities(self, c: typedict) -> bool:
        receive = c.boolget("remote-logging.receive")
        send = c.boolget("remote-logging.send")
        v = c.get("remote-logging")
        if isinstance(v, dict):
            c = typedict(v)
            receive = c.boolget("receive")
            send = c.boolget("send")
        if self.remote_logging.lower() in ("send", "both", "yes", "true", "on") and receive:
            # check for debug:
            from xpra.log import is_debug_enabled
            conflict = tuple(v for v in ("network", "crypto", "websocket", "quic") if is_debug_enabled(v))
            if conflict:
                log.warn("Warning: cannot enable remote logging")
                log.warn(" because debug logging is enabled for: %s", csv(conflict))
                return True
            if LOG_PACKET_TYPE:
                log.warn("Warning: cannot enable remote logging")
                log.warn(f" because {LOG_PACKET_TYPE=}")
                return True
            log.info("enabled remote logging")
            if not self.log_both:
                log.info(" see server log file for further output")
            self.local_logging = set_global_logging_handler(self.remote_logging_handler)
        elif self.remote_logging.lower() == "receive":
            self.request_server_log = send
            if not self.request_server_log:
                log.warn("Warning: cannot receive log output from the server")
                log.warn(" the feature is not enabled or not supported by the server")
            else:
                self.after_handshake(self.start_receiving_logging)  # pylint: disable=no-member
        return True

    def start_receiving_logging(self) -> None:
        self.add_packets("logging-event")
        self.add_legacy_alias("logging", "logging-event")
        self.send("logging-control", "start")

    def _process_logging_event(self, packet: PacketType) -> None:
        assert not self.local_logging, "cannot receive logging packets when forwarding logging!"
        level = int(packet[1])
        msg = packet[2]
        prefix = "server: "
        if len(packet) >= 4:
            dtime = int(packet[3])
            prefix += "@%02i.%03i " % ((dtime // 1000) % 60, dtime % 1000)
        try:
            if isinstance(msg, (tuple, list)):
                dmsg = " ".join(str(x) for x in msg)
            else:
                dmsg = str(msg)
            for line in dmsg.splitlines():
                self.do_log(level, prefix + line)
        except Exception as e:
            log("log message decoding error", exc_info=True)
            log.error("Error: failed to parse logging message:")
            log.error(" %s", repr_ellipsized(msg))
            log.estr(e)

    def do_log(self, level: int, line) -> None:
        with self.logging_lock:
            log.log(level, line)

    def remote_logging_handler(self, logger_log, level: int, msg: str, *args, **kwargs) -> None:
        # prevent loops (if our send call ends up firing another logging call):
        if self.in_remote_logging:
            return
        self.in_remote_logging = True
        ll = self.local_logging

        def local_warn(*warn_args) -> None:
            if ll:
                ll(logger_log, logging.WARNING, *warn_args)

        try:
            if not kwargs.pop("remote", True):
                # keyword is telling us not to forward it!
                if ll:
                    try:
                        ll(logger_log, level, msg, *args, **kwargs)
                    except Exception as e:
                        local_warn("Warning: failed to log message locally")
                        local_warn(" %s", e)
                        local_warn(" %s", msg)
                return

            dtime = int(1000 * (monotonic() - self.monotonic_start_time))
            data: str | Compressed
            if args:
                data = msg % args
            else:
                data = msg
            if len(data) >= 32:
                try:
                    data = self.compressed_wrapper("text", data.encode("utf8"), level=1)
                except Exception:
                    pass
            self.send("logging", level, data, dtime)
            exc_info = kwargs.get("exc_info")
            if exc_info is True:
                exc_info = sys.exc_info()
            if exc_info and exc_info[0]:
                for x in traceback.format_tb(exc_info[2]):
                    self.send("logging", level, x, dtime)
                try:
                    etypeinfo = exc_info[0].__name__
                except AttributeError:
                    etypeinfo = str(exc_info[0])
                self.send("logging", level, f"{etypeinfo}: {exc_info[1]}", dtime)
            if self.log_both and ll:
                ll(logger_log, level, msg, *args, **kwargs)
        except Exception as e:
            if self.exit_code is not None:
                # errors can happen during exit, don't care
                return
            local_warn("Warning: failed to send logging packet:")
            local_warn(f" {e}")
            local_warn(f" original unformatted message: {msg}")
            if args:
                local_warn(f" {len(args)} arguments: {args}")
            else:
                local_warn(" (no arguments)")
            if ll:
                try:
                    ll(logger_log, level, msg, *args, **kwargs)
                except Exception:
                    pass
            try:
                exc_info = sys.exc_info()
                for x in traceback.format_tb(exc_info[2]):
                    for v in x.splitlines():
                        local_warn(v)
            except Exception:
                pass
        finally:
            self.in_remote_logging = False
