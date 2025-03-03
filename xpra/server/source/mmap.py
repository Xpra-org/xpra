# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Sequence

from xpra.util.objects import typedict
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.net.mmap import init_server_mmap, BaseMmapArea

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

        def retry_close():
            try:
                area.close()
            except RuntimeError as e:
                log.warn(f"Warning: failed to close mmap area {area!r}: {e}")
        GLib.timeout_add(100, retry_close)


class MMAP_Connection(StubSourceMixin):

    PREFIX = "mmap"

    @classmethod
    def is_needed(cls, caps: typedict) -> bool:
        mmap_caps = typedict(caps.get("mmap") or {})
        for prefix in ("", "read", "write"):
            if prefix:
                area_caps = typedict(mmap_caps.dictget(prefix) or {})
            else:
                # older versions supply a single unprefixed area:
                area_caps = mmap_caps
            log(f"is_needed(..) caps({prefix!r})={area_caps!r}")
            if area_caps.intget("size", 0) > 0:
                return True
        return False

    def __init__(self):
        self.mmap_supported = False
        self.mmap_read_area = None
        self.mmap_write_area = None
        self.mmap_min_size = 0
        self.mmap_filenames: Sequence[str] = ()

    def init_from(self, _protocol, server) -> None:
        self.mmap_supported = server.mmap_supported
        if server.mmap_filename:
            self.mmap_filenames = server.mmap_filename.split(os.path.pathsep)
        self.mmap_min_size = server.mmap_min_size

    def init_state(self) -> None:
        self.mmap_read_area = None
        self.mmap_write_area = None

    def cleanup(self) -> None:
        clean_mmap_area(self.mmap_read_area)
        self.mmap_read_area = None
        clean_mmap_area(self.mmap_write_area)
        self.mmap_write_area = None

    def mmap_path(self, filename: str, index: int) -> str:
        if len(self.mmap_filenames) == 1 and os.path.isdir(self.mmap_filenames[0]):
            # server directory specified: use the client's filename, but at the server path
            mmap_dir = self.mmap_filenames[0]
            log(f"using global server specified mmap directory: {mmap_dir!r}")
            return os.path.join(mmap_dir, os.path.basename(filename))
        if self.mmap_filenames and len(self.mmap_filenames) > index:
            # server command line option overrides the path:
            filename = self.mmap_filenames[index]
            log(f"using global server specified mmap file path: {filename!r}")
        return filename

    def parse_area_caps(self, name: str, raw_caps: dict, index: int) -> BaseMmapArea | None:
        log("parse_area_caps(%r, %r, %i)", name, raw_caps, index)
        if not raw_caps:
            return None
        caps = typedict(raw_caps)
        filename = self.mmap_path(caps.strget("file"), index)
        if not filename or not os.path.exists(filename):
            log(f"mmap_file {filename!r} cannot be found!")
            return None
        size = caps.intget("size", 0)
        log("client supplied mmap_file=%r, size=%i", filename, size)
        if not size:
            return None
        area = BaseMmapArea(name, filename, size)
        area.parse_caps(caps)
        if not area.enabled:
            return None
        mmap, size = init_server_mmap(filename, size)
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
        area.mmap = mmap
        area.size = size
        if not area.verify_token():
            mmap.close()
            return None
        from xpra.util.stats import std_unit
        log.info(" mmap is enabled using %sB area in %s", std_unit(size, unit=1024), filename)
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
        self.mmap_read_area = self.parse_area_caps("read", tdcaps.dictget("write") or mmap_caps, 1)
        # also try legacy unprefixed lookup for 'read' area:
        self.mmap_write_area = self.parse_area_caps("write", tdcaps.dictget("read"), 0)
        log("parse_client_caps() mmap-read=%s, mmap-write=%s", self.mmap_read_area, self.mmap_write_area)

    def get_caps(self) -> dict[str, Any]:
        mmap_caps: dict[str, Any] = {}
        for prefixes, area in (
            (("read", ""), self.mmap_read_area),
            (("write", ), self.mmap_write_area),
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
