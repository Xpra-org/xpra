# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import hashlib

from xpra.log import Logger
printlog = Logger("printing")
filelog = Logger("file")

from xpra.simple_stats import to_std_unit
from xpra.os_util import bytestostr, WIN32
from xpra.util import engs, repr_ellipsized
from xpra.net.file_transfer import FileTransferAttributes
from xpra.server.mixins.stub_server_mixin import StubServerMixin


SAVE_PRINT_JOBS = os.environ.get("XPRA_SAVE_PRINT_JOBS", None)


"""
Mixin for servers that can handle file transfers and forwarded printers.
Printer forwarding is only supported on Posix servers with the cups backend script.
"""
class FilePrintServer(StubServerMixin):

    def __init__(self):
        self.lpadmin = ""
        self.lpinfo = ""
        self.add_printer_options = []
        self.file_transfer = FileTransferAttributes()

    def init(self, opts):
        self.file_transfer.init_opts(opts, can_ask=False)
        self.lpadmin = opts.lpadmin
        self.lpinfo = opts.lpinfo
        self.add_printer_options = opts.add_printer_options
        #server-side printer handling is only for posix via pycups for now:
        self.postscript_printer = opts.postscript_printer
        self.pdf_printer = opts.pdf_printer

    def threaded_setup(self):
        self.init_printing()


    def get_server_features(self, _source):
        f = self.file_transfer.get_file_transfer_features()
        f["printer.attributes"] = ("printer-info", "device-uri") 
        f.update(self.file_transfer.get_file_transfer_features())
        return f

    def get_info(self, _proto):
        d = {
            "lpadmin"              : self.lpadmin,
            "lpinfo"               : self.lpinfo,
            "add-printer-options"  : self.add_printer_options,
            },
        if self.file_transfer.printing:
            from xpra.platform.printing import get_info
            d.update(get_info())
        info = {"printing" : d}
        if self.file_transfer.file_transfer:
            info["file"] = self.file_transfer.get_info()
        return info


    def init_printing(self):
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
            printer_definitions = pycups_printing.validate_setup()
            printing = bool(printer_definitions)
            if printing:
                printlog.info("printer forwarding enabled using %s", " and ".join([x.replace("application/", "") for x in printer_definitions.keys()]))
            else:
                printlog.warn("Warning: no printer definitions found,")
                printlog.warn(" cannot enable printer forwarding")
        except ImportError as e:
            printlog("printing module is not installed: %s", e)
            printing = False
        except Exception:
            printlog.error("Error: failed to set lpadmin and lpinfo commands", exc_info=True)
            printing = False
        #verify that we can talk to the socket:
        auth_class = self.auth_classes.get("unix-domain")
        if printing and auth_class:
            try:
                #this should be the name of the auth module:
                auth_name = auth_class[0]
            except:
                auth_name = str(auth_class)
            if auth_name not in ("none", "file"):
                printlog.warn("Warning: printing conflicts with socket authentication module '%s'", auth_name)
                printing = False
        #update file transfer attributes since printing nay have been disabled here
        self.file_transfer.printing = printing
        printlog("init_printing() printing=%s", printing)

    def _process_print(self, _proto, packet):
        #ie: from the xpraforwarder we call this command:
        #command = ["xpra", "print", "socket:/path/tosocket", filename, mimetype, source, title, printer, no_copies, print_options]
        assert self.file_transfer.printing
        #printlog("_process_print(%s, %s)", proto, packet)
        if len(packet)<3:
            printlog.error("Error: invalid print packet, only %i arguments", len(packet))
            printlog.error(" %s", [repr_ellipsized(x) for x in packet])
            return
        filename, file_data = packet[1:3]
        mimetype, source_uuid, title, printer, no_copies, print_options = "", "*", "unnamed document", "", 1, ""
        if len(packet)>=4:
            mimetype = packet[3]
        if len(packet)>=5:
            source_uuid = packet[4]
        if len(packet)>=6:
            title = packet[5]
        if len(packet)>=7:
            printer = packet[6]
        if len(packet)>=8:
            no_copies = int(packet[7])
        if len(packet)>=9:
            print_options = packet[8]
        #parse and validate:
        if len(mimetype)>=128:
            printlog.error("Error: invalid mimetype in print packet:")
            printlog.error(" %s", repr_ellipsized(mimetype))
            return
        if type(print_options)!=dict:
            s = bytestostr(print_options)
            print_options = {}
            for x in s.split(" "):
                parts = x.split("=", 1)
                if len(parts)==2:
                    print_options[parts[0]] = parts[1]
        printlog("process_print: %s", (filename, mimetype, "%s bytes" % len(file_data), source_uuid, title, printer, no_copies, print_options))
        printlog("process_print: got %s bytes for file %s", len(file_data), filename)
        #parse the print options:
        u = hashlib.sha1()
        u.update(file_data)
        printlog("sha1 digest: %s", u.hexdigest())
        options = {
            "printer"    : printer,
            "title"      : title,
            "copies"     : no_copies,
            "options"    : print_options,
            "sha1"       : u.hexdigest(),
            }
        printlog("parsed printer options: %s", options)
        if SAVE_PRINT_JOBS:
            self._save_print_job(filename, file_data)

        sent = 0
        sources = tuple(self._server_sources.values())
        printlog("will try to send to %i clients: %s", len(sources), sources)
        for ss in sources:
            if source_uuid!='*' and ss.uuid!=source_uuid:
                printlog("not sending to %s (wanted uuid=%s)", ss, source_uuid)
                continue
            if not ss.printing:
                if source_uuid!='*':
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
        #warn if not sent:
        if sent==0:
            l = printlog.warn
        else:
            l = printlog.info
        unit_str, v = to_std_unit(len(file_data), unit=1024)
        l("'%s' (%i%sB) sent to %i client%s for printing", title or filename, v, unit_str, sent, engs(sent))

    def _save_print_job(self, filename, file_data):
        try:
            save_filename = os.path.join(SAVE_PRINT_JOBS, filename)
            with open(save_filename, "wb") as f:
                f.write(file_data)
            printlog.info("saved print job to: %s", save_filename)
        except Exception as e:
            printlog.error("Error: failed to save print job to %s", save_filename)
            printlog.error(" %s", e)

    def _process_printers(self, proto, packet):
        if not self.file_transfer.printing or WIN32:
            printlog.error("Error: received printer definitions data")
            printlog.error(" but this server does not support printer forwarding")
            return
        ss = self._server_sources.get(proto)
        if ss is None:
            return
        printers = packet[1]
        auth_class = self.auth_classes.get("unix-domain")
        ss.set_printers(printers, self.password_file, auth_class, self.encryption, self.encryption_keyfile)


    ######################################################################
    # file transfers:
    def _process_send_file(self, proto, packet):
        ss = self._server_sources.get(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for send-file packet")
            return
        ss._process_send_file(packet)

    def _process_ack_file_chunk(self, proto, packet):
        ss = self._server_sources.get(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for ack-file-chunk packet")
            return
        ss._process_ack_file_chunk(packet)

    def _process_send_file_chunk(self, proto, packet):
        ss = self._server_sources.get(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for send-file-chunk packet")
            return
        ss._process_send_file_chunk(packet)

    def _process_send_data_request(self, proto, packet):
        ss = self._server_sources.get(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for send-file-request packet")
            return
        ss._process_send_data_request(packet)

    def _process_send_data_response(self, proto, packet):
        ss = self._server_sources.get(proto)
        if not ss:
            printlog.warn("Warning: invalid client source for send-data-response packet")
            return
        ss._process_send_data_response(packet)


    def init_packet_handlers(self):
        self._authenticated_packet_handlers = {
            "printers":                             self._process_printers,
            "send-file":                            self._process_send_file,
            "ack-file-chunk":                       self._process_ack_file_chunk,
            "send-file-chunk":                      self._process_send_file_chunk,
            "send-data-request":                    self._process_send_data_request,
            "send-data-response":                   self._process_send_data_response,
            "print":                                self._process_print,
          }
