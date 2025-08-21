# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.net.file_transfer import FileTransferHandler
from xpra.client.base.stub import StubClientMixin
from xpra.log import Logger

GLib = gi_import("GLib")

printlog = Logger("printing")
filelog = Logger("file")

DELETE_PRINTER_FILE = envbool("XPRA_DELETE_PRINTER_FILE", True)
SKIP_STOPPED_PRINTERS = envbool("XPRA_SKIP_STOPPED_PRINTERS", True)
INIT_PRINTING_DELAY = envint("XPRA_INIT_PRINTING_DELAY", 2)


class FileMixin(StubClientMixin, FileTransferHandler):

    def __init__(self):
        StubClientMixin.__init__(self)
        FileTransferHandler.__init__(self)
        self.remote_request_file: bool = False

    def init(self, opts) -> None:
        # printing and file transfer:
        FileTransferHandler.init_opts(self, opts)

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(
            "open-url", "send-file",
            "send-data-request", "send-data-response",
            "ack-file-chunk", "send-file-chunk",
        )

    def get_caps(self) -> dict[str, Any]:
        return {"file": self.get_file_transfer_features()}

    def cleanup(self) -> None:
        # we must clean printing before FileTransferHandler, which turns the printing flag off!
        FileTransferHandler.cleanup(self)

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.parse_file_transfer_caps(c)
        self.remote_request_file = c.boolget("request-file", False)
        return True
