# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.util.objects import typedict
from xpra.os_util import gi_import
from xpra.net.protocol.factory import get_server_protocol_class
from xpra.server.proxy.instance_base import ProxyInstance
from xpra.log import Logger

log = Logger("proxy")

GLib = gi_import("GLib")


class ProxyInstanceThread(ProxyInstance):

    def __init__(self, session_options: dict[str, str], pings: int,
                 client_proto, server_conn,
                 disp_desc: dict[str, Any],
                 cipher: str, cipher_mode: str, encryption_key: bytes, caps: typedict):
        super().__init__(session_options, pings,
                         disp_desc, cipher, cipher_mode, encryption_key, caps)
        self.client_protocol = client_proto
        self.server_conn = server_conn

    def __repr__(self):
        return "threaded proxy instance"

    def idle_add(self, fn: Callable, *args, **kwargs) -> int:
        return GLib.idle_add(fn, *args, **kwargs)

    def timeout_add(self, timeout, fn: Callable, *args, **kwargs) -> int:
        return GLib.timeout_add(timeout, fn, *args, **kwargs)

    def source_remove(self, tid: int) -> None:
        GLib.source_remove(tid)

    def run(self) -> None:
        log("ProxyInstanceThread.run()")
        server_protocol_class = get_server_protocol_class(self.server_conn.socktype)
        self.server_protocol = server_protocol_class(self.server_conn,
                                                     self.process_server_packet, self.get_server_packet)
        self.log_start()
        super().run()

    def start_network_threads(self) -> None:
        log("start_network_threads()")
        self.server_protocol.start()
        self.client_protocol._process_packet_cb = self.process_client_packet
        self.client_protocol.set_packet_source(self.get_client_packet)
        # no need to start the client protocol,
        # it was started when we processed authentication in the proxy server
        # self.client_protocol.start()
