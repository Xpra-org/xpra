# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.common import BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.exit_codes import ExitCode
from xpra.util.str_fn import csv
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.client.base.stub import StubClientMixin
from xpra.net.mmap.io import init_client_mmap, clean_mmap
from xpra.net.mmap.objects import BaseMmapArea
from xpra.log import Logger

log = Logger("mmap")

KEEP_MMAP_FILE = envbool("XPRA_KEEP_MMAP_FILE", False)


class MmapArea(BaseMmapArea):

    def __init__(self, name: str, group="", filename="", size=0):
        super().__init__(name, filename, size)
        self.group = group
        self.tempfile = None
        self.delete: bool = False

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["group"] = self.group
        return info

    def cleanup(self) -> None:
        super().close()
        self.clean_mmap()

    def clean_mmap(self) -> None:
        log("%s.clean_mmap() filename=%s", self, self.filename)
        if self.tempfile:
            try:
                self.tempfile.close()
            except OSError as e:
                log("%s.clean_mmap() error closing file %s: %s", self, self.tempfile, e)
            self.tempfile = None
        if self.delete:
            # this should be redundant: closing the tempfile should get it deleted
            if self.filename and os.path.exists(self.filename):
                clean_mmap(self.filename)
                self.filename = ""

    def enable_from_caps(self, mmap_caps: typedict) -> bool:
        try:
            self.parse_caps(mmap_caps)
            if self.enabled:
                self.verify_token()
            if not self.enabled:
                self.clean_mmap()
            return self.enabled
        finally:
            # the server will have a handle on the mmap file by now, safe to delete:
            if not KEEP_MMAP_FILE:
                self.clean_mmap()

    def init_mmap(self, socket_filename: str) -> None:
        log("%s.init_mmap(%r)", self, socket_filename)
        self.enabled, self.delete, self.mmap, self.size, self.tempfile, self.filename = \
            init_client_mmap(self.group, socket_filename, self.size, self.filename)
        if self.enabled:
            self.gen_token()
            self.write_token()


class MmapClient(StubClientMixin):
    """
    Mixin for adding mmap support to a client
    """
    PREFIX = "mmap"

    def __init__(self):
        self.mmap_read_area: MmapArea | None = None
        self.mmap_write_area: MmapArea | None = None
        self.mmap_supported = True

    def init(self, opts) -> None:
        mopt = opts.mmap.lower()
        log("mmap.init(..) mmap=%r", mopt)
        if mopt in FALSE_OPTIONS:
            self.mmap_supported = False
            return
        self.mmap_supported = True
        read = write = False
        if mopt in ("auto", "read"):
            # by default, only enable mmap reads, not writes:
            read = True
            filenames = ("", )
        elif mopt == "write":
            write = True
            filenames = ("", "")
        elif mopt in TRUE_OPTIONS or mopt == "both":
            read = write = True
            filenames = ("", "")
        else:
            # assume file path(s) have been specified:
            filenames = opts.mmap.split(os.path.pathsep)
            if len(filenames) >= 3:
                raise RuntimeError("too many mmap filenames specified: %r" % csv(filenames))
            read = True
            write = len(filenames) == 2
        group = opts.mmap_group
        root_w, root_h = self.get_root_size()
        # at least 256MB, or 8 fullscreen RGBX frames:
        size = max(512 * 1024 * 1024, root_w * root_h * 4 * 8)
        # but no more than 2GB:
        size = min(2048 * 1024 * 1024, size)
        if read:
            self.mmap_read_area = MmapArea("read", group, filenames[0], size)
        if write:
            self.mmap_write_area = MmapArea("write", group, filenames[1], size)
        log("init(..) group=%s, mmap=%s, read-area=%s, write-area=%s",
            group, opts.mmap, self.mmap_read_area, self.mmap_write_area)

    def cleanup(self) -> None:
        self.clean_areas()

    def clean_areas(self) -> None:
        def clean(area: MmapArea | None) -> None:
            try:
                if not area:
                    return
            except ValueError as e:
                log("clean(%r) %s ignored", area, e)
                return
            area.cleanup()

        mra = self.mmap_read_area
        self.mmap_read_area = None
        clean(mra)
        mwa = self.mmap_write_area
        self.mmap_write_area = None
        clean(mwa)

    def setup_connection(self, conn) -> None:
        log("setup_connection(%s) mmap supported=%s", conn, self.mmap_supported)
        if not self.mmap_supported:
            return
        for name, area in {
            "read": self.mmap_read_area,
            "write": self.mmap_write_area,
        }.items():
            log(f"{name!r}={area}")
            if area is not None:
                area.init_mmap(conn.filename or "")

    @staticmethod
    def get_root_size() -> tuple[int, int]:
        # subclasses should provide real values
        return 1024, 1024

    # noinspection PyUnreachableCode
    def parse_server_capabilities(self, c: typedict) -> bool:
        mmap_caps = typedict(c.dictget("mmap") or {})
        log(f"mmap.parse_server_capabilities(..) {mmap_caps=}")
        if not self.mmap_supported or not mmap_caps:
            self.clean_areas()
            return True
        READ_PREFIXES = ("read", )
        # older versions didn't use a prefix:
        WRITE_PREFIXES = ("write", "") if BACKWARDS_COMPATIBLE else ("write", )
        # parse each area
        for prefixes, area in (
            (WRITE_PREFIXES, self.mmap_read_area),
            (READ_PREFIXES, self.mmap_write_area),
        ):
            log(f"{prefixes} : {area}")
            if not area:
                continue
            area_caps = {}
            prefix = ""
            for prefix in prefixes:
                if prefix:
                    area_caps = mmap_caps.dictget(prefix)
                else:
                    # older versions only have one mmap area:
                    area_caps = mmap_caps
                if area_caps:
                    break
            log(f"caps({prefix!r})={area_caps!r}")
            if area_caps:
                try:
                    if area.enable_from_caps(typedict(area_caps)):
                        # enabled!
                        continue
                except ValueError:
                    log("mmap.parse_server_capabilities(..)", exc_info=True)
                    self.quit(ExitCode.MMAP_TOKEN_FAILURE)
                    return False
            # not found, or not enabled:
            area.cleanup()
        return True

    def get_info(self) -> dict[str, Any]:
        info = {}
        for prefix, area in {
            "read": self.mmap_read_area,
            "write": self.mmap_write_area,
        }.items():
            if area:
                info[prefix] = area.get_info()
        return {MmapClient.PREFIX: info}

    def get_caps(self) -> dict[str, Any]:
        if not self.mmap_supported:
            return {}
        caps = {}
        for prefix, area in {
            "read": self.mmap_read_area,
            "write": self.mmap_write_area,
        }.items():
            if area:
                caps[prefix] = area.get_caps()
        if BACKWARDS_COMPATIBLE and self.mmap_read_area:
            # duplicate it for legacy unprefixed caps:
            caps.update(self.mmap_read_area.get_caps())
        return {MmapClient.PREFIX: caps}
