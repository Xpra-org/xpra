# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.
# pylint: disable-msg=E1101

import os.path
import hashlib
from typing import Any
from collections.abc import Sequence

from xpra.util.stats import to_std_unit, std_unit
from xpra.os_util import WIN32, POSIX
from xpra.util.env import osexpand
from xpra.util.io import load_binary_file
from xpra.util.str_fn import repr_ellipsized, csv
from xpra.common import NotificationID
from xpra.auth.auth_helper import AuthDef
from xpra.net.common import PacketType
from xpra.net.file_transfer import FileTransferAttributes
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

printlog = Logger("printing")
filelog = Logger("file")

SAVE_PRINT_JOBS = os.environ.get("XPRA_SAVE_PRINT_JOBS", None)


def _save_print_job(filename, file_data) -> None:
    save_filename = os.path.join(SAVE_PRINT_JOBS, filename)
    try:
        with open(save_filename, "wb") as f:
            f.write(file_data)
        printlog.info("saved print job to: %s", save_filename)
    except Exception as e:
        printlog.error("Error: failed to save print job to %s", save_filename)
        printlog.estr(e)


class FilePrintServer(StubServerMixin):
    """
    Mixin for servers that can handle file transfers and forwarded printers.
    Printer forwarding is only supported on Posix servers with the cups backend script.
    """

    def __init__(self):
        self.lpadmin: str = ""
        self.lpinfo: str = ""
        self.add_printer_options = []
        self.file_transfer = FileTransferAttributes()

    def init(self, opts) -> None:
        self.file_transfer.init_opts(opts, can_ask=False)
        self.lpadmin = opts.lpadmin
        self.lpinfo = opts.lpinfo
        self.add_printer_options = opts.add_printer_options
        # server-side printer handling is only for posix via pycups for now:
        self.postscript_printer = opts.postscript_printer
        self.pdf_printer = opts.pdf_printer

    def threaded_setup(self) -> None:
        self.init_printing()

    def init_sockets(self, sockets) -> None:
        # verify we have a local socket for printing:
        unixsockets = [info for socktype, _, info, _ in sockets if socktype == "socket"]
        printlog("local unix domain sockets we can use for printing: %s", unixsockets)
        if not unixsockets and self.file_transfer.printing:
            if not WIN32:
                printlog.warn("Warning: no local sockets defined,")
                printlog.warn(" disabling printer forwarding")
            printlog("printer forwarding disabled")
            self.file_transfer.printing = False

    def get_server_features(self, _source) -> dict[str, Any]:
        f = self.file_transfer.get_file_transfer_features()
        f["printer.attributes"] = ("printer-info", "device-uri")
        ftf = self.file_transfer.get_file_transfer_features()
        if self.file_transfer.file_transfer:
            ftf["request-file"] = True
        f.update(ftf)
        return f

    def get_info(self, _proto) -> dict[str, Any]:
        d = {}
        if POSIX:
            d.update({
                "lpadmin": self.lpadmin,
                "lpinfo": self.lpinfo,
                "add-printer-options": self.add_printer_options,
            })
        if self.file_transfer.printing:
            from xpra.platform.printing import get_info
            d.update(get_info())
        info = {"printing": d}
        if self.file_transfer.file_transfer:
            fti = self.file_transfer.get_info()
            if self.file_transfer.file_transfer:
                fti["request-file"] = True
            info["file"] = fti
        return info

    def init_printing(self) -> None:
        printing = self.file_transfer.printing
        if not printing or WIN32:
            return
        try:
            from xpra.platform import pycups_printing
            pycups_printing.set_lpadmin_command(self.lpadmin)
            pycups_printing.set_lpinfo_command(self.lpinfo)
            pycups_printing.set_add_printer_options(self.add_printer_options)
            if self.postscript_printer:
                pycups_printing.add_printer_def("application/postscript", self.postscript_printer)
            if self.pdf_printer:
                pycups_printing.add_printer_def("application/pdf", self.pdf_printer)
            printer_definitions = pycups_printing.get_printer_definitions()
            printing = bool(printer_definitions)
            if printing:
                printlog.info("printer forwarding enabled using %s", " and ".join(
                    x.replace("application/", "") for x in printer_definitions))
            else:
                printlog.warn("Warning: no printer definitions found,")
                printlog.warn(" cannot enable printer forwarding")
        except ImportError as e:
            printlog("printing module is not installed: %s", e)
            printing = False
        except Exception:
            printlog.error("Error: failed to set lpadmin and lpinfo commands", exc_info=True)
            printing = False
        # verify that we can talk to the socket:
        auth_classes: Sequence[AuthDef] = self.auth_classes.get("socket", ())
        if printing and auth_classes:
            fail: list[str] = []
            for auth_class in auth_classes:
                try:
                    # this should be the name of the auth module:
                    auth_name = auth_class[0]
                except Exception:
                    auth_name = str(auth_class)
                if auth_name not in ("allow", "file", "hosts", "none", "peercred"):
                    fail.append(auth_name)
            if fail:
                printlog.warn("Warning: printer forwarding is not supported")
                printlog.warn(" with sockets using authentication modules %s", csv(fail))
                printing = False
        # update file transfer attributes since printing nay have been disabled here
        self.file_transfer.printing = printing
        printlog("init_printing() printing=%s", printing)

    def _process_print(self, _proto, packet: PacketType) -> None:
        # ie: from the xpraforwarder we call this command:
        # command = ["xpra", "print", "socket:/path/tosocket",
        #           filename, mimetype, source, title, printer, no_copies, print_options]
        assert self.file_transfer.printing
        # printlog("_process_print(%s, %s)", proto, packet)
        if len(packet) < 3:
            printlog.error("Error: invalid print packet, only %i arguments", len(packet))
            printlog.error(" %s", [repr_ellipsized(x) for x in packet])
            return
        filename = str(packet[1])
        file_data = packet[2]
        mimetype, source_uuid, title, printer, no_copies, print_options = "", "*", "unnamed document", "", 1, ""
        if len(packet) >= 4:
            mimetype = str(packet[3])
        if len(packet) >= 5:
            source_uuid = str(packet[4])
        if len(packet) >= 6:
            title = str(packet[5])
        if len(packet) >= 7:
            printer = str(packet[6])
        if len(packet) >= 8:
            no_copies = int(packet[7])
        if len(packet) >= 9:
            print_options = packet[8]
        # parse and validate:
        if len(mimetype) >= 128:
            printlog.error("Error: invalid mimetype in print packet:")
            printlog.error(" %s", repr_ellipsized(mimetype))
            return
        if not isinstance(print_options, dict):
            s = str(print_options)
            print_options = {}
            for x in s.split(" "):
                parts = x.split("=", 1)
                if len(parts) == 2:
                    print_options[parts[0]] = parts[1]
        printlog("process_print: %s", (filename, mimetype, "%s bytes" % len(file_data),
                                       source_uuid, title, printer, no_copies, print_options))
        printlog("process_print: got %s bytes for file %s", len(file_data), filename)
        # parse the print options:
        hu = hashlib.sha256()
        hu.update(file_data)
        printlog("sha1 digest: %s", hu.hexdigest())
        options = {
            "printer": printer,
            "title": title,
            "copies": no_copies,
            "options": print_options,
            "sha256": hu.hexdigest(),
        }
        printlog("parsed printer options: %s", options)
        if SAVE_PRINT_JOBS:
            _save_print_job(filename, file_data)

        sent = 0
        sources = tuple(self._server_sources.values())
        printlog("will try to send to %i clients: %s", len(sources), sources)
        for ss in sources:
            if source_uuid not in ("*", ss.uuid):
                printlog("not sending to %s (uuid=%s, wanted uuid=%s)", ss, ss.uuid, source_uuid)
                continue
            if not ss.printing:
                if source_uuid != '*':
                    printlog.warn("Warning: printing is not enabled for:")
                    printlog.warn(" %s", ss)
                else:
                    printlog("printing is not enabled for %s", ss)
                continue
            if not ss.printers:
                printlog.warn("Warning: client %s does not have any printers", ss.uuid)
                continue
            if printer not in ss.printers:
                printlog.warn("Warning: client %s does not have a '%s' printer", ss.uuid, printer)
                continue
            printlog("'%s' sent to %s for printing on '%s'", title or filename, ss, printer)
            if ss.send_file(filename, mimetype, file_data, len(file_data), True, True, options):
                sent += 1
        # warn if not sent:
        log_fn = printlog.warn if sent == 0 else printlog.info
        unit_str, v = to_std_unit(len(file_data), unit=1024)
        log_fn("'%s' (%i%sB) sent to %i clients for printing", title or filename, v, unit_str, sent)

    def _process_printers(self, proto, packet: PacketType) -> None:
        if not self.file_transfer.printing or WIN32:
            printlog.error("Error: received printer definitions data")
            printlog.error(" but this server does not support printer forwarding")
            return
        ss = self.get_server_source(proto)
        if ss is None:
            return
        printers = dict(packet[1])
        auth_class: Sequence[AuthDef] = self.auth_classes.get("socket", ())
        ss.set_printers(printers, self.password_file, auth_class, self.encryption, self.encryption_keyfile)

    ######################################################################
    # file transfers:
    def _process_send_file(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for send-file packet")
            return
        ss._process_send_file(packet)

    def _process_ack_file_chunk(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for ack-file-chunk packet")
            return
        ss._process_ack_file_chunk(packet)

    def _process_send_file_chunk(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for send-file-chunk packet")
            return
        ss._process_send_file_chunk(packet)

    def _process_send_data_request(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for send-file-request packet")
            return
        ss._process_send_data_request(packet)

    def _process_send_data_response(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for send-data-response packet")
            return
        ss._process_send_data_response(packet)

    def _process_request_file(self, proto, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            filelog.warn("Warning: invalid client source for send-data-response packet")
            return
        argf = str(packet[1])
        if argf == "${XPRA_SERVER_LOG}" and not os.environ.get("XPRA_SERVER_LOG"):
            filelog("no server log to send")
            return
        openit = packet[2]
        filename = os.path.abspath(osexpand(argf))
        if not os.path.exists(filename):
            filelog.warn("Warning: the file requested does not exist:")
            filelog.warn(f" {filename!r}")
            ss.may_notify(NotificationID.FILETRANSFER,
                          "File not found", "The file requested does not exist:\n%s" % filename,
                          icon_name="file")
            return
        try:
            stat = os.stat(filename)
            filelog("os.stat(%s)=%s", filename, stat)
        except os.error:
            filelog("os.stat(%s)", filename, exc_info=True)
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
        if self.file_transfer.printing:
            self.add_packets("printers", "print")
        if self.file_transfer.printing or self.file_transfer.file_transfer:
            self.add_packets("send-file", "ack-file-chunk", "send-file-chunk",
                             "send-data-request", "send-data-response")
        if self.file_transfer.file_transfer:
            self.add_packets("request-file")
