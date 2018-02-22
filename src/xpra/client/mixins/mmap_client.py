# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger("client")

from xpra.exit_codes import EXIT_MMAP_TOKEN_FAILURE
from xpra.platform.features import MMAP_SUPPORTED
from xpra.scripts.config import TRUE_OPTIONS
from xpra.simple_stats import std_unit


"""
Mixin for adding mmap support to a client
"""
class MmapClient(object):
    def __init__(self):
        self.mmap_enabled = False
        self.mmap = None
        self.mmap_token = None
        self.mmap_token_index = 0
        self.mmap_token_bytes = 0
        self.mmap_filename = None
        self.mmap_size = 0
        self.mmap_group = None
        self.mmap_tempfile = None
        self.mmap_delete = False
        self.supports_mmap = MMAP_SUPPORTED


    def init(self, opts):
        if MMAP_SUPPORTED:
            self.mmap_group = opts.mmap_group
            if os.path.isabs(opts.mmap):
                self.mmap_filename = opts.mmap
                self.supports_mmap = True
            else:
                self.supports_mmap = opts.mmap.lower() in TRUE_OPTIONS


    def cleanup(self):
        self.clean_mmap()


    def setup_connection(self, conn):
        if self.supports_mmap:
            self.init_mmap(self.mmap_filename, self.mmap_group, conn.filename)


    def parse_server_capabilities(self):
        c = self.server_capabilities
        self.mmap_enabled = self.supports_mmap and self.mmap_enabled and c.boolget("mmap_enabled")
        if self.mmap_enabled:
            from xpra.net.mmap_pipe import read_mmap_token, DEFAULT_TOKEN_INDEX, DEFAULT_TOKEN_BYTES
            mmap_token = c.intget("mmap_token")
            mmap_token_index = c.intget("mmap_token_index", DEFAULT_TOKEN_INDEX)
            mmap_token_bytes = c.intget("mmap_token_bytes", DEFAULT_TOKEN_BYTES)
            token = read_mmap_token(self.mmap, mmap_token_index, mmap_token_bytes)
            if token!=mmap_token:
                log.error("Error: mmap token verification failed!")
                log.error(" expected '%#x'", mmap_token)
                log.error(" found '%#x'", token)
                self.mmap_enabled = False
                self.quit(EXIT_MMAP_TOKEN_FAILURE)
                return
            log.info("enabled fast mmap transfers using %sB shared memory area", std_unit(self.mmap_size, unit=1024))
        #the server will have a handle on the mmap file by now, safe to delete:
        self.clean_mmap()

    def get_caps(self):
        if self.mmap_enabled:
            return {
                "file"          : self.mmap_filename,
                "size"          : self.mmap_size,
                "token"         : self.mmap_token,
                "token_index"   : self.mmap_token_index,
                "token_bytes"   : self.mmap_token_bytes,
                }
        return {}
    
    def init_mmap(self, mmap_filename, mmap_group, socket_filename):
        log("init_mmap(%s, %s, %s)", mmap_filename, mmap_group, socket_filename)
        from xpra.os_util import get_int_uuid
        from xpra.net.mmap_pipe import init_client_mmap, write_mmap_token, DEFAULT_TOKEN_INDEX, DEFAULT_TOKEN_BYTES
        #calculate size:
        root_w, root_h = self.cp(*self.get_root_size())
        #at least 256MB, or 8 fullscreen RGBX frames:
        mmap_size = max(256*1024*1024, root_w*root_h*4*8)
        mmap_size = min(1024*1024*1024, mmap_size)
        self.mmap_enabled, self.mmap_delete, self.mmap, self.mmap_size, self.mmap_tempfile, self.mmap_filename = \
            init_client_mmap(mmap_group, socket_filename, mmap_size, self.mmap_filename)
        if self.mmap_enabled:
            self.mmap_token = get_int_uuid()
            self.mmap_token_bytes = DEFAULT_TOKEN_BYTES
            self.mmap_token_index = self.mmap_size - DEFAULT_TOKEN_BYTES
            #self.mmap_token_index = DEFAULT_TOKEN_INDEX*2
            #write the token twice:
            # once at the old default offset for older servers,
            # and at the offset we want to use with new servers
            for index in (DEFAULT_TOKEN_INDEX, self.mmap_token_index):
                write_mmap_token(self.mmap, self.mmap_token, index, self.mmap_token_bytes)

    def clean_mmap(self):
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
                self.mmap_filename = None
