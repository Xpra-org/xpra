# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Any

from xpra.util.parsing import str_to_bool
from xpra.server.subsystem.stub import StubSubsystem


class MMAP_Server(StubSubsystem):
    """
    Mixin for servers that can handle mmap transfers
    """
    __slots__ = ("filename", "min_size", "supported")
    PREFIX = "mmap"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.supported = False
        self.filename = ""
        self.min_size = 64 * 1024 * 1024

    def init(self, opts) -> None:
        if opts.mmap and os.path.isabs(opts.mmap):
            self.supported = True
            self.filename = opts.mmap
        else:
            self.supported = str_to_bool(opts.mmap)

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            MMAP_Server.PREFIX: {
                "supported": self.supported,
                "filename": self.filename or "",
            },
        }
