# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.objects import typedict
from xpra.net.file_transfer import FileTransferHandler
from xpra.server.source.stub import StubClientConnection


class FileConnection(FileTransferHandler, StubClientConnection):

    def __init__(self):
        FileTransferHandler.__init__(self)
        StubClientConnection.__init__(self)

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        return bool("file" in caps or caps.boolget("file-transfer"))

    def parse_client_caps(self, c: typedict) -> None:
        FileTransferHandler.parse_file_transfer_caps(self, c)

    def get_info(self) -> dict[str, Any]:
        return {
            "file-transfers": FileTransferHandler.get_info(self),
        }

    def init_from(self, _protocol, server) -> None:
        self.init_attributes()
        # copy attributes
        for x in (
                "file_transfer", "file_transfer_ask", "file_size_limit", "file_chunks",
                "open_files", "open_files_ask",
                "open_url", "open_url_ask",
                "file_ask_timeout", "open_command",
        ):
            setattr(self, x, getattr(server.file_transfer, x))
