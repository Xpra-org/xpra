# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
printlog = Logger("printing")
filelog = Logger("file")

from xpra.util import envbool
from xpra.net.file_transfer import FileTransferHandler
from xpra.client.mixins.stub_client_mixin import StubClientMixin


DELETE_PRINTER_FILE = envbool("XPRA_DELETE_PRINTER_FILE", True)
SKIP_STOPPED_PRINTERS = envbool("XPRA_SKIP_STOPPED_PRINTERS", True)


class FilePrintMixin(StubClientMixin, FileTransferHandler):

    def __init__(self):
        StubClientMixin.__init__(self)
        FileTransferHandler.__init__(self)
        self.printer_attributes = []
        self.send_printers_timer = 0
        self.exported_printers = None

    def init(self, opts):
        #printing and file transfer:
        FileTransferHandler.init_opts(self, opts)

    def init_authenticated_packet_handlers(self):
        self.set_packet_handlers(self._packet_handlers, {
            "open-url"          : self._process_open_url,
            "send-file"         : self._process_send_file,
            "send-data-request" : self._process_send_data_request,
            "send-data-response": self._process_send_data_response,
            "ack-file-chunk"    : self._process_ack_file_chunk,
            "send-file-chunk"   : self._process_send_file_chunk,
            })

    def get_caps(self):
        return self.get_file_transfer_features()

    def cleanup(self):
        #we must clean printing before FileTransferHandler, which turns the printing flag off!
        self.cleanup_printing()
        FileTransferHandler.cleanup(self)

    def parse_server_capabilities(self):
        self.parse_printing_capabilities()
        self.parse_file_transfer_caps(self.server_capabilities)

    def parse_printing_capabilities(self):
        printlog("parse_printing_capabilities() client printing support=%s", self.printing)
        if self.printing:
            server_printing = self.server_capabilities.boolget("printing")
            printlog("parse_printing_capabilities() server printing support=%s", server_printing)
            if server_printing:
                self.printer_attributes = self.server_capabilities.strlistget("printer.attributes", ["printer-info", "device-uri"])
                self.timeout_add(1000, self.init_printing)


    def init_printing(self):
        try:
            from xpra.platform.printing import init_printing
            printlog("init_printing=%s", init_printing)
            init_printing(self.send_printers)
        except Exception as e:
            printlog.error("Error initializing printing support:")
            printlog.error(" %s", e)
            self.printing = False
        else:
            try:
                self.do_send_printers()
            except Exception:
                printlog.error("Error sending the list of printers:", exc_info=True)
                self.printing = False
        printlog("init_printing() enabled=%s", self.printing)

    def cleanup_printing(self):
        printlog("cleanup_printing() printing=%s", self.printing)
        if not self.printing:
            return
        self.cancel_send_printers_timer()
        try:
            from xpra.platform.printing import cleanup_printing
            printlog("cleanup_printing=%s", cleanup_printing)
            cleanup_printing()
        except Exception as e:
            printlog("cleanup_printing()", exc_info=True)
            printlog.warn("Warning: failed to cleanup printing subsystem:")
            printlog.warn(" %s", e)

    def send_printers(self, *args):
        printlog("send_printers%s timer=%s", args, self.send_printers_timer)
        #dbus can fire dozens of times for a single printer change
        #so we wait a bit and fire via a timer to try to batch things together:
        if self.send_printers_timer:
            return
        self.send_printers_timer = self.timeout_add(500, self.do_send_printers)

    def cancel_send_printers_timer(self):
        spt = self.send_printers_timer
        printlog("cancel_send_printers_timer() send_printers_timer=%s", spt)
        if spt:
            self.send_printers_timer = None
            self.source_remove(spt)

    def do_send_printers(self):
        try:
            self.send_printers_timer = None
            from xpra.platform.printing import get_printers, get_mimetypes
            try:
                printers = get_printers()
            except Exception as  e:
                printlog("%s", get_printers, exc_info=True)
                printlog.error("Error: cannot access the list of printers")
                printlog.error(" %s", e)
                return
            printlog("do_send_printers() found printers=%s", printers)
            #remove xpra-forwarded printers to avoid loops and multi-forwards,
            #also ignore stopped printers
            #and only keep the attributes that the server cares about (self.printer_attributes)
            exported_printers = {}
            def used_attrs(d):
                #filter attributes so that we only compare things that are actually used
                if not d:
                    return d
                return dict((k,v) for k,v in d.items() if k in self.printer_attributes)
            for k,v in printers.items():
                device_uri = v.get("device-uri", "")
                if device_uri:
                    #this is cups specific.. oh well
                    printlog("do_send_printers() device-uri(%s)=%s", k, device_uri)
                    if device_uri.startswith("xpraforwarder"):
                        printlog("do_send_printers() skipping xpra forwarded printer=%s", k)
                        continue
                state = v.get("printer-state")
                #"3" if the destination is idle,
                #"4" if the destination is printing a job,
                #"5" if the destination is stopped.
                if state==5 and SKIP_STOPPED_PRINTERS:
                    printlog("do_send_printers() skipping stopped printer=%s", k)
                    continue
                attrs = used_attrs(v)
                #add mimetypes:
                attrs["mimetypes"] = get_mimetypes()
                exported_printers[k.encode("utf8")] = attrs
            if self.exported_printers is None:
                #not been sent yet, ensure we can use the dict below:
                self.exported_printers = {}
            elif exported_printers==self.exported_printers:
                printlog("do_send_printers() exported printers unchanged: %s", self.exported_printers)
                return
            #show summary of what has changed:
            added = [k for k in exported_printers.keys() if k not in self.exported_printers]
            if added:
                printlog("do_send_printers() new printers: %s", added)
            removed = [k for k in self.exported_printers.keys() if k not in exported_printers]
            if removed:
                printlog("do_send_printers() printers removed: %s", removed)
            modified = [k for k,v in exported_printers.items() if self.exported_printers.get(k)!=v and k not in added]
            if modified:
                printlog("do_send_printers() printers modified: %s", modified)
            printlog("do_send_printers() printers=%s", exported_printers.keys())
            printlog("do_send_printers() exported printers=%s", ", ".join(str(x) for x in exported_printers.keys()))
            self.exported_printers = exported_printers
            self.send("printers", self.exported_printers)
        except:
            printlog.error("do_send_printers()", exc_info=True)
