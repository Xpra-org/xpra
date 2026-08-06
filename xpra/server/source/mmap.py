# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Sequence

from xpra.os_util import WIN32
from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.server.source.stub import StubClientConnection
from xpra.net.mmap.common import get_default_mmap_dirs
from xpra.net.mmap.io import init_server_mmap, init_server_mmap_section, safe_open_mmap_file
from xpra.net.mmap.objects import BaseMmapArea

from xpra.log import Logger

log = Logger("mmap")


def clean_mmap_area(area: BaseMmapArea) -> None:
    if not area:
        return
    try:
        area.close()
    except BufferError:
        # this can fail when handling a SIGINT signal,
        # with the message: "cannot close exported pointers exist",
        # so wait a little bit and try again:
        from xpra.os_util import gi_import
        GLib = gi_import("GLib")

        def retry_close() -> None:
            try:
                area.close()
            except RuntimeError as e:
                log.warn(f"Warning: failed to close mmap area {area!r}: {e}")
        GLib.timeout_add(100, retry_close)


class MMAP_Connection(StubClientConnection):

    PREFIX = "mmap"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        mmap_caps = typedict(caps.get("mmap") or {})
        if not BACKWARDS_COMPATIBLE:
            return bool(mmap_caps)
        for prefix in ("", "read", "write"):
            if prefix:
                area_caps = typedict(mmap_caps.dictget(prefix))
            else:
                # older versions supply a single unprefixed area:
                area_caps = mmap_caps
            log(f"is_needed(..) caps({prefix!r})={area_caps!r}")
            if area_caps.intget("size", 0) > 0:
                return True
        return False

    def __init__(self):
        super().__init__()
        self.mmap_supported = False
        self.mmap_read_area = None
        self.mmap_write_area = None
        self.mmap_min_size = 0
        # the directories and files specified with the `mmap` option:
        self.mmap_dirs: Sequence[str] = ()
        self.mmap_files: Sequence[str] = ()
        # the directories the client's mmap file may live in:
        self.allowed_dirs: Sequence[str] = ()
        self.peer_uid = -1

    def init_from(self, protocol, server) -> None:
        # `MMAP_Server` is the standalone subsystem instance:
        mmap_sub = server.subsystems["mmap"]
        self.mmap_supported = mmap_sub.supported
        self.mmap_dirs = mmap_sub.dirs
        self.mmap_files = mmap_sub.files
        self.mmap_min_size = mmap_sub.min_size
        conn = getattr(protocol, "_conn", None)
        get_peer_uid = getattr(conn, "get_peer_uid", None)
        self.peer_uid = get_peer_uid() if get_peer_uid else -1
        # the paths given on the command line are trusted,
        # otherwise we can only accept the standard locations:
        self.allowed_dirs = self.mmap_dirs or get_default_mmap_dirs(self.peer_uid)
        log("mmap: peer uid=%i, allowed directories=%s", self.peer_uid, self.allowed_dirs)

    def init_state(self) -> None:
        self.mmap_read_area = None
        self.mmap_write_area = None

    def cleanup(self) -> None:
        clean_mmap_area(self.mmap_read_area)
        self.mmap_read_area = None
        clean_mmap_area(self.mmap_write_area)
        self.mmap_write_area = None

    def mmap_path(self, filename: str, index: int) -> str:
        """
            The path we should use for the area the client has described,
            or an empty string if the client's filename is not acceptable.
            Only the basename of the client's filename is ever used:
            the directory always comes from the server's configuration,
            so a client can never point us at an arbitrary location.
        """
        if len(self.mmap_files) > index:
            # server command line option overrides the path completely:
            path = self.mmap_files[index]
            log(f"using global server specified mmap file path: {path!r}")
            return path
        if not filename:
            return ""
        if WIN32:
            # not a filesystem path, but the name of a shared memory section:
            return filename
        basename = os.path.basename(filename)
        if not basename or basename in (os.curdir, os.pardir):
            log.warn(f"Warning: invalid mmap filename {filename!r}")
            return ""
        dirname = os.path.dirname(filename)
        if not dirname:
            # the client did not specify a directory,
            # so look for its file in the directories we allow:
            for mmap_dir in self.allowed_dirs:
                path = os.path.join(mmap_dir, basename)
                if os.path.exists(path):
                    log(f"found mmap file {basename!r} in {mmap_dir!r}")
                    return path
            log.warn(f"Warning: mmap file {basename!r} not found")
            log.warn(" in any of the allowed directories: %s", csv(self.allowed_dirs) or "none")
            return ""
        dirname = os.path.normpath(dirname)
        for mmap_dir in self.allowed_dirs:
            # use the directory the client's file is supposed to live in,
            # so that a client can choose between the directories we allow:
            if os.path.normpath(mmap_dir) == dirname:
                return os.path.join(mmap_dir, basename)
        if self.mmap_dirs:
            # the directories were specified by the server administrator:
            # the client's file is expected to be found in the first one,
            # no matter where the client believes it is
            mmap_dir = self.mmap_dirs[0]
            log(f"using global server specified mmap directory: {mmap_dir!r}")
            return os.path.join(mmap_dir, basename)
        log.warn("Warning: the mmap file specified by the client is not in an allowed directory")
        log.warn(f" {filename!r}")
        log.warn(" allowed: %s", csv(self.allowed_dirs) or "none")
        return ""

    def open_mmap_file(self, path: str, index: int) -> int:
        """
            Opens the mmap file, returns a file descriptor or -1.
            The file is only verified when the client chose its location:
            a path specified by the server administrator is used as-is,
            it can legitimately be a symbolic link, a device file
            or a file belonging to another user.
        """
        if len(self.mmap_files) > index:
            try:
                return os.open(path, os.O_RDWR | os.O_CLOEXEC)
            except OSError as e:
                log(f"os.open({path!r})", exc_info=True)
                log.error(f"Error: cannot access the mmap file {path!r}:")
                log.estr(e)
                return -1
        uids = [os.getuid()]
        if self.peer_uid >= 0 and self.peer_uid not in uids:
            uids.append(self.peer_uid)
        # the directory is one of ours, the basename is all that comes from the client:
        return safe_open_mmap_file(os.path.dirname(path), os.path.basename(path), uids)

    def parse_area_caps(self, name: str, raw_caps: dict, index: int) -> BaseMmapArea | None:
        log("parse_area_caps(%r, %r, %i)", name, raw_caps, index)
        if not raw_caps:
            return None
        caps = typedict(raw_caps)
        filename = self.mmap_path(caps.strget("file"), index)
        if not filename:
            return None
        size = caps.intget("size", 0)
        log("client supplied mmap_file=%r, size=%i", filename, size)
        if not size:
            return None
        area = BaseMmapArea(name, filename, size)
        area.parse_caps(caps)
        if not area.enabled:
            return None
        if WIN32:
            mmap, size = init_server_mmap_section(filename, size)
        else:
            fd = self.open_mmap_file(filename, index)
            if fd < 0:
                return None
            try:
                mmap, size = init_server_mmap(fd, size)
            finally:
                # the mapping remains valid once the file descriptor is closed:
                os.close(fd)
        log("found client mmap area: %s, %i bytes - min mmap size=%i in %r",
            mmap, size, self.mmap_min_size, filename)
        if size <= 0 or not mmap:
            return None
        if size < self.mmap_min_size:
            mmap.close()
            log.warn("Warning: client %s supplied mmap area is too small, discarding it", name)
            log.warn(" at least %iMB are needed and this area is only %iMB",
                     self.mmap_min_size // 1024 // 1024, size // 1024 // 1024)
            return None
        area.set_mmap(mmap)
        if not area.verify_token():
            mmap.close()
            return None
        return area

    def parse_client_caps(self, caps: typedict) -> None:
        if not self.mmap_supported:
            log("mmap.parse_client_caps() mmap is disabled")
            return
        mmap_caps = caps.get("mmap") or {}
        if not mmap_caps or not isinstance(mmap_caps, dict):
            log(f"mmap.parse_client_caps() client did not supply valid mmap caps: {mmap_caps!r}")
            self.mmap_supported = False
            return
        tdcaps = typedict(mmap_caps)
        read_caps = tdcaps.dictget("write")
        write_caps = tdcaps.dictget("read")
        if BACKWARDS_COMPATIBLE and not write_caps:
            # also try the legacy unprefixed lookup for the client's 'read' area:
            write_caps = mmap_caps
        self.mmap_read_area = self.parse_area_caps("read", read_caps, 1)
        self.mmap_write_area = self.parse_area_caps("write", write_caps, 0)
        log("parse_client_caps() mmap-read=%s, mmap-write=%s", self.mmap_read_area, self.mmap_write_area)

    def get_caps(self) -> dict[str, Any]:
        mmap_caps: dict[str, Any] = {}
        READ_PREFIXES = ("read", )
        WRITE_PREFIXES = ("write", )
        if BACKWARDS_COMPATIBLE:
            WRITE_PREFIXES = ("write", "")
        for prefixes, area in (
            (READ_PREFIXES, self.mmap_read_area),
            (WRITE_PREFIXES, self.mmap_write_area),
        ):
            if not area:
                continue
            # write a new token that the client can verify:
            area.gen_token()
            area.write_token()
            caps = area.get_caps()
            for prefix in prefixes:
                if prefix:
                    mmap_caps[prefix] = caps
                else:
                    mmap_caps.update(caps)
        log(f"mmap caps={mmap_caps}")
        return {MMAP_Connection.PREFIX: mmap_caps}

    def get_info(self) -> dict[str, Any]:
        info = {}
        for name, area in {
            "read": self.mmap_read_area,
            "write": self.mmap_write_area,
        }.items():
            if area:
                info[name] = area.get_info()
        return {MMAP_Connection.PREFIX: info}
