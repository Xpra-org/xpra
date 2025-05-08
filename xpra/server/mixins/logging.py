# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import sys
import logging
import traceback
from time import monotonic
from threading import Lock
from typing import Any
from collections.abc import Callable

from xpra.util.str_fn import repr_ellipsized, memoryview_to_bytes
from xpra.net.common import PacketType
from xpra.scripts.config import FALSE_OPTIONS, TRUE_OPTIONS
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger, set_global_logging_handler

log = Logger("server")


class LoggingServer(StubServerMixin):
    """
    Mixin for servers that can receive and send logging packets
    """
    PREFIX = "logging"

    def __init__(self):
        self.remote_logging_send: bool = False
        self.remote_logging_receive: bool = False
        self.logging_lock: Lock = Lock()
        self.log_both: bool = False
        self.in_remote_logging: bool = False
        self.local_logging: Callable | None = None
        self.logging_clients: dict[Any, float] = {}

    def init(self, opts) -> None:
        self.log_both = (opts.remote_logging or "").lower() == "both"
        if opts.remote_logging.lower() not in FALSE_OPTIONS:
            self.remote_logging_send = opts.remote_logging.lower() in ("allow", "send", "both")
            # "yes" is here for backwards compatibility:
            self.remote_logging_receive = opts.remote_logging.lower() in ["allow", "receive", "both"] + list(
                TRUE_OPTIONS)

    def cleanup(self) -> None:
        self.stop_capturing_logging()

    def get_server_features(self, _source=None) -> dict[str, Any]:
        return {"remote-logging": self._features()}

    def _features(self) -> dict[str, Any]:
        return {
            "receive": self.remote_logging_receive,
            "send": self.remote_logging_send,
        }

    def get_info(self, _proto):
        return {
            LoggingServer.PREFIX: self._features(),
        }

    def cleanup_protocol(self, protocol) -> None:
        if protocol in self.logging_clients:
            del self.logging_clients[protocol]

    def remove_logging_client(self, protocol) -> None:
        if self.logging_clients.pop(protocol, None) is None:
            log.warn("Warning: logging was not enabled for '%r'", protocol)
        if not self.logging_clients:
            self.stop_capturing_logging()

    def add_logging_client(self, protocol) -> None:
        n = len(self.logging_clients)
        if protocol in self.logging_clients:
            log.warn("Warning: logging already enabled for client %s", protocol)
            return
        log.info("sending log output to %s", protocol)
        self.logging_clients[protocol] = monotonic()
        if n == 0:
            self.start_capturing_logging()

    def start_capturing_logging(self) -> None:
        if not self.local_logging:
            self.local_logging = set_global_logging_handler(self.remote_logging_handler)

    def stop_capturing_logging(self) -> None:
        ll = self.local_logging
        if ll:
            self.local_logging = None
            set_global_logging_handler(ll)

    def remote_logging_handler(self, log, level: int, msg, *args, **kwargs) -> None:
        # prevent loops (if our send call ends up firing another logging call):
        if self.in_remote_logging:
            return
        ll = self.local_logging

        def local_warn(*args) -> None:
            if ll:
                ll(log, logging.WARNING, *args)

        def local_err(message, e=None) -> None:
            if self._closing:
                return
            local_warn("Warning: %s:", message)
            if e:
                local_warn(" %s", e)
            local_warn(" original unformatted message: %s", msg)
            if args:
                local_warn(" %i arguments: %s", len(args), args)
            else:
                local_warn(" (no arguments)")
            try:
                if ll:
                    ll(log, level, msg, *args, **kwargs)
            except Exception:
                pass
            try:
                exc_info = sys.exc_info()
                for x in traceback.format_tb(exc_info[2]):
                    for v in x.splitlines():
                        local_warn(v)
            except Exception:
                pass

        self.in_remote_logging = True
        try:
            if not kwargs.pop("remote", True):
                if ll:
                    try:
                        ll(log, level, msg, *args, **kwargs)
                    except Exception as e:
                        local_warn("Warning: failed to log message locally")
                        local_warn(" %s", e)
                        local_warn(" %s", msg)
                return
            try:
                if args:
                    data = msg % args
                else:
                    data = msg
            except Exception as e:
                local_err("failed to format log message", e)
                return
            for proto, start_time in self.logging_clients.items():
                source = self.get_server_source(proto)
                if not source:
                    continue
                try:
                    dtime = int(1000 * (monotonic() - start_time))
                    if len(data) >= 32:
                        try:
                            data = source.compressed_wrapper("text", data.encode("utf8"), level=1)
                        except Exception:
                            pass
                    source.send("logging", level, data, dtime)
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
                        source.send("logging", level, "%s: %s" % (etypeinfo, exc_info[1]), dtime)
                except Exception as e:
                    if self._closing:
                        return
                    local_warn("Warning: failed to send log message to %s: %s", source, e)
            if self.log_both and ll:
                try:
                    ll(log, level, msg, *args, **kwargs)
                except Exception:
                    pass
        finally:
            self.in_remote_logging = False

    def _process_logging_control(self, proto, packet: PacketType) -> None:
        action = str(packet[1])
        if action == "start":
            self.add_logging_client(proto)
        elif action == "stop":
            self.remove_logging_client(proto)
        else:
            log.warn("Warning: unknown logging-control action '%r'", action)

    def _process_logging(self, proto, packet: PacketType) -> None:
        self._process_logging_event(proto, packet)

    def _process_logging_event(self, proto, packet: PacketType) -> None:
        assert self.remote_logging_receive
        ss = self.get_server_source(proto)
        if ss is None:
            return
        level, msg = packet[1:3]
        prefix = "client "
        counter = getattr(ss, "counter", 0)
        if counter > 0:
            prefix += "%3i " % counter
        if len(packet) >= 4:
            dtime = packet[3]
            prefix += "@%02i.%03i " % ((dtime // 1000) % 60, dtime % 1000)

        def decode(v) -> str:
            if isinstance(v, str):
                return v
            return memoryview_to_bytes(v).decode("utf8")

        try:
            if isinstance(msg, (tuple, list)):
                dmsg = " ".join(decode(x) for x in msg)
            else:
                dmsg = decode(msg)
            for line in dmsg.splitlines():
                self.do_log(level, prefix + line)
        except Exception as e:
            log("log message decoding error", exc_info=True)
            log.error("Error: failed to parse logging message:")
            log.error(" %s", repr_ellipsized(msg))
            log.estr(e)

    def do_log(self, level, line) -> None:
        with self.logging_lock:
            log.log(level, line)

    def init_packet_handlers(self) -> None:
        if self.remote_logging_receive:
            self.add_packets("logging-event")
            self.add_legacy_alias("logging", "logging-event")
        if self.remote_logging_send:
            self.add_packets("logging-control")
