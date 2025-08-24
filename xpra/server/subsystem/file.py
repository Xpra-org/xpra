# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os.path
from typing import Any

from xpra.util.stats import std_unit
from xpra.util.env import osexpand
from xpra.util.io import load_binary_file
from xpra.common import NotificationID
from xpra.net.common import Packet
from xpra.net.file_transfer import FileTransferAttributes
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("file")


class FileServer(StubServerMixin):
    """
    Mixin for servers that can handle file transfers.
    This is also required for printer forwarding.
    """

    def __init__(self):
        StubServerMixin.__init__(self)
        self.file_transfer = FileTransferAttributes()

    def init(self, opts) -> None:
        self.file_transfer.init_opts(opts, can_ask=False)

    def get_server_features(self, _source) -> dict[str, Any]:
        f = self.file_transfer.get_file_transfer_features()
        if self.file_transfer.file_transfer:
            f["request-file"] = True
        return {"file": f}

    def get_info(self, _proto) -> dict[str, Any]:
        fti = {}
        if self.file_transfer.file_transfer:
            fti = self.file_transfer.get_info()
            if self.file_transfer.file_transfer:
                fti["request-file"] = True
        return {"file": fti}

    ######################################################################
    # file transfers:
    def _process_send_file(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for send-file packet")
            return
        ss._process_send_file(packet)

    def _process_ack_file_chunk(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for ack-file-chunk packet")
            return
        ss._process_ack_file_chunk(packet)

    def _process_send_file_chunk(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for send-file-chunk packet")
            return
        ss._process_send_file_chunk(packet)

    def _process_send_data_request(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for send-file-request packet")
            return
        ss._process_send_data_request(packet)

    def _process_send_data_response(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for send-data-response packet")
            return
        ss._process_send_data_response(packet)

    def _process_request_file(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for send-data-response packet")
            return
        argf = packet.get_str(1)
        if argf == "${XPRA_SERVER_LOG}" and not os.environ.get("XPRA_SERVER_LOG"):
            log("no server log to send")
            return
        openit = packet.get_bool(2)
        filename = os.path.abspath(osexpand(argf))
        if not os.path.exists(filename):
            log.warn("Warning: the file requested does not exist:")
            log.warn(f" {filename!r}")
            ss.may_notify(NotificationID.FILETRANSFER,
                          "File not found", "The file requested does not exist:\n%s" % filename,
                          icon_name="file")
            return
        try:
            stat = os.stat(filename)
            log("os.stat(%s)=%s", filename, stat)
        except os.error:
            log("os.stat(%s)", filename, exc_info=True)
        else:
            file_size = stat.st_size
            if file_size > self.file_transfer.file_size_limit or file_size > ss.file_size_limit:
                ss.may_notify(NotificationID.FILETRANSFER,
                              "File too large",
                              "The file requested is too large to send:\n%s\nis %s" % (argf, std_unit(file_size)),
                              icon_name="file")
                return
        data = load_binary_file(filename)
        ss.send_file(filename, "", data, len(data), openit=openit, options={"request-file": (argf, openit)})

    def init_packet_handlers(self) -> None:
        # noqa: E241
        if self.file_transfer.printing or self.file_transfer.file_transfer:
            self.add_packets("send-file", "ack-file-chunk", "send-file-chunk",
                             "send-data-request", "send-data-response")
        if self.file_transfer.file_transfer:
            self.add_packets("request-file")
