# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os
import re

from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer
from xpra.net.common import Packet
from xpra.net.packet_type import INFO_REQUEST, INFO_RESPONSE
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

log = Logger("network")

# LOG_INFO_RESPONSE = ("^window.*position", "^window.*size$")
LOG_INFO_RESPONSE: str = os.environ.get("XPRA_LOG_INFO_RESPONSE", "")


class ServerInfoClient(StubClientMixin):
    """
    Request `info` from server.
    """
    PREFIX = "server-info"

    def __init__(self, client=None):
        StubClientMixin.__init__(self, client)
        self.last_info: dict = {}
        self.request_pending: bool = False

        def request_initial_info(*_args) -> None:
            self.send_info_request()
        self.client.connect("startup-complete", request_initial_info)

    def _process_info_response(self, packet: Packet) -> None:
        self.request_pending = False
        self.last_info = typedict(packet.get_dict(1))
        log("info-response: %s", Ellipsizer(self.last_info))
        if LOG_INFO_RESPONSE:
            items = LOG_INFO_RESPONSE.split(",")
            logres = [re.compile(v) for v in items]
            log.info("info-response debug for %s:", csv("'%s'" % x for x in items))
            for k in sorted(self.last_info.keys()):
                if LOG_INFO_RESPONSE == "all" or any(lr.match(k) for lr in logres):
                    log.info(" %s=%s", k, self.last_info[k])

    def send_info_request(self, *categories: str) -> None:
        if not self.request_pending:
            self.request_pending = True
            window_ids = ()  # no longer used or supported by servers
            self.send(INFO_REQUEST, [self.get_subsystem("clientid").uuid], window_ids, categories)

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(INFO_RESPONSE)
