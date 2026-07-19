# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.util.objects import typedict
from xpra.util.env import envint, envbool
from xpra.net.file_transfer import FileTransferHandler
from xpra.client.base.stub import StubClientSubsystem
from xpra.log import Logger

printlog = Logger("printing")
filelog = Logger("file")

DELETE_PRINTER_FILE = envbool("XPRA_DELETE_PRINTER_FILE", True)
SKIP_STOPPED_PRINTERS = envbool("XPRA_SKIP_STOPPED_PRINTERS", True)
INIT_PRINTING_DELAY = envint("XPRA_INIT_PRINTING_DELAY", 2)


class File(StubClientSubsystem, FileTransferHandler):
    __slots__ = (
        "_file_io_queue", "_file_io_thread", "data_send_requests", "file_ask_timeout", "file_chunks",
        "file_descriptors", "file_request_callback", "file_size_limit", "file_transfer", "file_transfer_ask",
        "files_accepted", "files_requested", "open_command", "open_files", "open_files_ask", "open_url",
        "open_url_ask", "pending_send_data", "pending_send_data_timers", "printing", "printing_ask",
        "receive_chunks_in_progress", "remote_file_ask_timeout", "remote_file_chunks", "remote_file_size_limit",
        "remote_file_transfer", "remote_file_transfer_ask", "remote_open_files", "remote_open_files_ask",
        "remote_open_url", "remote_open_url_ask", "remote_printing", "remote_printing_ask", "remote_request_file",
        "send_chunks_in_progress",
    )
    PREFIX = "file"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        FileTransferHandler.__init__(self)
        self.remote_request_file: bool = False

    def init(self, opts) -> None:
        # printing and file transfer:
        FileTransferHandler.init_opts(self, opts)

    def init_authenticated_packet_handlers(self) -> None:
        self.add_legacy_alias("send-file", "file-send")
        self.add_legacy_alias("send-data-request", "file-data-request")
        self.add_legacy_alias("send-data-response", "file-data-response")
        self.add_legacy_alias("send-file-chunk", "file-send-chunk")
        self.add_legacy_alias("ack-file-chunk", "file-ack-chunk")
        self.add_packets(
            "file-send",
            "file-data-response",
            "file-ack-chunk", "file-send-chunk",
        )
        # `open-url` spawns a subprocess / web browser (ie: `execve`) and may prompt
        # the user via a dialog, so it must run on the main thread rather than inline
        # on the network parse thread - which the seccomp filter forbids from
        # spawning processes (see `docs/Usage/Seccomp.md`):
        self.add_packets("file-data-request", "open-url", main_thread=True)

    def get_caps(self) -> dict[str, Any]:
        return {"file": self.get_file_transfer_features()}

    def get_info(self) -> dict[str, Any]:
        return {"file-transfers": FileTransferHandler.get_info(self)}

    def cleanup(self) -> None:
        FileTransferHandler.cleanup(self)

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.parse_file_transfer_caps(c)
        fc = typedict(c.dictget("file"))
        self.remote_request_file = fc.boolget("request-file", c.boolget("request-file", False))
        return True

    # `FileTransferHandler`'s internals call these three back on `self` as hooks
    # (eg: to prompt the user, or report progress); toolkit clients (eg: gtk3)
    # provide them via the optional `dialogs` subsystem.
    def ask_data_request(self, cb_answer: Callable[[bool], None], *args, **kwargs) -> None:
        dialogs = self.get_subsystem("dialogs")
        fn = getattr(dialogs, "ask_data_request", None)
        if fn:
            fn(cb_answer, *args, **kwargs)
        else:
            FileTransferHandler.ask_data_request(self, cb_answer, *args, **kwargs)

    def file_size_warning(self, *args) -> None:
        dialogs = self.get_subsystem("dialogs")
        fn = getattr(dialogs, "file_size_warning", None)
        if fn:
            fn(*args)
        else:
            FileTransferHandler.file_size_warning(self, *args)

    def transfer_progress_update(self, *args, **kwargs) -> None:
        dialogs = self.get_subsystem("dialogs")
        fn = getattr(dialogs, "transfer_progress_update", None)
        if fn:
            fn(*args, **kwargs)
        else:
            FileTransferHandler.transfer_progress_update(self, *args, **kwargs)
