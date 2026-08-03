# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from typing import Any
from collections.abc import Sequence

from xpra.net.mmap.common import split_paths
from xpra.util.parsing import str_to_bool
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("mmap")


class MMAP_Server(StubSubsystem):
    """
    Mixin for servers that can handle mmap transfers
    """
    __slots__ = ("dirs", "files", "min_size", "supported")
    PREFIX = "mmap"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.supported = False
        # the paths specified with the `mmap` option, split by type:
        self.dirs: Sequence[str] = ()
        self.files: Sequence[str] = ()
        self.min_size = 64 * 1024 * 1024

    def init(self, opts) -> None:
        paths = split_paths(opts.mmap or "")
        if any(os.path.isabs(path) for path in paths):
            self.supported = True
            self.parse_paths(paths)
        else:
            self.supported = str_to_bool(opts.mmap)

    def parse_paths(self, paths: Sequence[str]) -> None:
        """
            Directories are the locations where the clients' mmap files can be found,
            any other path is used as-is for one mmap area, in the order specified.
        """
        dirs = []
        files = []
        for path in paths:
            if not os.path.isabs(path):
                log.warn(f"Warning: ignoring mmap path {path!r}")
                log.warn(" only absolute paths can be used")
                continue
            if os.path.isdir(path):
                dirs.append(path)
            else:
                files.append(path)
        self.dirs = tuple(dirs)
        self.files = tuple(files)
        log(f"mmap directories={self.dirs}, files={self.files}")

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            MMAP_Server.PREFIX: {
                "supported": self.supported,
                "dirs": self.dirs,
                "files": self.files,
            },
        }
