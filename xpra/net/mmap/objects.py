# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from random import randint
from typing import Any

from xpra.net.mmap.common import DEFAULT_TOKEN_BYTES
from xpra.net.mmap.io import read_mmap_token, write_mmap_token, mmap_read, mmap_write, mmap_free_size
from xpra.client.gui.window.backing import PaintCallback
from xpra.os_util import get_int_uuid
from xpra.util.objects import typedict
from xpra.util.stats import std_unit
from xpra.log import Logger

log = Logger("mmap")


class BaseMmapArea:
    """
    Represents an mmap area we can read from or write to
    """

    def __init__(self, name: str, filename="", size=0):
        self.name = name
        self.mmap = None
        self.enabled = False
        self.token: int = 0
        self.token_index: int = 0
        self.token_bytes: int = 0
        self.filename = filename
        self.size = size

    def __repr__(self):
        return "MmapArea(%s:%s:%i)" % (self.name, self.filename, self.size)

    def __bool__(self):
        return bool(self.mmap) and self.enabled and self.size > 0

    def close(self) -> None:
        if mmap := self.mmap:
            try:
                mmap.close()
            except BufferError:
                log("%s.close()", mmap, exc_info=True)
            except OSError:
                log("%s.close()", mmap, exc_info=True)
                log.warn("Warning: failed to close %s mmap area", self.name)
            self.mmap = None
        self.enabled = False

    def set_mmap(self, mmap_area) -> None:
        """
            The length we have actually mapped is the only size we can trust:
            the peer chooses the size it advertises in its capabilities,
            and the area may well have been mapped with a different length.
        """
        self.mmap = mmap_area
        self.size = len(mmap_area)

    def get_caps(self) -> dict[str, Any]:
        return {
            "file": self.filename,
            "size": self.size,
            "token": self.token,
            "token_index": self.token_index,
            "token_bytes": self.token_bytes,
        }

    def get_info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": self.filename,
            "size": self.size,
        }

    def parse_caps(self, mmap_caps: typedict) -> None:
        self.enabled = mmap_caps.boolget("enabled", True)
        self.token = mmap_caps.intget("token")
        self.token_index = mmap_caps.intget("token_index", 0)
        self.token_bytes = mmap_caps.intget("token_bytes", DEFAULT_TOKEN_BYTES)
        if self.mmap:
            # the area is already mapped, so its real length wins
            # over whatever size the peer may claim:
            self.size = len(self.mmap)
        else:
            # we need a size to be able to map the area at all:
            self.size = self.size or mmap_caps.intget("size")

    def verify_token(self) -> bool:
        if not self.mmap:
            raise RuntimeError("mmap object is not defined")
        try:
            token = read_mmap_token(self.mmap, self.token_index, self.token_bytes)
        except ValueError as e:
            # the peer has chosen a token location or size we cannot use:
            self.enabled = False
            log.error(f"Error: invalid {self.name!r} mmap token attributes")
            log.error(f" {e}")
            log.error(" mmap is disabled")
            return False
        if token == 0:
            log.info(f"the server is not using the {self.name!r} mmap area")
            return False
        if token != self.token:
            self.enabled = False
            log.error(f"Error: {self.name!r} mmap token verification failed!")
            log.error(f" expected {self.token:x}")
            log.error(f" found {token:x}")
            log.error(" mmap is disabled")
            return False
        log.info("enabled fast %s mmap transfers using %sB shared memory area",
                 self.name, std_unit(self.size, unit=1024))
        log.info(" %r", self.filename)
        return True

    def gen_token(self) -> None:
        self.token = get_int_uuid()
        self.token_bytes = DEFAULT_TOKEN_BYTES
        self.token_index = randint(0, self.size - DEFAULT_TOKEN_BYTES)

    def write_token(self) -> None:
        write_mmap_token(self.mmap, self.token, self.token_index, self.token_bytes)

    def write_data(self, data) -> list[tuple[int, int]]:
        return mmap_write(self.mmap, self.size, data)

    def mmap_read(self, *descr_data: tuple[int, int]) -> tuple[bytes | memoryview, PaintCallback]:
        return mmap_read(self.mmap, *descr_data)

    def get_free_size(self) -> int:
        return mmap_free_size(self.mmap, self.size)
