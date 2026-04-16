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
from xpra.common import may_notify_client
from xpra.constants import NotificationID
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
        self.add_file_control_commands()

    def add_file_control_commands(self) -> None:
        ac = self.args_control
        ac("print", "sends the file to the client(s) for printing", min_args=1)
        ac("open-url", "open the URL on the client(s)", min_args=1, max_args=2)
        ac("send-file", "sends the file to the client(s)", min_args=1, max_args=4)

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
    def _process_file_send(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for send-file packet")
            return
        ss._process_file_send(packet)

    def _process_file_ack_chunk(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for ack-file-chunk packet")
            return
        ss._process_file_ack_chunk(packet)

    def _process_file_send_chunk(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for send-file-chunk packet")
            return
        ss._process_file_send_chunk(packet)

    def _process_file_data_request(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for send-file-request packet")
            return
        ss._process_file_data_request(packet)

    def _process_file_data_response(self, proto, packet: Packet) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            log.warn("Warning: invalid client source for send-data-response packet")
            return
        ss._process_file_data_response(packet)

    def _process_file_request(self, proto, packet: Packet) -> None:
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
            may_notify_client(ss, NotificationID.FILETRANSFER,
                              "File not found", "The file requested does not exist:\n%s" % filename, icon_name="file")
            return
        try:
            stat = os.stat(filename)
            log("os.stat(%s)=%s", filename, stat)
        except os.error:
            log("os.stat(%s)", filename, exc_info=True)
        else:
            file_size = stat.st_size
            if file_size > self.file_transfer.file_size_limit or file_size > ss.file_size_limit:
                may_notify_client(ss, NotificationID.FILETRANSFER,
                                  "File too large",
                                  "The file requested is too large to send:\n%s\nis %s" % (argf, std_unit(file_size)),
                                  icon_name="file")
                return
        data = load_binary_file(filename)
        ss.send_file(filename, "", data, len(data), openit=openit, options={"request-file": (argf, openit)})

    def init_packet_handlers(self) -> None:
        # noqa: E241
        if self.file_transfer.printing or self.file_transfer.file_transfer:
            self.add_legacy_alias("send-file", "file-send")
            self.add_legacy_alias("ack-file-chunk", "file-ack-chunk")
            self.add_legacy_alias("send-file-chunk", "file-send-chunk")
            self.add_legacy_alias("send-data-request", "file-date-request")
            self.add_legacy_alias("send-data-response", "file-date-response")

            self.add_packets("file-send", "file-ack-chunk", "file-send-chunk",
                             "file-data-request", "file-data-response")

        if self.file_transfer.file_transfer:
            self.add_legacy_alias("request-file", "file-request")
            self.add_packets("file-request")

    #########################################
    # Control Commands
    #########################################

    def control_command_open_url(self, url: str, client_uuids="*") -> str:
        # find the clients:
        from xpra.net.control.common import control_get_sources, ControlError
        sources = control_get_sources(self, client_uuids)
        if not sources:
            raise ControlError(f"no clients found matching: {client_uuids!r}")
        clients = 0
        for ss in sources:
            if hasattr(ss, "send_open_url") and ss.send_open_url(url):
                clients += 1
        return f"url sent to {clients} clients"

    def control_command_send_file(self, filename: str, openit="open", client_uuids="*", maxbitrate=0) -> str:
        # we always get the values as strings from the command interface,
        # but those may actually be utf8 encoded binary strings,
        # so we may have to do an ugly roundtrip:
        openit = str(openit).lower() in ("open", "true", "1")
        return self.do_control_file_command("send file", client_uuids, filename, "file_transfer", (False, openit))

    def control_command_print(self, filename: str, printer="", client_uuids="*",
                              maxbitrate=0, title="", *options_strs) -> str:
        # FIXME: printer and bitrate are ignored
        # parse options into a dict:
        options = {}
        for arg in options_strs:
            argp = arg.split("=", 1)
            if len(argp) == 2 and len(argp[0]) > 0:
                options[argp[0]] = argp[1]
        return self.do_control_file_command("print", client_uuids, filename, "printing", (True, True, options))

    def do_control_file_command(self, command_type: str, client_uuids, filename: str, source_flag_name, send_file_args) -> str:
        # find the clients:
        from xpra.net.control.common import control_get_sources, ControlError
        sources = control_get_sources(self, client_uuids)
        if not sources:
            raise ControlError(f"no clients found matching: {client_uuids!r}")

        filelog = Logger("command", "file")

        def checksize(file_size):
            if file_size > self.file_transfer.file_size_limit:
                raise ControlError("file '%s' is too large: %sB (limit is %sB)" % (
                    filename, std_unit(file_size), std_unit(self.file_transfer.file_size_limit)))

        # find the file and load it:
        actual_filename = os.path.abspath(os.path.expanduser(filename))
        try:
            stat = os.stat(actual_filename)
            filelog("os.stat(%s)=%s", actual_filename, stat)
        except os.error:
            filelog("os.stat(%s)", actual_filename, exc_info=True)
        else:
            checksize(stat.st_size)
        if not os.path.exists(actual_filename):
            raise ControlError(f"file {filename!r} does not exist")
        data = load_binary_file(actual_filename)
        if not data:
            raise ControlError(f"no data loaded from {actual_filename!r}")
        # verify size:
        file_size = len(data)
        checksize(file_size)
        # send it to each client:
        for ss in sources:
            # ie: ServerSource.file_transfer (found in FileTransferAttributes)
            #     and ServerSource.remote_file_transfer (found in FileTransferHandler)
            server_support = getattr(ss, source_flag_name, False)
            client_support = getattr(ss, f"remote_{source_flag_name}", False)
            if not (server_support and client_support):
                # skip the warning if the client is not interactive
                # (for now just check for 'top' client):
                if not hasattr(ss, source_flag_name) or ss.client_type == "top":
                    log_fn = filelog.debug
                else:
                    log_fn = filelog.warn
                log_fn(f"Warning: cannot {command_type} {filename!r} to {ss.client_type} client")
                log_fn(f" feature flag {source_flag_name!r}")
                if not server_support:
                    log_fn(" this feature is not supported by the server connection")
                if not client_support:
                    log_fn(f" client {ss.uuid} does not support this feature")
            elif file_size > ss.file_size_limit:
                filelog.warn(f"Warning: cannot {command_type} {filename!r}")
                filelog.warn(" client %s file size limit is %sB (file is %sB)",
                             ss, std_unit(ss.file_size_limit), std_unit(file_size))
            else:
                filelog(f"sending {filename} to {ss}")
                ss.send_file(filename, "", data, file_size, *send_file_args)
        return f"{command_type} of {filename!r} to {client_uuids} initiated"
