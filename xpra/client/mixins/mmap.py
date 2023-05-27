# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from random import randint
from typing import Dict, Any, Tuple

from xpra.util import envbool, typedict
from xpra.os_util import get_int_uuid
from xpra.exit_codes import ExitCode
from xpra.scripts.config import TRUE_OPTIONS
from xpra.simple_stats import std_unit
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.log import Logger

log = Logger("mmap")

KEEP_MMAP_FILE = envbool("XPRA_KEEP_MMAP_FILE", False)


class MmapClient(StubClientMixin):
    """
    Mixin for adding mmap support to a client
    """

    def __init__(self):
        super().__init__()
        self.mmap_enabled : bool = False
        self.mmap = None
        self.mmap_token : int = 0
        self.mmap_token_index : int = 0
        self.mmap_token_bytes : int = 0
        self.mmap_filename : str = ""
        self.mmap_size : int = 0
        self.mmap_group : str = ""
        self.mmap_tempfile = None
        self.mmap_delete : bool = False
        self.supports_mmap : bool = True


    def init(self, opts) -> None:
        self.mmap_group = opts.mmap_group
        if os.path.isabs(opts.mmap):
            self.mmap_filename = opts.mmap
            self.supports_mmap = True
        else:
            self.supports_mmap = opts.mmap.lower() in TRUE_OPTIONS


    def cleanup(self) -> None:
        self.clean_mmap()


    def setup_connection(self, conn) -> None:
        if self.supports_mmap:
            self.init_mmap(self.mmap_filename, self.mmap_group, conn.filename)


    def get_root_size(self) -> Tuple[int,int]:
        #subclasses should provide real values
        return 1024, 1024

    def parse_server_capabilities(self, c : typedict) -> bool:
        mmap_caps = c.dictget("mmap")
        if mmap_caps:
            #new format with namespace
            c = typedict(mmap_caps)
            def iget(attrname, default_value=0):
                return c.intget(attrname, default_value)
        else:
            def iget(attrname, default_value=0):
                #legacy format: try different forms, at top level:
                return c.intget(f"mmap.{attrname}") or c.intget(f"mmap_{attrname}", default_value)
        self.mmap_enabled = bool(self.supports_mmap and self.mmap_enabled and iget("enabled"))
        log("parse_server_capabilities(..) mmap_enabled=%s", self.mmap_enabled)
        if self.mmap_enabled:
            from xpra.net.mmap_pipe import read_mmap_token, DEFAULT_TOKEN_BYTES
            mmap_token = iget("token")
            mmap_token_index = iget("token_index", 0)
            mmap_token_bytes = iget("token_bytes", DEFAULT_TOKEN_BYTES)
            token = read_mmap_token(self.mmap, mmap_token_index, mmap_token_bytes)
            if token!=mmap_token:
                log.error("Error: mmap token verification failed!")
                log.error(f" expected {token:x}")
                log.error(f" found {mmap_token:x}")
                self.mmap_enabled = False
                self.quit(ExitCode.MMAP_TOKEN_FAILURE)
                return False
            log.info("enabled fast mmap transfers using %sB shared memory area", std_unit(self.mmap_size, unit=1024))
        #the server will have a handle on the mmap file by now, safe to delete:
        if not KEEP_MMAP_FILE:
            self.clean_mmap()
        return True


    def get_info(self) -> Dict[str,Any]:
        if not self.mmap_enabled:
            return {}
        mmap_info = self.get_raw_caps()
        mmap_info["group"] = self.mmap_group or ""
        return {
            "mmap" : mmap_info,
            }

    def get_caps(self) -> Dict[str,Any]:
        if not self.mmap_enabled:
            return {}
        raw_caps = self.get_raw_caps()
        caps : Dict[str,Any] = {
            "mmap" : raw_caps,
            }
        #pre 2.3 servers only use underscore instead of "." prefix for mmap caps:
        for k,v in raw_caps.items():
            caps["mmap_%s" % k] = v
        caps["mmap.namespace"] = True   #this client understands "mmap.ATTRIBUTE" format
        log(f"mmap caps={caps}")
        return caps

    def get_raw_caps(self) -> Dict[str,Any]:
        return {
            "file"          : self.mmap_filename,
            "size"          : self.mmap_size,
            "token"         : self.mmap_token,
            "token_index"   : self.mmap_token_index,
            "token_bytes"   : self.mmap_token_bytes,
            }

    def init_mmap(self, mmap_filename, mmap_group, socket_filename) -> None:
        log("init_mmap(%s, %s, %s)", mmap_filename, mmap_group, socket_filename)
        from xpra.net.mmap_pipe import (  #pylint: disable=import-outside-toplevel
            init_client_mmap, write_mmap_token,
            DEFAULT_TOKEN_BYTES,
            )
        #calculate size:
        root_w, root_h = self.get_root_size()
        #at least 256MB, or 8 fullscreen RGBX frames:
        mmap_size : int = max(512*1024*1024, root_w*root_h*4*8)
        mmap_size = min(2048*1024*1024, mmap_size)
        self.mmap_enabled, self.mmap_delete, self.mmap, self.mmap_size, self.mmap_tempfile, self.mmap_filename = \
            init_client_mmap(mmap_group, socket_filename, mmap_size, self.mmap_filename)
        if self.mmap_enabled:
            self.mmap_token = get_int_uuid()
            self.mmap_token_bytes = DEFAULT_TOKEN_BYTES
            self.mmap_token_index = randint(0, self.mmap_size - DEFAULT_TOKEN_BYTES)
            write_mmap_token(self.mmap, self.mmap_token, self.mmap_token_index, self.mmap_token_bytes)

    def clean_mmap(self) -> None:
        log("XpraClient.clean_mmap() mmap_filename=%s", self.mmap_filename)
        if self.mmap_tempfile:
            try:
                self.mmap_tempfile.close()
            except Exception as e:
                log("clean_mmap error closing file %s: %s", self.mmap_tempfile, e)
            self.mmap_tempfile = None
        if self.mmap_delete:
            #this should be redundant: closing the tempfile should get it deleted
            if self.mmap_filename and os.path.exists(self.mmap_filename):
                from xpra.net.mmap_pipe import clean_mmap
                clean_mmap(self.mmap_filename)
                self.mmap_filename = ""
