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

from xpra.exit_codes import ExitCode
from xpra.util.stats import to_std_unit
from xpra.os_util import WIN32, POSIX
from xpra.util.str_fn import repr_ellipsized, csv
from xpra.auth.auth_helper import AuthDef
from xpra.util.objects import typedict
from xpra.net.common import Packet
from xpra.net.constants import ConnectionMessage
from xpra.net.file_transfer import FileTransferAttributes
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("printing")

SAVE_PRINT_JOBS = os.environ.get("XPRA_SAVE_PRINT_JOBS", None)


def _save_print_job(filename, file_data) -> None:
    save_filename = os.path.join(SAVE_PRINT_JOBS, filename)
    try:
        with open(save_filename, "wb") as f:
            f.write(file_data)
        log.info("saved print job to: %s", save_filename)
    except Exception as e:
        log.error("Error: failed to save print job to %s", save_filename)
        log.estr(e)


class PrinterServer(StubServerMixin):
    """
    Mixin for servers that can handle forwarded printers.
    Printer forwarding is only supported on Posix servers with the cups backend script.
    """
    PREFIX = "printer"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.lpadmin: str = ""
        self.lpinfo: str = ""
        self.add_printer_options = []
        # self.file_transfer is already initialized by FileServer,
        # so this is redundant except for subsystem unit tests:
        self.file_transfer = FileTransferAttributes()
        self.hello_request_handlers["print"] = self._handle_hello_request_print

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

    def setup(self) -> None:
        # verify we have a local socket for printing:
        sockets = getattr(self, "sockets", ())
        unixsockets = [sock.address for sock in sockets if sock.socktype == "socket"]
        log("local unix domain sockets we can use for printing: %s", unixsockets)
        if not unixsockets and self.file_transfer.printing:
            if not WIN32:
                log.warn("Warning: no local sockets defined,")
                log.warn(" disabling printer forwarding")
            log("printer forwarding disabled")
            self.file_transfer.printing = False

    def get_server_features(self, _source) -> dict[str, Any]:
        f = self.file_transfer.get_printer_features()
        f["attributes"] = ("printer-info", "device-uri")
        return {PrinterServer.PREFIX: f}

    def get_info(self, _proto) -> dict[str, Any]:
        info = {}
        if POSIX:
            info.update({
                "lpadmin": self.lpadmin,
                "lpinfo": self.lpinfo,
                "add-printer-options": self.add_printer_options,
            })
        if self.file_transfer.printing:
            from xpra.platform.printing import get_info
            info.update(get_info())
        return {PrinterServer.PREFIX: info}

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
                log.info("printer forwarding enabled using %s", " and ".join(
                    x.replace("application/", "") for x in printer_definitions))
            else:
                log.warn("Warning: no printer definitions found,")
                log.warn(" cannot enable printer forwarding")
        except ImportError as e:
            log("printing module is not installed: %s", e)
            printing = False
        except Exception:
            log.error("Error: failed to set lpadmin and lpinfo commands", exc_info=True)
            printing = False
        # verify that we can talk to the socket
        # (weak dependency on `auth_classes`)
        auth_classes: dict[str, Sequence[AuthDef]] = getattr(self, "auth_classes", {})
        socket_auth_classes: Sequence[AuthDef] = auth_classes.get("socket", ())
        if printing and socket_auth_classes:
            fail: list[str] = []
            for auth_class in socket_auth_classes:
                try:
                    # this should be the name of the auth module:
                    auth_name = auth_class[0]
                except (TypeError, IndexError):
                    auth_name = str(auth_class)
                if auth_name not in ("allow", "file", "hosts", "none", "peercred"):
                    fail.append(auth_name)
            if fail:
                log.warn("Warning: printer forwarding is not supported")
                log.warn(" with sockets using authentication modules %s", csv(fail))
                printing = False
        # update file transfer attributes since printing nay have been disabled here
        self.file_transfer.printing = printing
        log("init_printing() printing=%s", printing)

    def _handle_hello_request_print(self, proto, caps: typedict) -> bool:
        print_packet = caps.tupleget("print")
        if not print_packet:
            raise RuntimeError("print data is missing!")
        code, message = self.do_print_file(Packet(*print_packet))
        # minimal hello:
        from xpra.net.packet_encoding import get_packet_encoding_caps
        hello = get_packet_encoding_caps()
        hello[PrinterServer.PREFIX] ={
            "code": int(code),
            "info": message,
        }
        proto.send_now(Packet("hello", hello))
        self.send_disconnect(proto, ConnectionMessage.DONE)
        return True

    def _process_print_file(self, _proto, packet: Packet) -> None:
        code, message = self.do_print_file(packet)
        if code != ExitCode.OK:
            log.warn(message)

    def do_print_file(self, packet: Packet) -> tuple[ExitCode, str]:
        # ie: from the xpraforwarder we call this command:
        # command = ["xpra", "print", "socket:/path/tosocket",
        #           filename, mimetype, source, title, printer, no_copies, print_options]
        assert self.file_transfer.printing
        # log("_process_print(%s, %s)", proto, packet)
        if len(packet) < 3:
            log.error("Error: invalid print packet, only %i arguments", len(packet))
            log.error(" %s", [repr_ellipsized(x) for x in packet])
            return ExitCode.PACKET_FAILURE, "invalid print packet format"
        filename = packet.get_str(1)
        file_data = packet.get_bytes(2)
        mimetype, source_uuid, title, printer, no_copies, print_options = "", "*", "unnamed document", "", 1, ""
        if len(packet) >= 4:
            mimetype = packet.get_str(3)
        if len(packet) >= 5:
            source_uuid = packet.get_str(4)
        if len(packet) >= 6:
            title = packet.get_str(5)
        if len(packet) >= 7:
            printer = packet.get_str(6)
        if len(packet) >= 8:
            no_copies = packet.get_u16(7)
        if len(packet) >= 9:
            print_options = packet.get_str(8)
        # parse and validate:
        if len(mimetype) >= 128:
            log.error("Error: invalid mimetype in print packet:")
            log.error(" %s", repr_ellipsized(mimetype))
            return ExitCode.UNSUPPORTED, "invalid mimetype"
        if not isinstance(print_options, dict):
            s = str(print_options)
            print_options = {}
            for x in s.split(" "):
                parts = x.split("=", 1)
                if len(parts) == 2:
                    print_options[parts[0]] = parts[1]
        log("process_print: %s", (filename, mimetype, "%s bytes" % len(file_data),
                                  source_uuid, title, printer, no_copies, print_options))
        log("process_print: got %s bytes for file %s", len(file_data), filename)
        # parse the print options:
        hu = hashlib.sha256()
        hu.update(file_data)
        log("sha1 digest: %s", hu.hexdigest())
        options = {
            "printer": printer,
            "title": title,
            "copies": no_copies,
            "options": print_options,
            "sha256": hu.hexdigest(),
        }
        log("parsed printer options: %s", options)
        if SAVE_PRINT_JOBS:
            _save_print_job(filename, file_data)

        sent = 0
        sources = tuple(self._server_sources.values())
        log("will try to send to %i clients: %s", len(sources), sources)
        for ss in sources:
            if source_uuid not in ("*", ss.uuid):
                log("not sending to %s (uuid=%s, wanted uuid=%s)", ss, ss.uuid, source_uuid)
                continue
            if not ss.printing:
                if source_uuid != '*':
                    log.warn("Warning: printing is not enabled for:")
                    log.warn(" %s", ss)
                else:
                    log("printing is not enabled for %s", ss)
                continue
            if not ss.printers:
                log.warn("Warning: client %s does not have any printers", ss.uuid)
                continue
            if printer not in ss.printers:
                log.warn("Warning: client %s does not have a '%s' printer", ss.uuid, printer)
                continue
            log("'%s' sent to %s for printing on '%s'", title or filename, ss, printer)
            if ss.send_file(filename, mimetype, file_data, len(file_data), True, True, options):
                sent += 1
        unit_str, v = to_std_unit(len(file_data), unit=1024)
        message = "'%s' (%i%sB) sent to %i clients for printing" % (title or filename, v, unit_str, sent)
        log(message)
        return ExitCode.OK if sent > 0 else ExitCode.REMOTE_ERROR, message

    def _process_printers(self, proto, packet: Packet) -> None:
        if not self.file_transfer.printing or WIN32:
            log.error("Error: received printer definitions data")
            log.error(" but this server does not support printer forwarding")
            return
        ss = self.get_server_source(proto)
        if ss is None:
            return
        printers = packet.get_dict(1)
        auth_class: Sequence[AuthDef] = self.auth_classes.get("socket", ())
        # optional dependency on `self.password_file` from AuthServer:
        password_file: Sequence[str] = getattr(self, "password_file", ())
        # optional dependency on `self.encryption[_keyfile]` from EncryptionServer:
        encryption = getattr(self, "encryption", "")
        encryption_keyfile = getattr(self, "encryption_keyfile", "")
        ss.set_printers(printers, password_file, auth_class, encryption, encryption_keyfile)

    def init_packet_handlers(self) -> None:
        # noqa: E241
        if self.file_transfer.printing:
            self.add_packets("printers", "print")
