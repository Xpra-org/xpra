# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from random import randint
from typing import Any

from xpra.util.objects import typedict
from xpra.util.env import envbool
from xpra.os_util import get_int_uuid
from xpra.exit_codes import ExitCode
from xpra.scripts.config import FALSE_OPTIONS, TRUE_OPTIONS
from xpra.util.stats import std_unit
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.net.mmap import init_client_mmap, write_mmap_token, clean_mmap, read_mmap_token, DEFAULT_TOKEN_BYTES
from xpra.log import Logger

log = Logger("mmap")

KEEP_MMAP_FILE = envbool("XPRA_KEEP_MMAP_FILE", False)


class MmapArea:
    """
    Represents an mmap area we can read from or write to
    """

    def __init__(self, name: str, group="", filename="", size=0):
        self.name = name
        self.mmap = None
        self.enabled = False
        self.token: int = 0
        self.token_index: int = 0
        self.token_bytes: int = 0
        self.filename = filename
        self.size = size
        self.group = group
        self.tempfile = None
        self.delete: bool = False

    def __repr__(self):
        return "MmapArea(%s)" % self.name

    def get_caps(self) -> dict[str, Any]:
        return {
            "file": self.filename,
            "size": self.size,
            "token": self.token,
            "token_index": self.token_index,
            "token_bytes": self.token_bytes,
            "group": self.group or "",
        }

    def get_info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": self.filename,
            "size": self.size,
            "group": self.group or "",
        }

    def cleanup(self) -> None:
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
        self.enabled = mmap_caps.boolget("enabled", False)
        log("%s.enabled=%s", self, self.enabled)
        if self.enabled:
            assert self.mmap
            mmap_token = mmap_caps.intget("token")
            mmap_token_index = mmap_caps.intget("token_index", 0)
            mmap_token_bytes = mmap_caps.intget("token_bytes", DEFAULT_TOKEN_BYTES)
            token = read_mmap_token(self.mmap, mmap_token_index, mmap_token_bytes)
            if token != mmap_token:
                log.error("Error: mmap token verification failed!")
                log.error(f" expected {token:x}")
                log.error(f" found {mmap_token:x}")
                self.enabled = False
                if token:
                    raise ValueError("mmap token failure")
                log.error(" mmap is disabled")
                return False
            log.info("enabled fast %s mmap transfers using %sB shared memory area",
                     self.name, std_unit(self.size, unit=1024))
            return True
        # the server will have a handle on the mmap file by now, safe to delete:
        if not KEEP_MMAP_FILE:
            self.clean_mmap()
        return False

    def init_mmap(self, socket_filename: str) -> None:
        log("%s.init_mmap(%r)", self, socket_filename)
        self.enabled, self.delete, self.mmap, self.size, self.tempfile, self.filename = \
            init_client_mmap(self.group, socket_filename, self.size, self.filename)
        if self.enabled:
            self.token = get_int_uuid()
            self.token_bytes = DEFAULT_TOKEN_BYTES
            self.token_index = randint(0, self.size - DEFAULT_TOKEN_BYTES)
            write_mmap_token(self.mmap, self.token, self.token_index, self.token_bytes)


class MmapClient(StubClientMixin):
    """
    Mixin for adding mmap support to a client
    """

    def __init__(self):
        super().__init__()
        self.mmap_read_area = None
        self.mmap_write_area = None
        self.mmap_supported = True

    def init(self, opts) -> None:
        log("mmap.init(..) mmap=%r", opts.mmap)
        if opts.mmap.lower() in FALSE_OPTIONS:
            self.mmap_supported = False
            return
        self.mmap_supported = True
        if opts.mmap.lower() not in TRUE_OPTIONS:
            filenames = opts.mmap.split(os.path.pathsep)
        else:
            filenames = ("", "")
        group = opts.mmap_group
        root_w, root_h = self.get_root_size()
        # at least 256MB, or 8 fullscreen RGBX frames:
        size = max(512 * 1024 * 1024, root_w * root_h * 4 * 8)
        # but no more than 2GB:
        size = min(2048 * 1024 * 1024, size)
        self.mmap_read_area = MmapArea("read", group, filenames[0], size)
        if len(filenames) > 1:
            self.mmap_write_area = MmapArea("write", group, filenames[1], size)
        log("init(..) group=%s, mmap=%s, read-area=%s, write-area=%s",
            group, opts.mmap, self.mmap_read_area, self.mmap_write_area)

    def cleanup(self) -> None:
        self.clean_areas()

    def clean_areas(self) -> None:
        mra = self.mmap_read_area
        if mra:
            mra.cleanup()
            self.mmap_read_area = None
        mwa = self.mmap_write_area
        if mwa:
            mwa.cleanup()
            self.mmap_write_area = None

    def setup_connection(self, conn) -> None:
        log("setup_connection(%s) mmap supported=%s", conn, self.mmap_supported)
        if not self.mmap_supported:
            return
        for area in (self.mmap_read_area, self.mmap_write_area):
            if area:
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
        # parse each area
        # older versions don't use a prefix for "read" which used to be the default:
        for prefixes, area in (
            (("read", ""), self.mmap_read_area),
            (("write", ), self.mmap_write_area),
        ):
            log(f"{prefixes} : {area}")
            if not area:
                continue
            found = False
            for prefix in prefixes:
                if prefix:
                    area_caps = mmap_caps.dictget(prefix)
                else:
                    # older versions only have one mmap area:
                    area_caps = mmap_caps
                log(f"caps({prefix})={area_caps!r}")
                if area_caps:
                    try:
                        if area.enable_from_caps(area_caps):
                            found = True
                            break   # no need to try the other prefix
                    except ValueError:
                        log("mmap.parse_server_capabilities(..)", exc_info=True)
                        self.quit(ExitCode.MMAP_TOKEN_FAILURE)
                        return False
            if not found:
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
        return {"mmap": info}

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
        if self.mmap_read_area:
            # duplicate it for legacy unprefixed caps:
            caps.update(self.mmap_read_area.get_caps())
        return {"mmap": caps}
