# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool
from xpra.net.file_transfer import FileTransferHandler
from xpra.client.base.stub import StubClientMixin
from xpra.util.thread import start_thread
from xpra.log import Logger

GLib = gi_import("GLib")

printlog = Logger("printing")
filelog = Logger("file")

DELETE_PRINTER_FILE = envbool("XPRA_DELETE_PRINTER_FILE", True)
SKIP_STOPPED_PRINTERS = envbool("XPRA_SKIP_STOPPED_PRINTERS", True)
INIT_PRINTING_DELAY = envint("XPRA_INIT_PRINTING_DELAY", 2)


class PrinterMixin(StubClientMixin, FileTransferHandler):

    def __init__(self):
        StubClientMixin.__init__(self)
        FileTransferHandler.__init__(self)
        self.printer_attributes = []
        self.send_printers_timer: int = 0
        self.exported_printers = None

    def init(self, opts) -> None:
        FileTransferHandler.init_opts(self, opts)

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(
            "open-url", "send-file",
            "send-data-request", "send-data-response",
            "ack-file-chunk", "send-file-chunk",
        )

    def get_caps(self) -> dict[str, Any]:
        return {"printer": self.get_printer_features()}

    def cleanup(self) -> None:
        # we must clean printing before FileTransferHandler, which turns the printing flag off!
        self.cleanup_printing()
        FileTransferHandler.cleanup(self)

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.parse_printing_capabilities(c)
        self.parse_printer_caps(c)
        self.dump_remote_printing_caps()
        return True

    def parse_printing_capabilities(self, caps: typedict) -> None:
        printlog("parse_printing_capabilities() client printing support=%s", self.printing)
        if self.printing:
            server_printing = caps.boolget("printer")
            if BACKWARDS_COMPATIBLE:
                server_printing |= caps.boolget("printer.attributes")
            printlog("parse_printing_capabilities() server printing support=%s", server_printing)
            if server_printing:
                self.printer_attributes = caps.strtupleget("printer.attributes",
                                                           ("printer-info", "device-uri"))
                GLib.timeout_add(INIT_PRINTING_DELAY * 1000, self.init_printing)

    def dump_remote_printing_caps(self) -> None:
        filelog("printing remote caps:")
        filelog(" printing=%-5s        (ask=%s)", self.remote_printing, self.remote_printing_ask)

    def init_printing(self) -> None:
        try:
            from xpra.platform.printing import init_printing  # pylint: disable=import-outside-toplevel
            printlog("init_printing=%s", init_printing)
            init_printing(self.send_printers)
        except Exception as e:
            printlog.error("Error initializing printing support:")
            printlog.estr(e)
            self.printing = False
        else:
            self.send_printers()
        printlog("init_printing() enabled=%s", self.printing)

    def cleanup_printing(self) -> None:
        printlog("cleanup_printing() printing=%s", self.printing)
        if not self.printing:
            return
        self.cancel_send_printers_timer()
        try:
            from xpra.platform.printing import cleanup_printing  # pylint: disable=import-outside-toplevel
            printlog("cleanup_printing=%s", cleanup_printing)
            cleanup_printing()
        except ImportError:
            printlog("cleanup_printing()", exc_info=True)
        except Exception as e:
            printlog("cleanup_printing()", exc_info=True)
            printlog.warn("Warning: failed to cleanup printing subsystem:")
            printlog.warn(" %s", e)

    def send_printers(self, *args) -> None:
        printlog("send_printers%s timer=%s", args, self.send_printers_timer)
        # dbus can fire dozens of times for a single printer change,
        # so we wait a bit and fire via a timer to try to batch things together:
        if self.send_printers_timer:
            return
        self.send_printers_timer = GLib.timeout_add(500, self.do_send_printers)

    def cancel_send_printers_timer(self) -> None:
        spt = self.send_printers_timer
        printlog("cancel_send_printers_timer() send_printers_timer=%s", spt)
        if spt:
            self.send_printers_timer = 0
            GLib.source_remove(spt)

    def do_send_printers(self) -> None:
        self.send_printers_timer = 0
        start_thread(self.send_printers_thread, "send-printers", True)

    def send_printers_thread(self) -> None:
        from xpra.platform.printing import get_printers, get_mimetypes  # pylint: disable=import-outside-toplevel
        try:
            printers = get_printers()
        except Exception as e:
            printlog("%s", get_printers, exc_info=True)
            printlog.error("Error: cannot access the list of printers")
            printlog.estr(e)
            return
        printlog("send_printers_thread() found printers=%s", printers)
        try:
            # remove xpra-forwarded printers to avoid loops and multi-forwards,
            # also ignore stopped printers
            # and only keep the attributes that the server cares about (self.printer_attributes)
            exported_printers = {}

            def used_attrs(d):
                # filter attributes so that we only compare things that are actually used
                if not d:
                    return d
                return {pk: pv for pk, pv in d.items() if pk in self.printer_attributes}

            for k, v in printers.items():
                device_uri = v.get("device-uri", "")
                if device_uri:
                    # this is specific to the `cups` backend:
                    printlog("send_printers_thread() device-uri(%s)=%s", k, device_uri)
                    if device_uri.startswith("xpraforwarder"):
                        printlog("do_send_printers() skipping xpra forwarded printer=%s", k)
                        continue
                state = v.get("printer-state")
                # "3" if the destination is idle,
                # "4" if the destination is printing a job,
                # "5" if the destination is stopped.
                if state == 5 and SKIP_STOPPED_PRINTERS:
                    printlog("do_send_printers() skipping stopped printer=%s", k)
                    continue
                attrs = used_attrs(v)
                # add mimetypes:
                attrs["mimetypes"] = get_mimetypes()
                exported_printers[k] = attrs
            if self.exported_printers is None:
                # not been sent yet, ensure we can use the dict below:
                self.exported_printers = {}
            elif exported_printers == self.exported_printers:
                printlog("send_printers_thread() exported printers unchanged: %s", self.exported_printers)
                return
            # show summary of what has changed:
            added = tuple(k for k in exported_printers if k not in self.exported_printers)
            if added:
                printlog("send_printers_thread() new printers: %s", added)
            removed = tuple(k for k in self.exported_printers if k not in exported_printers)
            if removed:
                printlog("send_printers_thread() printers removed: %s", removed)
            modified = tuple(k for k, v in exported_printers.items() if
                             self.exported_printers.get(k) != v and k not in added)
            if modified:
                printlog("send_printers_thread() printers modified: %s", modified)
            printlog("send_printers_thread() printers=%s", exported_printers.keys())
            printlog("send_printers_thread() exported printers=%s", csv(str(x) for x in exported_printers))
            self.exported_printers = exported_printers
            self.send("printers", self.exported_printers)
        except Exception as e:
            printlog("do_send_printers()", exc_info=True)
            printlog.error("Error sending the list of printers")
            printlog.estr(e)
