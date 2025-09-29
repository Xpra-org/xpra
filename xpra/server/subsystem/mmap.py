# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Any

from xpra.util.parsing import str_to_bool
from xpra.server.subsystem.stub import StubServerMixin


class MMAP_Server(StubServerMixin):
    """
    Mixin for servers that can handle mmap transfers
    """
    PREFIX = "mmap"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.mmap_supported = False
        self.mmap_filename = ""
        self.mmap_min_size = 64 * 1024 * 1024

    def init(self, opts) -> None:
        if opts.mmap and os.path.isabs(opts.mmap):
            self.mmap_supported = True
            self.mmap_filename = opts.mmap
        else:
            self.mmap_supported = str_to_bool(opts.mmap)

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            MMAP_Server.PREFIX: {
                "supported": self.mmap_supported,
                "filename": self.mmap_filename or "",
            },
        }
