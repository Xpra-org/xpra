# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Final

from xpra.log import Logger

log = Logger("client", "terminal")

# POSIX shared memory objects live here on Linux (`shm_open` is
# `open` under this directory): the terminal opens our objects by name,
# so this only works when the terminal runs on this machine - which is
# what the `t=s` probe verifies before any of this is used:
SHM_DIR: Final[str] = "/dev/shm"


class ShmWriter:
    """
    Allocates the POSIX shared memory objects used for kitty `t=s` pixel
    transmissions.  The terminal unlinks every object it reads, so a
    successful transfer needs no cleanup here: `prune` only reaps objects
    the terminal never consumed (a dead terminal, a rejected command), and
    `cleanup` unlinks whatever is left on the way out.
    """

    def __init__(self):
        self.counter = 0
        self.prefix = f"/xpra-terminal-{os.getpid()}"
        # names the terminal may not have consumed yet:
        self.pending: list[str] = []

    def __repr__(self):
        return f"ShmWriter({self.prefix!r}, {self.counter} objects)"

    @staticmethod
    def available() -> bool:
        return os.path.isdir(SHM_DIR) and os.access(SHM_DIR, os.W_OK)

    @staticmethod
    def path(name: str) -> str:
        return SHM_DIR + name

    def write(self, data) -> str:
        """
        Store `data` in a new shared memory object,
        returns its name, or an empty string on failure.
        """
        self.prune()
        self.counter += 1
        name = f"{self.prefix}-{self.counter}"
        path = self.path(name)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
            finally:
                os.close(fd)
        except OSError as e:
            log("write() failed for %r", path, exc_info=True)
            log.warn(f"Warning: cannot write {len(data)} bytes of shared memory: {e}")
            try:
                os.unlink(path)
            except OSError:
                pass
            return ""
        self.pending.append(name)
        return name

    def prune(self) -> None:
        """ forget the objects the terminal has consumed (it unlinks them) """
        self.pending = [name for name in self.pending if os.path.exists(self.path(name))]

    def cleanup(self) -> None:
        for name in self.pending:
            try:
                os.unlink(self.path(name))
            except OSError:
                pass
        self.pending = []
